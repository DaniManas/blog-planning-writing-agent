# LinkedIn Video Script — Blog Writing Agent
**Target length: ~90 seconds**
**Format: Slide intro (30 sec) → Live Streamlit demo (60 sec)**

---

## Part 1 — Slides (30 seconds)
*Screen share your slides in full screen. Speak naturally, one beat per slide.*

---

**[Slide 1 — Title]** *(5 sec)*
> "I built an AI agent that plans, researches, writes, and illustrates full technical blog posts — completely end to end."

---

**[Slide 2 — The Problem]** *(6 sec)*
> "Most AI writing tools are just glorified prompt wrappers. One input, one output. No structure. No awareness of what research is even needed."

---

**[Slide 3 — The Insight]** *(6 sec)*
> "The insight behind this project is simple: agents need to think before they act. So I wanted my agent to have real planning capabilities."

---

**[Slide 4 — How It Works]** *(8 sec)*
> "It runs a five-stage LangGraph pipeline — a router decides if web research is needed, an orchestrator builds a structured plan, then parallel worker nodes write each section simultaneously, and a reducer merges everything with AI-generated images."

---

**[Slide 5 — Tech Stack]** *(5 sec)*
> "It's built on LangGraph, OpenAI, Tavily for web search, and a Streamlit UI — all with typed Pydantic schemas throughout."

---

## Part 2 — Live Demo (60 seconds)
*Switch to your browser with Streamlit running at localhost:8501.*

---

**[Open the app]** *(3 sec)*
> "Here's the app running locally. I'll type in a topic..."

**[Type in the topic field]**
> Type: `"How LangGraph enables agentic AI workflows"`

> "...and hit Generate."

**[Click Generate — watch the status bar]** *(10 sec)*
> "You can see it streaming in real time — the router just classified this as hybrid mode, so it's pulling web research from Tavily right now... and now the orchestrator is building the plan."

**[Switch to the Plan tab once it appears]** *(12 sec)*
> "This is the plan it built — a structured outline with section titles, target word counts, research flags. This is what separates an agent from a chatbot. It thought before it wrote."

**[Switch to the Evidence tab]** *(8 sec)*
> "Here are the web sources it actually pulled — with publication dates and URLs. In open-book mode, every factual claim in the output is cited back to one of these."

**[Switch to Markdown Preview tab]** *(12 sec)*
> "And here's the final blog post — fully written, structured, with an AI-generated image placed contextually inside it. I can download it as Markdown or as a zip bundle with the images."

**[Switch to Logs tab briefly]** *(5 sec)*
> "The logs tab shows the full event stream from the graph — every node, every state update."

**[Back to slide 7 — CTA]** *(10 sec)*
> "The whole project is open source. If you're building agents and want to see how LangGraph's map-reduce pattern works in practice, the link is in the comments. Happy to answer questions!"

---

## Tips for Recording

- Use **Loom** (free) — records screen + webcam bubble, exports MP4 in one click
- Or **QuickTime** on Mac → File → New Screen Recording
- Record at 1920×1080 — LinkedIn plays best at this resolution
- Speak slightly slower than feels natural — it reads better on video
- You don't need to narrate every word above exactly — treat it as a guide, not a script
- Keep the Streamlit app open and ready before you start recording

## LinkedIn Post Caption (copy-paste)

```
🧠 I built a LangGraph agent that plans before it writes.

Most AI writing tools are prompt wrappers — one input, one output.
This one runs a 5-stage pipeline: route → research → plan → write (in parallel) → compose with AI images.

The key insight: I wanted my agent to have real planning capabilities.
So the orchestrator node produces a typed Plan object with Tasks, word targets, and research flags before any writing happens.

Built with: LangGraph · OpenAI · Tavily · Streamlit · FastAPI · Pydantic

Full demo in the video 👆
GitHub: github.com/DaniManas/blog-planning-writing-agent

#AI #LangGraph #AgenticAI #OpenAI #Python #MachineLearning #BuildInPublic
```
