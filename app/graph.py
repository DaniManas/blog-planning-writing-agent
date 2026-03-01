from __future__ import annotations

import operator
import os
import re
import json
import base64
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict, List, Optional, Literal, Annotated

from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# ============================================================
# Blog Writer (Router → (Research?) → Orchestrator → Workers → ReducerWithImages)
# Patches image capability using your 3-node reducer flow:
#   merge_content -> decide_images -> generate_and_place_images
# ============================================================


# -----------------------------
# 1) Schemas
# -----------------------------
class Task(BaseModel):
    id: int
    title: str
    goal: str = Field(..., description="One sentence describing what the reader should do/understand.")
    bullets: List[str] = Field(..., min_length=3, max_length=6)
    target_words: int = Field(..., description="Target words (120–550).")

    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal["explainer", "tutorial", "news_roundup", "comparison", "system_design"] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task]


class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None  # ISO "YYYY-MM-DD" preferred
    snippet: Optional[str] = None
    source: Optional[str] = None


class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    reason: str
    queries: List[str] = Field(default_factory=list)
    max_results_per_query: int = Field(5)


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


# ---- Image planning schema (ported from your image flow) ----
class ImageSpec(BaseModel):
    placeholder: str = Field(..., description="e.g. [[IMAGE_1]]")
    filename: str = Field(..., description="Save under images/, e.g. qkv_flow.png")
    alt: str
    caption: str
    prompt: str = Field(..., description="Prompt to send to the image model.")
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"


class GlobalImagePlan(BaseModel):
    md_with_placeholders: str
    images: List[ImageSpec] = Field(default_factory=list)

class State(TypedDict):
    topic: str

    # routing / research
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]

    # recency
    as_of: str
    recency_days: int
    max_sections: int
    include_images: bool

    # workers
    sections: Annotated[List[tuple[int, str]], operator.add]  # (task_id, section_md)

    # reducer/image
    merged_md: str
    md_with_placeholders: str
    image_specs: List[dict]

    final: str

OUTPUTS_DIR = ROOT_DIR / "outputs"
IMAGES_DIR = OUTPUTS_DIR / "images"

# -----------------------------
# 2) LLM
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

LLM_MODEL = os.getenv("BWA_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.getenv("BWA_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = OPENAI_API_KEY
if not LLM_API_KEY:
    raise ValueError("Set OPENAI_API_KEY in .env")

llm = ChatOpenAI(
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    temperature=0.2,
)


def _extract_json(text: str) -> dict:
    content = (text or "").strip()
    if not content:
        raise ValueError("Empty model response.")
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if match:
        content = match.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to salvage JSON object embedded in prose.
        obj_match = re.search(r"\{[\s\S]*\}", content)
        if obj_match:
            return json.loads(obj_match.group(0))
        raise

# -----------------------------
# 3) Router
# -----------------------------
ROUTER_SYSTEM = """You are a routing module for a technical blog planner.

Decide whether web research is needed BEFORE planning.

Modes:
- closed_book (needs_research=false): evergreen concepts.
- hybrid (needs_research=true): evergreen + needs up-to-date examples/tools/models.
- open_book (needs_research=true): volatile weekly/news/"latest"/pricing/policy.

If needs_research=true:
- Output 3–10 high-signal, scoped queries.
- For open_book weekly roundup, include queries reflecting last 7 days.
"""

def router_node(state: State) -> dict:
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    ROUTER_SYSTEM
                    + "\nReturn ONLY valid JSON with schema: "
                    + '{"needs_research":false,"mode":"closed_book","reason":"","queries":[],"max_results_per_query":5}'
                )
            ),
            HumanMessage(content=f"Topic: {state['topic']}\nAs-of date: {state['as_of']}"),
        ]
    )
    try:
        decision = RouterDecision.model_validate(_extract_json(response.content))
    except Exception:
        decision = RouterDecision(
            needs_research=True,
            mode="hybrid",
            reason="Fallback due to non-JSON router response",
            queries=[state["topic"]],
            max_results_per_query=5,
        )

    if decision.mode == "open_book":
        recency_days = 7
    elif decision.mode == "hybrid":
        recency_days = 45
    else:
        recency_days = 3650

    return {
        "needs_research": decision.needs_research,
        "mode": decision.mode,
        "queries": decision.queries,
        "recency_days": recency_days,
    }

def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"

# -----------------------------
# 4) Research (Tavily)
# -----------------------------
def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    if not os.getenv("TAVILY_API_KEY"):
        return []
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults  # type: ignore
        tool = TavilySearchResults(max_results=max_results)
        results = tool.invoke({"query": query})
        out: List[dict] = []
        for r in results or []:
            out.append(
                {
                    "title": r.get("title") or "",
                    "url": r.get("url") or "",
                    "snippet": r.get("content") or r.get("snippet") or "",
                    "published_at": r.get("published_date") or r.get("published_at"),
                    "source": r.get("source"),
                }
            )
        return out
    except Exception:
        return []

def _iso_to_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None

RESEARCH_SYSTEM = """You are a research synthesizer.

Given raw web search results, produce EvidenceItem objects.

Rules:
- Only include items with a non-empty url.
- Prefer relevant + authoritative sources.
- Normalize published_at to ISO YYYY-MM-DD if reliably inferable; else null (do NOT guess).
- Keep snippets short.
- Deduplicate by URL.
"""

def research_node(state: State) -> dict:
    queries = (state.get("queries") or [])[:10]
    max_results = 6
    try:
        max_results = max(1, min(10, int(state.get("max_results_per_query", 6))))
    except Exception:
        max_results = 6
    raw: List[dict] = []
    for q in queries:
        raw.extend(_tavily_search(q, max_results=max_results))

    if not raw:
        return {"evidence": []}

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    RESEARCH_SYSTEM
                    + "\nReturn ONLY valid JSON with schema: "
                    + '{"evidence":[{"title":"", "url":"", "published_at":null, "snippet":"", "source":""}]}'
                )
            ),
            HumanMessage(
                content=(
                    f"As-of date: {state['as_of']}\n"
                    f"Recency days: {state['recency_days']}\n\n"
                    f"Raw results:\n{raw}"
                )
            ),
        ]
    )
    try:
        pack = EvidencePack.model_validate(_extract_json(response.content))
    except Exception:
        pack = EvidencePack(evidence=[])

    dedup = {}
    for e in pack.evidence:
        if e.url:
            dedup[e.url] = e
    evidence = list(dedup.values())

    if state.get("mode") == "open_book":
        as_of = date.fromisoformat(state["as_of"])
        cutoff = as_of - timedelta(days=int(state["recency_days"]))
        evidence = [e for e in evidence if (d := _iso_to_date(e.published_at)) and d >= cutoff]

    return {"evidence": evidence}

# -----------------------------
# 5) Orchestrator (Plan)
# -----------------------------
ORCH_SYSTEM = """You are a senior technical writer and developer advocate.
Produce a highly actionable outline for a technical blog post.

Requirements:
- 5–9 tasks, each with goal + 3–6 bullets + target_words.
- Tags are flexible; do not force a fixed taxonomy.

Grounding:
- closed_book: evergreen, no evidence dependence.
- hybrid: use evidence for up-to-date examples; mark those tasks requires_research=True and requires_citations=True.
- open_book: weekly/news roundup:
  - Set blog_kind="news_roundup"
  - No tutorial content unless requested
  - If evidence is weak, plan should explicitly reflect that (don’t invent events).

Output must match Plan schema.
"""

def orchestrator_node(state: State) -> dict:
    mode = state.get("mode", "closed_book")
    evidence = state.get("evidence", [])

    forced_kind = "news_roundup" if mode == "open_book" else None

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    ORCH_SYSTEM
                    + "\nReturn ONLY valid JSON that exactly matches this schema: "
                    + '{"blog_title":"","audience":"","tone":"","blog_kind":"explainer","constraints":[],"tasks":[{"id":1,"title":"","goal":"","bullets":[""],"target_words":250,"tags":[],"requires_research":false,"requires_citations":false,"requires_code":false}]}'
                )
            ),
            HumanMessage(
                content=(
                    f"Topic: {state['topic']}\n"
                    f"Mode: {mode}\n"
                    f"As-of: {state['as_of']} (recency_days={state['recency_days']})\n"
                    f"{'Force blog_kind=news_roundup' if forced_kind else ''}\n\n"
                    f"Evidence:\n{[e.model_dump() for e in evidence][:16]}"
                )
            ),
        ]
    )
    try:
        plan = Plan.model_validate(_extract_json(response.content))
    except Exception:
        plan = Plan(
            blog_title=f"{state['topic'].strip().title()}",
            audience="Developers",
            tone="Clear and practical",
            blog_kind="explainer" if mode != "open_book" else "news_roundup",
            constraints=[],
            tasks=[
                Task(id=1, title="Introduction", goal="Set context for the topic", bullets=["What it is", "Why it matters", "What this blog covers"], target_words=180),
                Task(id=2, title="Core Concepts", goal="Explain key ideas", bullets=["Main components", "How it works", "Common terms"], target_words=260),
                Task(id=3, title="Practical Steps", goal="Show actionable guidance", bullets=["Step-by-step approach", "Tips", "Pitfalls"], target_words=260),
                Task(id=4, title="Conclusion", goal="Summarize and suggest next steps", bullets=["Recap", "When to use", "Next actions"], target_words=160),
            ],
        )
    if forced_kind:
        plan.blog_kind = "news_roundup"

    return {"plan": plan}


# -----------------------------
# 6) Fanout
# -----------------------------
def fanout(state: State):
    assert state["plan"] is not None
    max_sections = state.get("max_sections", 6)
    tasks = state["plan"].tasks[: max(1, int(max_sections))]
    return [
        Send(
            "worker",
            {
                "task": task.model_dump(),
                "topic": state["topic"],
                "mode": state["mode"],
                "as_of": state["as_of"],
                "recency_days": state["recency_days"],
                "plan": state["plan"].model_dump(),
                "evidence": [e.model_dump() for e in state.get("evidence", [])],
            },
        )
        for task in tasks
    ]

# -----------------------------
# 7) Worker
# -----------------------------
WORKER_SYSTEM = """You are a senior technical writer and developer advocate.
Write ONE section of a technical blog post in Markdown.

Constraints:
- Cover ALL bullets in order.
- Target words ±15%.
- Output only section markdown starting with "## <Section Title>".

Scope guard:
- If blog_kind=="news_roundup", do NOT drift into tutorials (scraping/RSS/how to fetch).
  Focus on events + implications.

Grounding:
- If mode=="open_book": do not introduce any specific event/company/model/funding/policy claim unless supported by provided Evidence URLs.
  For each supported claim, attach a Markdown link ([Source](URL)).
  If unsupported, write "Not found in provided sources."
- If requires_citations==true (hybrid tasks): cite Evidence URLs for external claims.

Code:
- If requires_code==true, include at least one minimal snippet.
"""

def worker_node(payload: dict) -> dict:
    task = Task(**payload["task"])
    plan = Plan(**payload["plan"])
    evidence = [EvidenceItem(**e) for e in payload.get("evidence", [])]

    bullets_text = "\n- " + "\n- ".join(task.bullets)
    evidence_text = "\n".join(
        f"- {e.title} | {e.url} | {e.published_at or 'date:unknown'}"
        for e in evidence[:20]
    )

    section_md = llm.invoke(
        [
            SystemMessage(content=WORKER_SYSTEM),
            HumanMessage(
                content=(
                    f"Blog title: {plan.blog_title}\n"
                    f"Audience: {plan.audience}\n"
                    f"Tone: {plan.tone}\n"
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Constraints: {plan.constraints}\n"
                    f"Topic: {payload['topic']}\n"
                    f"Mode: {payload.get('mode')}\n"
                    f"As-of: {payload.get('as_of')} (recency_days={payload.get('recency_days')})\n\n"
                    f"Section title: {task.title}\n"
                    f"Goal: {task.goal}\n"
                    f"Target words: {task.target_words}\n"
                    f"Tags: {task.tags}\n"
                    f"requires_research: {task.requires_research}\n"
                    f"requires_citations: {task.requires_citations}\n"
                    f"requires_code: {task.requires_code}\n"
                    f"Bullets:{bullets_text}\n\n"
                    f"Evidence (ONLY cite these URLs):\n{evidence_text}\n"
                )
            ),
        ]
    ).content.strip()

    return {"sections": [(task.id, section_md)]}

# ============================================================
# 8) ReducerWithImages (subgraph)
#    merge_content -> decide_images -> generate_and_place_images
# ============================================================
def merge_content(state: State) -> dict:
    plan = state["plan"]
    if plan is None:
        raise ValueError("merge_content called without plan.")
    ordered_sections = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]
    body = "\n\n".join(ordered_sections).strip()
    merged_md = f"# {plan.blog_title}\n\n{body}\n"
    return {"merged_md": merged_md}


DECIDE_IMAGES_SYSTEM = """You are an expert technical editor.
Decide if images/diagrams are needed for THIS blog.

Rules:
- Max 3 images total.
- Each image must materially improve understanding (diagram/flow/table-like visual).
- Insert placeholders exactly: [[IMAGE_1]], [[IMAGE_2]], [[IMAGE_3]].
- If no images needed: md_with_placeholders must equal input and images=[].
- Avoid decorative images; prefer technical diagrams with short labels.
Return strictly GlobalImagePlan.
"""

def decide_images(state: State) -> dict:
    if not state.get("include_images", True):
        return {"md_with_placeholders": state["merged_md"], "image_specs": []}

    merged_md = state["merged_md"]
    plan = state["plan"]
    assert plan is not None

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    DECIDE_IMAGES_SYSTEM
                    + "\nReturn ONLY valid JSON with schema: "
                    + '{"md_with_placeholders":"","images":[{"placeholder":"[[IMAGE_1]]","filename":"diagram.png","alt":"","caption":"","prompt":"","size":"1024x1024","quality":"medium"}]}'
                )
            ),
            HumanMessage(
                content=(
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Topic: {state['topic']}\n\n"
                    "Insert placeholders + propose image prompts.\n\n"
                    f"{merged_md}"
                )
            ),
        ]
    )
    try:
        image_plan = GlobalImagePlan.model_validate(_extract_json(response.content))
    except Exception:
        image_plan = GlobalImagePlan(md_with_placeholders=merged_md, images=[])

    # Guarantee at least one image for longer blogs in demo mode.
    # This avoids silent "no-image" outputs when the planner returns images=[].
    if not image_plan.images:
        approx_words = len(re.findall(r"\w+", merged_md))
        if approx_words >= 700:
            fallback_placeholder = "[[IMAGE_1]]"
            md_with_ph = merged_md
            if fallback_placeholder not in md_with_ph:
                first_h2 = re.search(r"\n##\s+", md_with_ph)
                if first_h2:
                    insert_at = first_h2.start()
                    md_with_ph = (
                        md_with_ph[:insert_at]
                        + f"\n\n{fallback_placeholder}\n\n"
                        + md_with_ph[insert_at:]
                    )
                else:
                    md_with_ph = md_with_ph + f"\n\n{fallback_placeholder}\n"

            image_plan = GlobalImagePlan(
                md_with_placeholders=md_with_ph,
                images=[
                    ImageSpec(
                        placeholder=fallback_placeholder,
                        filename=f"{_safe_slug(state['topic'])}_overview.png",
                        alt="Technical overview diagram",
                        caption="Conceptual diagram summarizing the main flow discussed in this article.",
                        prompt=(
                            f"Create a clean technical diagram for a blog titled '{state['topic']}'. "
                            "Use a modern flat style, light background, dark readable labels, arrows showing flow, "
                            "and 4-6 key components. No brand logos, no watermarks."
                        ),
                        size="1536x1024",
                        quality="medium",
                    )
                ],
            )

    return {
        "md_with_placeholders": image_plan.md_with_placeholders,
        "image_specs": [img.model_dump() for img in image_plan.images],
    }


def _openai_generate_image_bytes(prompt: str, size: str = "1536x1024", quality: str = "medium") -> bytes:
    """
    Returns raw image bytes generated by OpenAI image API.
    Requires: OPENAI_API_KEY
    """
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)
    image_model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    resp = client.images.generate(
        model=image_model,
        prompt=prompt,
        size=size,
        quality=quality,
    )

    if not resp.data or not getattr(resp.data[0], "b64_json", None):
        raise RuntimeError("No image bytes returned by OpenAI images API.")

    return base64.b64decode(resp.data[0].b64_json)


def _safe_slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "blog"


def generate_and_place_images(state: State) -> dict:
    plan = state["plan"]
    assert plan is not None

    md = state.get("md_with_placeholders") or state["merged_md"]
    image_specs = state.get("image_specs", []) or []

    # If no images requested, just write merged markdown
    if not image_specs:
        filename = f"{_safe_slug(plan.blog_title)}.md"
        OUTPUTS_DIR.mkdir(exist_ok=True)
        (OUTPUTS_DIR / filename).write_text(md, encoding="utf-8")
        return {"final": md}

    OUTPUTS_DIR.mkdir(exist_ok=True)
    images_dir = IMAGES_DIR
    images_dir.mkdir(exist_ok=True)

    for spec in image_specs:
        placeholder = spec["placeholder"]
        filename = spec["filename"]
        out_path = images_dir / filename

        # generate only if needed
        if not out_path.exists():
            try:
                img_bytes = _openai_generate_image_bytes(
                    spec["prompt"],
                    size=spec.get("size", "1536x1024"),
                    quality=spec.get("quality", "medium"),
                )
                out_path.write_bytes(img_bytes)
            except Exception as e:
                # graceful fallback: keep doc usable
                prompt_block = (
                    f"> **[IMAGE GENERATION FAILED]** {spec.get('caption','')}\n>\n"
                    f"> **Alt:** {spec.get('alt','')}\n>\n"
                    f"> **Prompt:** {spec.get('prompt','')}\n>\n"
                    f"> **Error:** {e}\n"
                )
                md = md.replace(placeholder, prompt_block)
                continue

        img_md = f"![{spec['alt']}](outputs/images/{filename})\n*{spec['caption']}*"
        md = md.replace(placeholder, img_md)

    filename = f"{_safe_slug(plan.blog_title)}.md"
    (OUTPUTS_DIR / filename).write_text(md, encoding="utf-8")
    return {"final": md}

# build reducer subgraph
reducer_graph = StateGraph(State)
reducer_graph.add_node("merge_content", merge_content)
reducer_graph.add_node("decide_images", decide_images)
reducer_graph.add_node("generate_and_place_images", generate_and_place_images)
reducer_graph.add_edge(START, "merge_content")
reducer_graph.add_edge("merge_content", "decide_images")
reducer_graph.add_edge("decide_images", "generate_and_place_images")
reducer_graph.add_edge("generate_and_place_images", END)
reducer_subgraph = reducer_graph.compile()

# -----------------------------
# 9) Build main graph
# -----------------------------
g = StateGraph(State)
g.add_node("router", router_node)
g.add_node("research", research_node)
g.add_node("orchestrator", orchestrator_node)
g.add_node("worker", worker_node)
g.add_node("reducer", reducer_subgraph)

g.add_edge(START, "router")
g.add_conditional_edges("router", route_next, {"research": "research", "orchestrator": "orchestrator"})
g.add_edge("research", "orchestrator")

g.add_conditional_edges("orchestrator", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", END)

graph_app = g.compile()
app = graph_app
