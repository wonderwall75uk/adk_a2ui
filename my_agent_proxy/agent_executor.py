import json
import logging
import re

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    DataPart,
    Part,
    Task,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import new_agent_parts_message, new_task
from a2a.utils.errors import ServerError
from a2ui.a2a.parts import parse_response_to_parts
from google.adk.agents.llm_agent import LlmAgent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents import run_config
from google.genai import types

logger = logging.getLogger(__name__)

_USER_ID = "remote_agent"

# Matches any <a2ui-json> block - non-greedy so multiple blocks are each captured cleanly
_A2UI_TAG_RE = re.compile(r"<a2ui-json>(.*?)</a2ui-json>", re.DOTALL)


def _extract_json_fallback(text: str) -> str | None:
    """
    Scan for the first balanced JSON array or object in `text`.

    Uses a character-by-character walk to find the matching closing bracket,
    correctly handling nested structures and strings — not a greedy regex.
    """
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _extract_user_action(context: RequestContext) -> dict | None:
    """
    Return the userAction dict if a button-click DataPart is present, else None.

    A2UI button clicks arrive as an A2A DataPart whose `data` dict contains:

        {
          "userAction": {
            "name": "submit_incident",
            "surfaceId": "seal-incident-report",
            "sourceComponentId": "submit-btn",
            "timestamp": "...",
            "context": { "fieldName": "value", ... }
          }
        }

    The `context` dict holds the resolved data-model values declared in
    the button's `action.context` list in the A2UI JSON.
    """
    if not (context.message and context.message.parts):
        return None
    for part in context.message.parts:
        if isinstance(part.root, DataPart) and "userAction" in part.root.data:
            return part.root.data["userAction"]
    return None


def _build_action_query(user_action: dict) -> str:
    """
    Convert a userAction dict into a natural-language prompt the LLM can act on.

    The LLM handles ALL routing — no hard-coded action names here.
    The system prompt instructs the LLM on how to respond to USER_ACTION messages,
    making this executor fully action-name-agnostic.
    """
    action_name = user_action.get("name", "unknown_action")
    surface_id  = user_action.get("surfaceId", "")
    ctx         = user_action.get("context", {})

    if ctx:
        ctx_lines = "\n".join(f"  {k}: {v}" for k, v in ctx.items())
    else:
        ctx_lines = "  (no form data submitted)"

    return (
        f"USER_ACTION: {action_name}\n"
        f"Surface: {surface_id}\n"
        f"Submitted form data:\n{ctx_lines}"
    )


def _clean_llm_output(full_text: str) -> str:
    """
    Ensure the LLM output is wrapped in <a2ui-json> tags.

    Priority:
      1. <a2ui-json>…</a2ui-json> tags already present → trust them.
      2. No tags → find the outermost balanced JSON structure and wrap it.
      3. No JSON found at all → return raw text (parse_response_to_parts
         will use its fallback_text).
    """
    if _A2UI_TAG_RE.search(full_text):
        return full_text

    extracted = _extract_json_fallback(full_text)
    if extracted:
        logger.warning("LLM omitted <a2ui-json> tags — wrapping extracted JSON.")
        return f"<a2ui-json>\n{extracted}\n</a2ui-json>"

    logger.warning("Could not find JSON in LLM output — passing raw text to fallback.")
    return full_text


class A2uiAgentExecutor(AgentExecutor):
    """
    Generic A2UI AgentExecutor.

    Handles two input types transparently:

    • Plain text / multimodal messages  →  passed straight to the LLM as-is.
    • A2UI button actions (DataPart)    →  converted to a USER_ACTION: prompt so
                                           the LLM generates the follow-up UI.

    All action routing lives in the LLM via the system prompt — this executor
    is fully action-name-agnostic. New button actions in the UI just work
    without any code changes here.
    """

    def __init__(self, agent: LlmAgent, app_name: str = "a2ui_agent"):
        self._agent = agent
        self._runner = Runner(
            app_name=app_name,
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # ── 1. Determine query ────────────────────────────────────────────────
        user_action = _extract_user_action(context)

        if user_action:
            query = _build_action_query(user_action)
            logger.info(
                f"Button action: name={user_action.get('name')!r}  "
                f"surface={user_action.get('surfaceId')!r}  "
                f"fields={list(user_action.get('context', {}).keys())}"
            )
        else:
            query = context.get_user_input()
            logger.info(f"Text/multimodal query: {query!r}")

        # ── 2. Ensure task + session exist ────────────────────────────────────
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        session = await self._runner.session_service.get_session(
            app_name=self._runner.app_name,
            user_id=_USER_ID,
            session_id=task.context_id,
        )
        if session is None:
            session = await self._runner.session_service.create_session(
                app_name=self._runner.app_name,
                user_id=_USER_ID,
                session_id=task.context_id,
            )

        # ── 3. Build GenAI message (multimodal-aware) ─────────────────────────
        # Button actions: inject the action summary as a single text part.
        # Regular messages: convert all A2A parts (preserves images, files, etc.).
        if user_action:
            genai_parts = [types.Part.from_text(text=query)]
        else:
            from google.adk.a2a.converters.event_converter import convert_a2a_part_to_genai_part
            genai_parts = []
            if context.message and context.message.parts:
                for a2a_part in context.message.parts:
                    converted = convert_a2a_part_to_genai_part(a2a_part)
                    if converted:
                        genai_parts.append(converted)
            if not genai_parts:
                genai_parts = [types.Part.from_text(text=query)]

        new_message = types.Content(role="user", parts=genai_parts)

        # ── 4. Run LLM ────────────────────────────────────────────────────────
        full_text_parts: list[str] = []
        async for event in self._runner.run_async(
            user_id=_USER_ID,
            session_id=session.id,
            run_config=run_config.RunConfig(
                streaming_mode=run_config.StreamingMode.NONE
            ),
            new_message=new_message,
        ):
            if event.content and event.content.parts:
                for p in event.content.parts:
                    if p.text:
                        full_text_parts.append(p.text)

        full_text = "".join(full_text_parts)
        logger.info(f"LLM response length: {len(full_text)} chars")
        logger.debug(f"LLM raw output:\n{full_text}")

        # ── 5. Clean output and dispatch A2A DataParts ────────────────────────
        cleaned_text = _clean_llm_output(full_text)
        final_parts = parse_response_to_parts(cleaned_text, fallback_text=full_text or "Done.")
        logger.info(f"Sending {len(final_parts)} part(s) to client")

        await updater.update_status(
            TaskState.completed,
            new_agent_parts_message(final_parts, task.context_id, task.id),
            final=True,
        )

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
