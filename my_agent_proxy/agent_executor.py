import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Part,
    Task,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import new_agent_parts_message, new_task
from a2a.utils.errors import ServerError
from a2ui.a2a.parts import parse_response_to_parts
from a2ui.schema.constants import VERSION_0_8
from google.adk.agents.llm_agent import LlmAgent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents import run_config
from google.genai import types

logger = logging.getLogger(__name__)

_USER_ID = "remote_agent"


class A2uiAgentExecutor(AgentExecutor):
    """Generic A2UI AgentExecutor — runs an LlmAgent, converts <a2ui-json> responses to DataParts."""

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
        query = context.get_user_input()
        logger.info(f"Query: {query!r}")

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Ensure session exists
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

        # Run the LLM and collect full response text
        # Convert A2A parts to GenAI parts to support multi-modality (images, etc)
        from google.adk.a2a.converters.event_converter import convert_a2a_part_to_genai_part
        genai_parts = []
        if context.message and context.message.parts:
            for a2a_part in context.message.parts:
                converted = convert_a2a_part_to_genai_part(a2a_part)
                if converted:
                    genai_parts.append(converted)
        
        # Fallback if no valid parts were found
        if not genai_parts:
            genai_parts.append(types.Part.from_text(text=query))

        new_message = types.Content(
            role="user", parts=genai_parts
        )

        full_text_parts = []
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
        logger.info(f"LLM raw output:\n{full_text}")

        # Pre-process: The model frequently invents new markdown tags (like ```a2ui-json).
        # To be completely robust, we extract the outermost JSON array or object directly
        # and forcefully wrap it in the required tags, ignoring whatever the model wrote around it.
        import re
        json_match = re.search(r'(\[.*\]|\{.*\})', full_text, re.DOTALL)
        if json_match:
            cleaned_text = f"<a2ui-json>\n{json_match.group(1)}\n</a2ui-json>"
        else:
            cleaned_text = full_text

        # Convert <a2ui-json> blocks to A2A DataParts
        final_parts = parse_response_to_parts(cleaned_text, fallback_text=full_text or "Done.")
        logger.info(f"Sending {len(final_parts)} part(s) to client")

        await updater.update_status(
            TaskState.completed,
            new_agent_parts_message(final_parts, task.context_id, task.id),
            final=True,
        )

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
