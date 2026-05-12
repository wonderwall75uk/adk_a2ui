# ADK + A2UI Demo

An [Agent Development Kit (ADK)](https://google.github.io/adk-docs/) agent that generates rich, interactive [A2UI v0.8](https://a2ui-composer.ag-ui.com/) interfaces for every response — forms, tabs, confirmation flows, ranked lists, sliders, date pickers and more — using Gemini.

## Architecture

```
Browser (localhost:8000)
  └── ADK Web UI
        └── my_agent_proxy/     ← RemoteA2aAgent (ADK entry point)
              └── HTTP → my_agent A2A server (localhost:10003)
                            └── LlmAgent (Gemini 2.0 Flash)
                                  └── a2ui v0.8 system prompt + examples
```

Two processes run concurrently:
| Process | What it is | Port |
|---------|-----------|------|
| `my_agent` | A2A server — runs the LLM, converts `<a2ui-json>` responses to A2A DataParts | 10003 |
| `adk web` | ADK web UI — serves the chat interface, proxies via `my_agent_proxy` | 8000 |

## Prerequisites

- **Python 3.12** (3.11 may work; 3.13 not tested)
- **Git**
- A **Gemini API key** — get one free at [aistudio.google.com](https://aistudio.google.com/app/apikey)

> **Windows users — important:** The `litellm` transitive dependency has very long internal file paths that exceed the Windows 260-character path limit. Create your virtual environment at a **short path** such as `C:\venv\a2ui` rather than inside the project folder.

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/wonderwall75uk/adk_a2ui.git
cd adk_a2ui
```

### 2. Create and activate a virtual environment

**Windows (short path to avoid long-path issues):**
```powershell
python -m venv C:\venv\a2ui
C:\venv\a2ui\Scripts\activate
```

**macOS / Linux:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Important — `a2a-sdk` version:** This project requires `a2a-sdk==0.3.26`. Version 1.x has a completely different API and is **not compatible**. The pinned `requirements.txt` handles this automatically.

### 4. Set your API key

Copy `.env.example` to `.env` and add your Gemini key:

```bash
cp .env.example .env
```

Edit `.env`:
```
GOOGLE_API_KEY=AIza...your_key_here...
```

### 5. Apply the ADK web button-text patch

There is a bug in the a2ui theme bundled with `google-adk==1.33.0` where button label text is invisible (same colour as the button background). Run the patch script once after installing:

```bash
python patch_adk_web.py
```

You should see:
```
Patched successfully: main-TCIQIOZ3.js
```

The script is safe to run again — it detects if the patch is already applied.

## Running

You need **two terminals**, both with the virtual environment activated and run from the repo root.

### Terminal 1 — A2A Agent Server

```bash
python -m my_agent
```

Expected output:
```
INFO:     Started server process
INFO:     Uvicorn running on http://localhost:10003
```

### Terminal 2 — ADK Web UI

```bash
adk web
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Then open **http://127.0.0.1:8000** in your browser, select **my_agent_proxy** from the agent dropdown, and start chatting.

## What it can do

The agent generates rich A2UI interfaces for any query. Try:

| Prompt | What renders |
|--------|-------------|
| `Tell me about the solar system` | Tabbed informational card with facts |
| `Top 5 programming languages` | Ranked list with cards |
| `Compare Python vs JavaScript` | Side-by-side comparison tabs |
| `Create a task intake form` | Full form with priority chips, team checkboxes, date picker, urgency toggle |
| `I want to give feedback` | Satisfaction slider + multi-select + text area |
| `Ask me to confirm deleting something` | Confirmation card with warning icon + detail list |

## Project structure

```
adk_a2ui/
├── my_agent/                   # A2A server (port 10003)
│   ├── __init__.py
│   ├── __main__.py             # uvicorn entry point + AgentCard
│   ├── agent.py                # LlmAgent with full a2ui v0.8 system prompt
│   ├── agent_executor.py       # A2A executor — runs LLM, parses <a2ui-json> → DataParts
│   └── examples/0.8/           # Few-shot examples injected into the system prompt
│       ├── intake_form.json
│       ├── feedback_form.json
│       ├── confirm_action.json
│       ├── overview_tabs.json
│       ├── comparison.json
│       └── ranked_list.json
├── my_agent_proxy/             # ADK web entry point
│   ├── __init__.py
│   └── agent.py                # RemoteA2aAgent → localhost:10003
├── requirements.txt            # Pinned dependencies
├── patch_adk_web.py            # One-time button-text colour fix
├── .env.example                # API key template
└── .gitignore
```

## How A2UI rendering works in ADK web

ADK web only renders A2UI components when an event travels through the A2A conversion pipeline (`RemoteA2aAgent`). A plain `LlmAgent` used directly with `adk web` cannot render A2UI — this is why the architecture uses a two-process approach:

1. `my_agent_proxy` is an ADK-native `RemoteA2aAgent` that ADK web can load
2. It proxies every message to `my_agent` (an A2A server) over HTTP
3. `my_agent` uses `parse_response_to_parts()` to convert `<a2ui-json>…</a2ui-json>` output from Gemini into A2A `DataPart` objects
4. These DataParts flow back through the A2A pipeline and ADK web renders them as A2UI components

## Troubleshooting

**Button labels are invisible (same colour as background)**
Run `python patch_adk_web.py`. If it says "Already patched" but the issue persists, hard-refresh the browser (Ctrl+Shift+R).

**`ModuleNotFoundError: No module named 'a2a.server.apps'`**
You have `a2a-sdk` version 1.x installed. Pin it: `pip install a2a-sdk==0.3.26`.

**`RemoteA2aAgent` import errors**
Ensure `google-adk==1.33.0` is installed: `pip show google-adk`.

**Windows: `pip install` fails with path-too-long errors**
Create your venv at a short path: `python -m venv C:\venv\a2ui`.

**Agent not responding / empty events in ADK web**
Check that Terminal 1 (`python -m my_agent`) is running and shows no errors. The proxy silently fails if port 10003 is not reachable.

**`adk web` picks up the wrong agent**
Run `adk web` from the **repo root** — ADK discovers agents by scanning subdirectories for packages with a `root_agent`. Both `my_agent_proxy` and `my_agent` will appear; select `my_agent_proxy`.
