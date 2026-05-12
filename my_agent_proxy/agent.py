from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
import os
from dotenv import load_dotenv

# Explicitly load the SSL patch for corporate networks
try:
    import pip_system_certs.wrapt_requests
except ImportError:
    pass

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

root_agent = RemoteA2aAgent(
    name="my_agent_proxy",
    agent_card="http://localhost:10007",
    description="A2UI assistant — renders rich components for every question. (Smart Proxy pointing to 10007)",
)
