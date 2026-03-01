# Blog Planning & Writing Agent

LangGraph-based AI blog agent that routes topics, optionally researches with Tavily, plans sections, writes in parallel, and composes a final markdown post with generated images.

## Project Structure

```text
app/          # LangGraph workflow
api/          # FastAPI server (health + generate)
ui/           # Streamlit frontend
docs/         # Architecture/flow docs
notebooks/    # Learning/experimentation notebooks
outputs/      # Generated markdown and images
```

## Setup

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

Create `.env` in repo root:

```env
OPENAI_API_KEY="..."
BWA_MODEL="gpt-4o-mini"
BWA_BASE_URL="https://api.openai.com/v1"
OPENAI_IMAGE_MODEL="gpt-image-1"
TAVILY_API_KEY="..."
LOCAL_API_KEY="your_local_token"
```

## Run Streamlit

```bash
uv run streamlit run ui/streamlit_app.py
```

## Run FastAPI (local only)

```bash
uv run uvicorn api.server:api --host 127.0.0.1 --port 8000
```

## API Endpoints

- `GET /health`
- `POST /generate` (optional `X-API-Key` header if `LOCAL_API_KEY` is set)

