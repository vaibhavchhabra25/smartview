# SmartView AI Interviewer

A stateful multi-agent mock interview platform. Upload a resume and job description, and the system runs a personalised end-to-end interview — generating questions, collecting answers turn-by-turn, scoring deterministically, and producing a structured feedback report.

## Architecture

```
Browser (React/Vite/TypeScript)
         │  SSE (setup)  REST (interview turns)
         ▼
FastAPI  ──────────────────────────────────────────────────────────
  POST /sessions/stream    → SSE: streams setup progress to browser
  POST /sessions/{id}/answer → resume graph, return next question
  GET  /sessions/{id}/report → fetch ScoreReport after completion
         │
         ▼
LangGraph StateGraph  (graph.py)
  ┌─ extract_schemas ──── async, LLM (Claude Sonnet)
  │    └─ Redis cache: SHA-256(resume) → ResumeSchema (1h TTL)
  ├─ generate_questions ── sync, LLM (Claude Sonnet)
  │    └─ Pydantic tool-use: guaranteed JSON, no hallucinations
  ├─ ask_question ──────── DETERMINISTIC — interrupt(), await answer
  │    └─ loops N times (one per question)
  ├─ score_session ──────── DETERMINISTIC — keyword-overlap scoring
  │    └─ category weights: technical 50% / behavioral 25% / situational 15% / resume 10%
  └─ generate_summary ──── LLM (Claude Haiku) — narrative only
         │
         ▼
Redis (localhost:6379)
  LangGraph checkpointer  → full graph state per session (4h TTL)
  Resume schema cache     → SHA-256 keyed (1h TTL)
```

## LangGraph pipeline

| Node | Type | Purpose |
|---|---|---|
| `extract_schemas` | Async + LLM | Resume → `ResumeSchema`, JD → `JobDescriptionSchema` (Redis-cached) |
| `generate_questions` | Sync + LLM | Schemas → `List[Question]` with rubrics; forced tool-use JSON |
| `ask_question` | **Deterministic** | `interrupt()` — pauses graph, persists to Redis, resumes on answer |
| `score_session` | **Deterministic** | Keyword overlap + weighted aggregation → partial `ScoreReport` |
| `generate_summary` | Sync + LLM (Haiku) | Narrative + strengths/areas from structured report |
| `error_node` | **Deterministic** | Terminal node for failed setups |

~60% of nodes are deterministic — no LLM token cost for routing, scoring, or session management.

## Key design decisions

**Forced tool-use for structured output** — `call_structured()` in `claude_service.py` creates a single Claude tool whose `input_schema` matches the target Pydantic model. The model must fill the schema; it cannot return free text. This eliminates hallucinations and guarantees 100% parseable responses.

**LangGraph `interrupt()` / `Command(resume=)` for stateful turns** — the graph pauses mid-execution at `ask_question`, checkpointing full state to Redis. `POST /sessions/{id}/answer` resumes it with `Command(resume=answer_text)`. No polling, no manual session dicts.

**Deterministic keyword-overlap scoring** — `scoring.py` scores each answer by checking how many rubric keywords appear in the text, then aggregates with category weights. Zero LLM calls in the scoring path.

**SSE for setup progress** — `POST /sessions/stream` uses `astream_events` to emit `on_chain_end` events as each setup node finishes, giving the frontend real-time progress steps (Extracting → Questioning → Ready) instead of a 15-20s blank wait.

## Stack

| Layer | Technology |
|---|---|
| LLM | Groq (llama-3.3-70b-versatile for extraction/questions, llama-3.1-8b-instant for summary) |
| Agent orchestration | LangGraph 0.2+ |
| State persistence | Redis + `langgraph-checkpoint-redis` |
| Backend | FastAPI + Pydantic v2 |
| Frontend | React 18 + Vite + TypeScript |

## Running locally

**Prerequisites:** Python 3.10+, Node 18+, Redis

```bash
# Start Redis
brew services start redis

# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=your_key_here" > .env
python main.py          # → http://localhost:8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev             # → http://localhost:5173
```

Open `http://localhost:5173`, upload a PDF resume and paste a job description, then click **Start Mock Interview**.

## Project structure

```
backend/
  main.py                   FastAPI app, all API routes, lifespan hooks
  graph.py                  LangGraph StateGraph definition
  schemas.py                All Pydantic models
  services/
    parser.py               PDF / DOCX text extraction
    claude_service.py       Anthropic SDK wrapper — call_structured()
    interview_service.py    Schema extraction + question generation
    scoring.py              Deterministic scoring engine
    skill_taxonomy.py       ~150 skill aliases, category weights
    redis_service.py        Resume schema caching helpers

frontend/src/
  App.tsx                   3-phase state machine (setup → interviewing → complete)
  components/
    SetupScreen.tsx         File upload + SSE streaming progress
    InterviewScreen.tsx     Question card, answer input, transcript
    ReportScreen.tsx        Score circle, category bars, skill coverage, Q&A accordion
    ErrorBoundary.tsx       React error boundary
  types/session.ts          TypeScript mirrors of backend Pydantic models
```
