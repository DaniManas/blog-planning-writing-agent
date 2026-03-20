# CLAUDE.md — Blog Genie (Blog Writing Agent)

This file gives Claude Code full context about this project so it can assist
effectively without re-reading the entire codebase every session.

---

## What This Project Does

Blog Genie is a LangGraph-powered AI agent that writes complete, research-backed
blog posts from a single topic prompt. It does not just call GPT and return text.
It follows a structured pipeline: classify the topic, search the web, plan the
structure, write sections in parallel, verify citations, generate images, and
save the final blog as a Markdown file.

The core idea: agents should plan before they execute. Most LLM apps take input
and immediately produce output. This project separates planning from execution
deliberately — the orchestrator plans, the workers execute, and never the other
way around.

---

## How To Run

### Streamlit UI (main way to use the app)
```bash
streamlit run ui/streamlit_app.py
```
Opens at http://localhost:8501

### FastAPI server (optional, for programmatic access)
```bash
uvicorn api.server:api --host 127.0.0.1 --port 8000
```

---

## Environment Variables (.env)

```env
OPENAI_API_KEY=sk-...           # Required — LLM + image generation
BWA_MODEL=gpt-4o-mini           # Which model to use
BWA_BASE_URL=https://api.openai.com/v1  # Change to use other providers
OPENAI_IMAGE_MODEL=dall-e-2     # Image generation model
TAVILY_API_KEY=tvly-...         # Optional — enables web research
```

Note: Without TAVILY_API_KEY the agent falls back to closed_book mode and
writes from model knowledge only. Without OPENAI_API_KEY the app will not start.

---

## Project Structure

```
blog-writing-agent/
├── app/
│   ├── graph.py          # THE BRAIN — entire LangGraph pipeline lives here
│   └── __init__.py       # Exports graph_app
├── ui/
│   └── streamlit_app.py  # Web UI with 5 tabs and live streaming
├── api/
│   └── server.py         # FastAPI REST endpoint (same graph_app, different entry)
├── notebooks/            # 6 notebooks showing iterative development
│   ├── 1_bwa_basic.ipynb
│   ├── 2_bwa_research.ipynb
│   ├── 3_bwa_orchestrator.ipynb
│   ├── 4_bwa_workers.ipynb
│   ├── 5_bwa_image.ipynb
│   └── 6_bwa_final.ipynb
├── outputs/              # Generated .md blog files saved here
│   └── images/           # AI-generated images saved here
├── docs/
│   └── FLOW_DIAGRAM.md   # Mermaid architecture diagram
└── requirements.txt
```

The most important file is `app/graph.py`. Everything else supports it.

---

## Pipeline — Node by Node

The pipeline is a LangGraph StateGraph. All nodes share a single `State`
TypedDict that gets progressively filled as the pipeline runs.

### Node 1 — router_node
- Reads: topic, as_of date
- Does: Asks GPT to classify topic into closed_book / hybrid / open_book
- Writes: mode, needs_research, queries, recency_days
- Fallback: If GPT returns bad JSON → default to hybrid mode, use topic as query
- Recency: open_book=7 days, hybrid=45 days, closed_book=3650 days

### Node 2 — research_node (conditional — only runs if needs_research=True)
- Reads: queries, recency_days, as_of
- Does: Calls Tavily for each query, passes raw results to GPT to structure
  into EvidenceItem objects, deduplicates by URL, filters by recency
- Writes: evidence (list of EvidenceItem)
- Fallback: No Tavily key → empty list. GPT parse fails → empty list.
  Pipeline continues without sources.

### Node 3 — orchestrator_node
- Reads: topic, mode, evidence, as_of
- Does: Asks GPT to create a structured Plan with 5-9 Tasks
- Writes: plan (Plan object with blog_title, audience, tone, blog_kind, tasks)
- Fallback: GPT parse fails → hardcoded 4-section plan
  (Introduction, Core Concepts, Practical Steps, Conclusion)
  This is visible when all checkboxes are unchecked in the Plan tab.

### Node 4 — fanout (not a node, a conditional edge function)
- Reads: plan.tasks, evidence, max_sections
- Does: Uses LangGraph Send API to fire all worker nodes simultaneously
- Returns: List of Send() calls — one per task
- Why: All sections write in parallel instead of sequentially (4x faster)

### Node 5 — worker_node (runs N times in parallel)
- Reads: one Task + evidence + plan context (per worker)
- Does: Asks GPT to write one section. Then validates every citation URL
  against allowed_urls (set of URLs from evidence). Fake URLs become
  "(source unavailable)". If no citations at all → adds Sources section.
- Writes: (task_id, section_markdown) tuple into sections list
- Fallback: Always produces text. Citation enforcement runs post-generation.

### Node 6 — merge_content (inside reducer subgraph)
- Reads: all (id, section_text) tuples from sections
- Does: Sorts by task_id, joins into one Markdown document, adds title
- Writes: merged_md
- No GPT call. Pure Python.

### Node 7 — decide_images (inside reducer subgraph)
- Reads: merged_md, topic, include_images flag
- Does: GPT reads full blog, inserts [[IMAGE_1]] placeholders where diagrams help
  If blog is 700+ words but GPT adds no images → forces one placeholder
- Writes: md_with_placeholders, image_specs
- Fallback: GPT parse fails → return blog unchanged, no images

### Node 8 — generate_and_place_images (inside reducer subgraph)
- Reads: md_with_placeholders, image_specs
- Does: For each placeholder — calls dall-e-2, saves .png to outputs/images/,
  replaces [[IMAGE_1]] with real Markdown image tag. Saves final .md file.
- Writes: final (complete blog string)
- Fallback: Image API fails → replace placeholder with [IMAGE GENERATION FAILED]
  error block. Blog still saves.

---

## Key Design Decisions

### Why 3 routing modes instead of just "search or don't"
open_book / hybrid / closed_book with different recency windows gives the system
fine-grained control. Calling Tavily for "what is machine learning" wastes API
calls and introduces irrelevant recent results. The router prevents this.

### Why planning is a separate node from writing
Early versions had the orchestrator also write the first section. Quality was
noticeably worse. Separating planning from writing lets GPT focus on one job
at a time. The orchestrator thinks about structure. Workers think about prose.

### Why use Send API for workers
LangGraph's Send API fires all workers simultaneously. Without it, sections
would be written sequentially — one at a time. With 4 sections at 30 seconds
each, parallelism saves ~90 seconds per blog.

### Why citation enforcement exists
Without it, GPT fabricates plausible-looking URLs. The allowed_urls whitelist
contains only URLs actually returned by Tavily. Every link in worker output is
checked against this list. Non-matching URLs are replaced with
"(source unavailable)". This prevents hallucinated sources reaching the reader.

### Why URL normalization matters
Initial implementation used exact string matching on URLs. Bug found: Tavily
sometimes returns http:// while GPT cites https:// for the same article.
Exact match fails. Fix: normalize both URLs by stripping protocol and trailing
slashes before comparing. fptsoftware.com == fptsoftware.com regardless of
http/https prefix.

### Why a nested subgraph for the reducer
merge_content + decide_images + generate_and_place_images are grouped into a
compiled sub-StateGraph called reducer_subgraph. The main graph treats this
as a single "reducer" node. This keeps the main graph clean and makes the
image pipeline independently testable and reusable.

### Why _extract_json exists
GPT often wraps JSON responses in markdown code blocks (```json ... ```) or
adds prose around the JSON. json.loads() fails on both. _extract_json tries:
1. Strip backtick wrapper and parse
2. Find any {...} in the text and parse
3. If both fail — raise, which triggers the node's except block

### Why every node has try/except
Defensive engineering. If any GPT call returns bad JSON, the pipeline must not
crash. Each node has a hardcoded fallback that produces a usable result.
The blog may be lower quality without web research or with a generic plan,
but it always finishes.

---

## Pydantic Schemas (in app/graph.py)

All LLM outputs are validated against these schemas:

- `RouterDecision` — router output (mode, needs_research, queries)
- `EvidenceItem` — one web article (title, url, snippet, published_at, source)
- `EvidencePack` — list of EvidenceItem (research node output)
- `Task` — one section's instructions (title, goal, bullets, target_words, flags)
- `Plan` — full blog outline (blog_title, audience, tone, blog_kind, tasks)
- `ImageSpec` — one image (placeholder, filename, prompt, size, quality)
- `GlobalImagePlan` — all images + blog with placeholders

If GPT response doesn't match the schema → Pydantic raises → except block runs.

---

## What Was Built vs What AI Generated

### Designed and owned by Manas:
- Overall architecture (how many nodes, what each does, input/output of each)
- 3-mode routing system (closed_book / hybrid / open_book with recency logic)
- Fanout pattern using Send API for parallel execution
- Citation enforcement logic (allowed_urls whitelist concept)
- Fallback strategy for every node
- Node connection logic (which node routes to which)
- Bug diagnosis: URL normalization fix for http vs https mismatch
- Iterative development through 6 notebooks

### Generated with AI assistance:
- Pydantic schema boilerplate (Task, Plan, EvidenceItem etc.)
- System prompt strings (ROUTER_SYSTEM, ORCH_SYSTEM, WORKER_SYSTEM)
- FastAPI server scaffolding (api/server.py)
- Streamlit UI layout and tab structure
- Image decision and placement nodes (decide_images, generate_and_place_images)

---

## Common Issues

### App won't start
Check OPENAI_API_KEY in .env. Must start with sk- (not gsk_ which is Groq).

### Token limit exceeded (if using Groq)
Groq free tier has low TPM limits. Parallel workers hit limit simultaneously.
Fix: reduce max_sections to 2, or switch back to OpenAI gpt-4o-mini.

### Images failing with 403
Check OPENAI_IMAGE_MODEL in .env. Set to dall-e-2. gpt-image-1 requires
higher account tier. Remove TOGETHER_API_KEY if present — it takes priority
over OpenAI and the free model no longer exists.

### Plan checkboxes all unchecked (requires_research all False)
Orchestrator is using fallback plan — GPT response couldn't be parsed.
Usually caused by a small/weak model. Switch to gpt-4o-mini.

### Running from wrong directory
All commands must be run from the project root or the worktree directory.
The app reads .env relative to its location.

---

## Testing The Pipeline

Best way to test each mode:

- closed_book: "What is backpropagation in neural networks"
- hybrid: "Python best practices for production code"
- open_book: "Latest AI trends in 2026"

Check the Logs tab after generation to see every node that ran and the
final state including evidence_count, mode, and sections_done.
