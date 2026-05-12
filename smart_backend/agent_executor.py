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

        # Check for A2UI Action Execution
        # If the user clicked a button, we might want to intercept it instead of calling the LLM
        if context.message and context.message.parts:
            for part in context.message.parts:
                # A2UI actions usually come as a DataPart or similar structure in the message
                # For this demo, we'll check for the 'submit_incident_report' action name
                if hasattr(part, 'text') and "submit_incident_report" in str(part.text):
                     # Extract form data from context if possible
                     # Since we are in a demo, we can also look at the session state or the last message
                     logger.info("Intercepted 'submit_incident_report' action. Generating completed form image...")
                     
                     # 1. Generate the image
                     image_data = await self._generate_completed_form_image(context)
                     
                     # 2. Return the image as a Part
                     if image_data:
                         await event_queue.enqueue_event(new_agent_parts_message(
                             [types.Part.from_bytes(data=image_data, mime_type="image/png")], 
                             context.current_task.context_id, 
                             context.current_task.id
                         ))
                         
                         # Update task to completed
                         updater = TaskUpdater(event_queue, context.current_task.id, context.current_task.context_id)
                         await updater.update_status(TaskState.completed, final=True)
                         return

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

    async def _generate_completed_form_image(self, context: RequestContext) -> bytes | None:
        """Uses gemini-3-pro-image-preview to generate a completed form image."""
        import os
        from google import genai
        from google.genai import types as genai_types
        
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.error("No API key found for image generation.")
            return None

        client = genai.Client(api_key=api_key, http_options={'verify': False})
        
        # Load the template
        template_path = os.path.join(os.path.dirname(__file__), "resources", "form_template.png")
        if not os.path.exists(template_path):
            logger.error(f"Template not found at {template_path}")
            return None
            
        with open(template_path, "rb") as f:
            template_bytes = f.read()

        # Construct the prompt
        # In a real app, we would pull the actual form data from context.action.context
        # For the demo, we will use a high-quality prompt that 'hallucinates' the completion based on the scenario
        prompt = (
            "Generate a high-fidelity, top-down scan of the provided GXO SEAL INCIDENT REPORT. "
            "The form should be 'completed' by a human hand using a black ballpoint pen. "
            "Write the following information into the corresponding fields: "
            "Date: 2026-05-12, Time: 13:45, Site: Site 1. "
            "Reporting Personnel: Nathan Clarke, Phone: +44 7700 900000. "
            "Seal # on BOL: 248791, Seal # on Trailer: 248791 (Matches). "
            "Description of Damage: The blue plastic seal was found snapped on the ground next to the trailer door. "
            "Additional Notes: Security notified immediately. Trailer remains sealed for investigation. "
            "Ensure the handwriting looks realistic and some checkboxes are marked with an 'X'."
        )

        try:
            # Call Imagen 3 / Gemini Image Generation
            # Note: This requires the specific model name and permissions
            response = client.models.generate_image(
                model="gemini-3-pro-image-preview",
                prompt=prompt,
                config=genai_types.GenerateImageConfig(
                    number_of_images=1,
                    include_rai_reason=True,
                    output_mime_type="image/png",
                )
            )
            
            if response.generated_images:
                return response.generated_images[0].image.image_bytes
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            # Fallback: maybe just return the template for now?
            return template_bytes
            
        return None

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
