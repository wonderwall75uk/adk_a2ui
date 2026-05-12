import os
from dotenv import load_dotenv
import pip_system_certs.wrapt_requests
import asyncio

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models import Gemini

async def run_test():
    try:
        agent = LlmAgent(model=Gemini(model="gemini-3.1-flash-lite"), name="test")
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.artifacts import InMemoryArtifactService
        from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
        from google.genai import types
        runner = Runner(app_name="test", agent=agent, session_service=InMemorySessionService(), artifact_service=InMemoryArtifactService(), memory_service=InMemoryMemoryService())
        
        async for event in runner.run_async(user_id="u", session_id="s", new_message=types.Content(role="user", parts=[types.Part.from_text(text="Hello")])):
            pass
        print("Success")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(run_test())
