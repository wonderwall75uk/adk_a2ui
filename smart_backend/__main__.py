import logging
import os
import sys

# Ensure the my_agent package directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

import click
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2ui.a2a.extension import get_a2ui_agent_extension
from a2ui.schema.constants import VERSION_0_8
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from backend_agent import root_agent
from agent_executor import A2uiAgentExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:10007"


def build_agent_card() -> AgentCard:
    extensions = [get_a2ui_agent_extension(VERSION_0_8, accepts_inline_catalogs=False, supported_catalog_ids=[])]
    return AgentCard(
        name="A2UI Assistant Proxy",
        description="A helpful assistant that renders rich A2UI components for every response.",
        url=BASE_URL,
        version="1.0.0",
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=False, extensions=extensions),
        skills=[
            AgentSkill(
                id="a2ui_chat",
                name="A2UI Chat",
                description="Answer any question with rich A2UI components.",
                tags=["a2ui", "chat"],
                examples=["Tell me about the solar system", "Compare Python vs JavaScript"],
            )
        ],
    )


@click.command()
@click.option("--host", default="localhost")
@click.option("--port", default=10007)
def main(host, port):
    executor = A2uiAgentExecutor(root_agent, app_name="a2ui_assistant")
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    server = A2AStarletteApplication(agent_card=build_agent_card(), http_handler=handler)

    import uvicorn
    app = server.build()
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    logger.info(f"Starting A2UI Assistant A2A server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
