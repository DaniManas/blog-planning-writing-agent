# 🧠 Blog Writing Agent

> A LangGraph-powered AI agent that **plans**, researches, writes, and illustrates full technical blog posts — end to end — from a single topic prompt.

Built because agentic systems need more than just a single LLM call. They need to **think before they act** — breaking a goal into structured tasks, routing intelligently, parallelising work, and synthesising a coherent result. This project is the embodiment of that idea, applied to technical content creation.

This implementation was developed from a learning baseline and then extended with production-style structure, API surface, stronger fallbacks, and a full end-to-end output pipeline.

---

## Why It Was Built

Most LLM-based writing tools are glorified prompt wrappers — one input, one output, no structure. The goal here was different: to give an agent genuine **planning capabilities**.

Instead of asking a model to "write a blog post," this agent:
1. **Decides** whether it needs to research the topic first
2. **Plans** a structured multi-section outline (a real `Plan` object with typed `Task`s)
3. **Fans out** work across parallel writer nodes — one per section
4. **Reduces** the parallel outputs back into a single coherent post
5. **Enriches** the final draft with AI-generated images placed contextually

This is what separates an *agent* from a chatbot.

---

## What It Does

Given a topic like `"How Mixture of Experts works in LLMs"` or `"This week in AI"`, the agent:

- 🔍 **Routes** the topic — decides if live web research is needed (`closed_book` / `hybrid` / `open_book`)
- 🌐 **Researches** using Tavily, filtering results by recency and relevance
- 🗂️ **Plans** a full blog outline: title, audience, tone, blog kind, and 5–9 typed tasks
- ✍️ **Writes** each section in parallel, with citations where evidence exists
- 🖼️ **Generates** and places contextual AI images (via OpenAI's image API)
- 📄 **Outputs** a polished Markdown file, downloadable as `.md` or a `.zip` bundle

---

## Architecture

The agent is built as a **LangGraph state graph** with a nested subgraph for the image pipeline.

```
__start__
    │
    ▼
 router  ──── needs_research=false ────────────────┐
    │                                               │
    │ needs_research=true                           │
    ▼                                               ▼
research ──────────────────────────────────► orchestrator
                                                    │
                                               fanout (Send)
                                          ┌────┬────┴────┐
                                          ▼    ▼         ▼
                                       worker worker … worker
                                          └────┴────┬────┘
                                                    ▼
                                             reducer (subgraph)
                                          ┌─────────────────────┐
                                          │  merge_content       │
                                          │       ↓              │
                                          │  decide_images       │
                                          │       ↓              │
                                          │ generate_and_place   │
                                          └─────────────────────┘
                                                    │
                                                __end__
```

The full Mermaid flow diagram is available in [`docs/FLOW_DIAGRAM.md`](docs/FLOW_DIAGRAM.md).

### Key Design Patterns

| Pattern | Where Used |
|---|---|
| **Conditional routing** | `router` → `research` or `orchestrator` |
| **Structured LLM output** | Pydantic schemas for `Plan`, `Task`, `EvidenceItem`, `ImageSpec` |
| **Map-reduce (parallel fanout)** | LangGraph `Send` API fans tasks to N concurrent `worker` nodes |
| **Nested subgraph** | Image pipeline runs as a compiled sub-`StateGraph` |
| **Graceful fallbacks** | Every LLM call has a hardcoded fallback if JSON parsing fails |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Agent framework** | [LangGraph](https://github.com/langchain-ai/langgraph) `0.2` |
| **LLM** | OpenAI `gpt-4o-mini` (configurable) via LangChain |
| **Image generation** | OpenAI `gpt-image-1` |
| **Web research** | [Tavily](https://tavily.com/) via `langchain-community` |
| **Data validation** | Pydantic `v2` |
| **UI** | Streamlit |
| **API server** | FastAPI + Uvicorn |
| **Runtime** | Python 3.11 |

---

## Live Demo

- Streamlit app: [https://bloggenie.streamlit.app/](https://bloggenie.streamlit.app/)
- Generation is passcode-protected because the app uses limited OpenAI credits.
- If you would like to test generation, please contact me for demo access.

---

## Project Structure

```
blog-writing-agent/
├── app/
│   └── graph.py          # Full LangGraph pipeline (router → research → orchestrator → workers → reducer)
├── ui/
│   └── streamlit_app.py  # Streamlit frontend with live streaming, plan viewer, and image gallery
├── docs/
│   └── FLOW_DIAGRAM.md   # Mermaid architecture diagram
├── outputs/              # Generated .md files
│   └── images/           # AI-generated images
├── requirements.txt
└── .env                  # API keys (not committed)
```

---

## Getting Started

### 1. Clone & install

```bash
git clone <your-repo-url>
cd blog-writing-agent

uv venv --python 3.11 .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
OPENAI_API_KEY="sk-..."
BWA_MODEL="gpt-4o-mini"
BWA_BASE_URL="https://api.openai.com/v1"
OPENAI_IMAGE_MODEL="gpt-image-1"
TAVILY_API_KEY="tvly-..."      # Optional — enables web research
LOCAL_API_KEY="your_token"     # Optional — secures the FastAPI endpoint
```

> **Tavily is optional.** Without it, the agent falls back to `closed_book` mode and writes from the model's training knowledge only.

### 3. Run the Streamlit UI

```bash
uv run streamlit run ui/streamlit_app.py
```

Open [http://localhost:8501](http://localhost:8501), enter a topic, and hit **Generate Blog**.

### 4. (Optional) Run the FastAPI server

```bash
uv run uvicorn api.server:api --host 127.0.0.1 --port 8000
```

Available endpoints:

- `GET /health` — liveness check
- `POST /generate` — programmatic blog generation (pass `X-API-Key` header if `LOCAL_API_KEY` is set)

---

## The Streamlit UI

The UI exposes the full agent internals in real time across five tabs:

| Tab | What you see |
|---|---|
| 🧩 **Plan** | Structured outline: title, audience, tone, task table |
| 🔎 **Evidence** | Web sources gathered by Tavily, with URLs and dates |
| 📝 **Markdown Preview** | Rendered blog post with inline images |
| 🖼️ **Images** | Generated images with download as `.zip` |
| 🧾 **Logs** | Full streaming event log from the graph |

You can also browse and reload **past generated blogs** directly from the sidebar.

---

## Research Modes

The `router` node classifies every topic into one of three modes before any writing begins:

| Mode | Trigger | Recency window |
|---|---|---|
| `closed_book` | Evergreen concepts (e.g. "What is backpropagation") | None — uses model knowledge |
| `hybrid` | Evergreen + needs current examples/tools | Last 45 days |
| `open_book` | Volatile / news / "latest" / pricing | Last 7 days |

In `open_book` mode, the agent enforces citation discipline: every factual claim in the output must be backed by a URL from the evidence pack, or the worker writes *"Not found in provided sources."*

---

## Requirements

```
Python        >= 3.11
langgraph     == 0.2.67
langchain-core == 0.3.45
langchain-openai == 0.3.7
pydantic      == 2.10.6
streamlit     == 1.42.2
pandas        == 2.2.3
langchain-community == 0.3.19
fastapi       == 0.115.8
uvicorn       == 0.34.0
```

---

## License

MIT
