from __future__ import annotations

from datetime import date
from typing import Any
import os

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from bwa_backend import app as graph_app


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3, description="Blog topic to generate")
    as_of: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    max_sections: int = Field(default=4, ge=1, le=6)
    include_images: bool = Field(default=True)


class GenerateResponse(BaseModel):
    topic: str
    as_of: str
    mode: str | None = None
    needs_research: bool | None = None
    evidence_count: int
    image_count: int
    final_markdown: str
    output_path: str | None = None


api = FastAPI(title="LangGraph Blog Agent API", version="1.0.0")
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.post("/generate", response_model=GenerateResponse)
def generate(payload: GenerateRequest, x_api_key: str | None = Header(default=None)) -> GenerateResponse:
    if LOCAL_API_KEY and x_api_key != LOCAL_API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")

    as_of = payload.as_of or date.today().isoformat()
    inputs: dict[str, Any] = {
        "topic": payload.topic.strip(),
        "mode": "",
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "as_of": as_of,
        "recency_days": 7,
        "max_sections": payload.max_sections,
        "include_images": payload.include_images,
        "sections": [],
        "merged_md": "",
        "md_with_placeholders": "",
        "image_specs": [],
        "final": "",
    }

    if not inputs["topic"]:
        raise HTTPException(status_code=400, detail="topic is required")

    try:
        out = graph_app.invoke(inputs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"generation failed: {exc}") from exc

    plan_obj = out.get("plan")
    title = "blog"
    if hasattr(plan_obj, "blog_title"):
        title = str(plan_obj.blog_title)
    elif isinstance(plan_obj, dict):
        title = str(plan_obj.get("blog_title") or title)

    output_slug = (
        title.strip().lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
        or "blog"
    )
    output_path = f"outputs/{output_slug}.md"

    return GenerateResponse(
        topic=payload.topic,
        as_of=as_of,
        mode=out.get("mode"),
        needs_research=out.get("needs_research"),
        evidence_count=len(out.get("evidence") or []),
        image_count=len(out.get("image_specs") or []),
        final_markdown=out.get("final") or "",
        output_path=output_path,
    )
