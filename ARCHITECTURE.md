# SmartView AI Interviewer — Architecture & Documentation

## Table of Contents
1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Agentic Architecture — LangGraph](#agentic-architecture--langgraph)
4. [Key Components](#key-components)
5. [Data Flow](#data-flow)
6. [API Reference](#api-reference)
7. [Pydantic Schema Design](#pydantic-schema-design)
8. [Frontend Architecture](#frontend-architecture)
9. [Running the Project](#running-the-project)

---

## Overview

SmartView is a stateful multi-agent mock interview platform. Given a candidate's resume and a job description, it:

1. **Analyses** the resume against the JD — semantic skill matching, qualitative strengths and improvement suggestions
2. **Conducts** a personalised mock interview — turn-by-turn, with voice input support
3. **Scores** each answer using LLM evaluation (quality, depth, structure) rather than keyword overlap
4. **Reports** a full score breakdown, per-question feedback, skill coverage, and an AI-written narrative

The system is built on a **LangGraph StateGraph** that persists the full interview state across HTTP requests, enabling a genuine stateful multi-turn agent without any manual session tracking.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser  (React 18 + Vite + TypeScript)                            │
│                                                                     │
│  SetupScreen → ResumeAnalysisScreen → InterviewScreen → ReportScreen│
│       │               ↑                     │               ↑       │
│  SSE stream      resume_analysis        POST /answer    GET /report │
│  (fetch API)         event              (axios JSON)   (axios JSON) │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  HTTP / SSE
┌──────────────────────────▼──────────────────────────────────────────┐
│  FastAPI  (main.py)                                                 │
│                                                                     │
│  POST /sessions/stream  ──► astream_events ──► SSE to browser      │
│  POST /sessions/{id}/answer ──► graph.ainvoke(Command(resume=...))  │
│  GET  /sessions/{id}/report ──► graph.aget_state(config)            │
│  GET  /sessions/{id}/resume-analysis                                │
│  POST /transcribe  ──► Groq Whisper                                 │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│  LangGraph  StateGraph  (graph.py)                                  │
│                                                                     │
│  extract_schemas → analyze_resume → generate_questions              │
│       → ask_question ↺ (interrupt loop) → score_session             │
│       → generate_summary → END                                      │
│                                                                     │
│  Checkpointer: AsyncSqliteSaver  (checkpoints.db)                   │
└──────────┬──────────────────────────────┬───────────────────────────┘
           │                              │
┌──────────▼──────────┐      ┌────────────▼────────────┐
│  Groq API           │      │  Redis                  │
│                     │      │                         │
│  llama-3.3-70b      │      │  Resume schema cache    │
│  (extraction,       │      │  SHA-256(text) → JSON   │
│   questions,        │      │  TTL: 1 hour            │
│   scoring,          │      │                         │
│   summary)          │      └─────────────────────────┘
│                     │
│  llama-3.1-8b       │
│  (per-answer        │
│   scoring, fast     │
│   ops)              │
│                     │
│  whisper-large-v3   │
│  (voice transcript) │
└─────────────────────┘
```

---

## Agentic Architecture — LangGraph

### Why LangGraph

A mock interview is inherently stateful and multi-turn. A naive approach would store session state in a database and reconstruct context on every request. LangGraph instead models the entire interview as a single **persistent graph execution** that:

- Pauses mid-execution at each question (`interrupt()`)
- Persists full state to SQLite via a checkpointer
- Resumes from exactly where it left off when the next answer arrives (`Command(resume=answer)`)

This means the graph "remembers" the full interview history (schemas, questions, answers, evaluations) without any application-level session management.

### Graph Definition

```
                  ┌─────────────────┐
                  │   __start__     │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │ extract_schemas │  async, LLM
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │ analyze_resume  │  sync, LLM + deterministic
                  └────────┬────────┘
                           │
               ┌───────────▼──────────────┐
               │     generate_questions   │  sync, LLM
               └───────────┬──────────────┘
                           │
              ┌────────────▼─────────────┐
              │  route_after_setup       │  deterministic
              └────────────┬─────────────┘
                    ┌──────┴──────┐
                    │             │
             ┌──────▼──────┐  ┌──▼──────────┐
             │ ask_question│  │ error_node  │
             │ (interrupt) │  └─────────────┘
             └──────┬──────┘
                    │  (graph pauses here, awaits answer via API)
                    │  (resumes with Command(resume=answer_text))
                    │
             ┌──────▼──────────────┐
             │  route_after_answer │  deterministic
             └──────┬──────────────┘
                    │
          ┌─────────┴──────────┐
          │                    │
    ┌─────▼──────┐     ┌───────▼────────┐
    │ ask_question│    │  score_session  │  async, LLM (parallel)
    │  (loop)    │     └───────┬─────────┘
    └────────────┘             │
                       ┌───────▼─────────┐
                       │ generate_summary │  sync, LLM
                       └───────┬─────────┘
                               │
                        ┌──────▼──────┐
                        │   __end__   │
                        └─────────────┘
```

### Nodes

| Node | Type | Model | Responsibility |
|---|---|---|---|
| `extract_schemas` | Async + LLM | Sonnet (quality) | Parses resume PDF/DOCX into `ResumeSchema` + JD into `JobDescriptionSchema`. Checks Redis cache first (SHA-256 of resume text). |
| `analyze_resume` | Sync + LLM | Quality + Fast | Semantic skill matching (LLM) + qualitative feedback (LLM). Emitted to frontend via SSE before questions are generated. |
| `generate_questions` | Sync + LLM | Quality | Generates 6 structured `Question` objects with rubrics (category, difficulty, expected keywords, ideal answer hint). |
| `ask_question` | **Deterministic** | — | Calls `interrupt(question_dict)`. Graph execution pauses and state is checkpointed. Resumes when `POST /sessions/{id}/answer` calls `Command(resume=answer_text)`. Records the answer. |
| `route_after_answer` | **Deterministic** | — | Checks `current_question_index < len(questions)`. Routes back to `ask_question` or forward to `score_session`. |
| `score_session` | Async + LLM | Fast | Runs all answer evaluations concurrently via `asyncio.gather`. Each answer gets an LLM score (0–10), `what_went_well`, and `what_to_improve`. Keyword stats computed in parallel (deterministic). |
| `generate_summary` | Sync + LLM | Quality | Produces narrative, strengths, development areas from the structured `ScoreReport`. Uses flat string fields to avoid Groq array schema issues. |
| `error_node` | **Deterministic** | — | Terminal node for failed setups. Sets `phase = "error"`. |

**~50% of nodes are deterministic** — routing, session management, keyword tracking, and score aggregation involve zero LLM calls.

### The Interrupt / Resume Pattern

This is the core technique enabling stateful multi-turn interviews over stateless HTTP:

```python
# In ask_question_node — graph pauses here
def ask_question_node(state: InterviewState) -> dict:
    question = state["questions"][state["current_question_index"]]
    answer_text: str = interrupt(question)   # ← graph suspends, state checkpointed
    # everything below runs after resume
    answer = Answer(question_id=question["id"], answer_text=answer_text, ...)
    return {"answers": state["answers"] + [answer.model_dump()], ...}
```

```python
# In POST /sessions/{id}/answer — resumes the graph
await graph.ainvoke(Command(resume=body.answer_text), config=config)
```

Each `interrupt()` call checkpoints the full `InterviewState` (all questions, all previous answers, all evaluations) to SQLite. The next HTTP request resumes from exactly that point.

### Forced Structured Output (No Hallucinations)

Every LLM call goes through `call_structured()` in `claude_service.py`, which uses **Groq's function-calling** to force the model to fill a Pydantic schema:

```python
def call_structured(prompt: str, schema: Type[T], model: str = QUALITY_MODEL) -> T:
    tool = {
        "type": "function",
        "function": {
            "name": "output",
            "parameters": schema.model_json_schema(),  # Pydantic → JSON Schema
        }
    }
    response = get_client().chat.completions.create(
        model=model,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "output"}},  # forced
        messages=[...]
    )
    raw = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return schema.model_validate(raw)  # validated against Pydantic model
```

The model **cannot return free text** — it must fill the tool's `parameters` schema. This guarantees 100% parseable, validated responses.

---

## Key Components

### Backend

#### `graph.py` — LangGraph StateGraph
Defines `InterviewState` (TypedDict) and assembles the `StateGraph`. This is the central orchestrator. All business logic routes through here. The compiled graph (with SQLite checkpointer injected at startup via FastAPI lifespan) handles all state persistence automatically.

#### `main.py` — FastAPI Application
- **Lifespan**: opens `AsyncSqliteSaver`, compiles the graph once, stores in `app.state.graph`
- **`POST /sessions/stream`**: SSE endpoint. Reads multipart upload, invokes graph via `astream_events`, emits `progress`, `resume_analysis`, and `session` events as nodes complete
- **`POST /sessions/{id}/answer`**: resumes graph with `Command(resume=answer_text)`
- **`POST /transcribe`**: pipes audio to Groq Whisper, returns `{"text": "..."}`

#### `schemas.py` — Pydantic Models
Single source of truth for all data shapes. Key models:

| Model | Purpose |
|---|---|
| `ResumeSchema` | Structured resume: skills, work history, education |
| `JobDescriptionSchema` | JD: role, required/preferred skills, responsibilities |
| `Question` + `QuestionRubric` | Interview question with category, difficulty, expected keywords |
| `Answer` | Candidate's submitted answer with timestamp |
| `AnswerScore` | LLM evaluation output: score, what_went_well, what_to_improve |
| `AnswerEvaluation` | Combined LLM score + keyword stats for one answer |
| `ScoreReport` | Full report: overall score, grade, category scores, skill coverage, narrative |
| `ResumeAnalysis` | Match score, matched/missing/extra skills, strengths, improvements |
| `SemanticSkillMatch` | LLM output for skill matching (comma-separated strings, avoids array issues) |

#### `services/claude_service.py` — Groq LLM Wrapper
`call_structured(prompt, schema, model)` — the single entry point for all LLM calls. Handles client initialisation, tool schema generation, response parsing, and Pydantic validation.

Two model tiers:
- `QUALITY_MODEL = "llama-3.3-70b-versatile"` — schema extraction, question generation, semantic matching, summary
- `FAST_MODEL = "llama-3.1-8b-instant"` — per-answer scoring (called in parallel, speed matters)

#### `services/scoring.py` — Hybrid Scoring Engine
- `score_answer(answer, question)` — runs `_llm_score_answer()` in a thread pool executor (sync→async bridge), then `_keyword_stats()` deterministically. Returns `AnswerEvaluation` with both LLM score and keyword breakdown.
- `aggregate_scores(evaluations, required_skills, answers)` — weighted category aggregation (technical 50%, behavioral 25%, situational 15%, resume_specific 10%), skill coverage scan, grade mapping.
- All 6 answers scored **concurrently** via `asyncio.gather` in `score_session_node`.

#### `services/skill_taxonomy.py` — Skill Matching
- `match_skills()` — deterministic alias-based matching (fallback)
- `semantic_match_skills(resume_skills, work_techs, jd_required)` — LLM-based matching. Merges explicit skills + work history technologies, asks the quality model to classify every JD skill as covered/missing accounting for synonyms (React = React.js), acronyms (k8s = Kubernetes), and implied experience. Falls back to alias matching on failure.

#### `services/interview_service.py` — Document Intelligence
- `extract_resume_schema(text)` — async, checks Redis cache (SHA-256 key, 1h TTL) before calling LLM
- `extract_jd_schema(text)` — extracts SHORT skill keywords from JD, not full sentences (prompt explicitly converts "Experience building RAG pipelines" → "RAG")
- `generate_questions_from_schemas(resume, jd)` — generates 6 questions: 3 technical, 2 behavioral, 1 resume-specific, mixed difficulties

#### `services/redis_service.py` — Caching
Async Redis helpers for resume schema caching. Soft-fail on all operations — app works without Redis, just re-extracts on every request.

---

## Data Flow

### Session Creation (POST /sessions/stream)

```
Browser                    FastAPI                   LangGraph Graph
  │                           │                           │
  │── POST /sessions/stream ──►│                           │
  │   (multipart: PDF + JD)   │── extract_text() ────────►│
  │                           │                           │ extract_schemas
  │◄── SSE: [extracting] ─────│◄── on_chain_end ──────────│   (LLM: Resume+JD → schemas)
  │                           │                           │   [Redis cache checked first]
  │                           │── astream_events ────────►│
  │◄── SSE: [analyzing] ──────│◄── on_chain_end ──────────│ analyze_resume
  │◄── SSE: resume_analysis ──│   (event["data"]["output"])│   (LLM: semantic skill match
  │                           │                           │    + qualitative feedback)
  │◄── SSE: [questioning] ────│◄── on_chain_end ──────────│ generate_questions
  │                           │                           │   (LLM: 6 structured questions)
  │◄── SSE: [ready] ──────────│                           │ ask_question
  │◄── SSE: session ──────────│◄── stream ends ───────────│   (interrupt() ← graph pauses)
  │   {session_id, Q1, total} │   aget_state(config)      │   [state checkpointed to SQLite]
```

### Interview Turn (POST /sessions/{id}/answer)

```
Browser                    FastAPI                   LangGraph Graph
  │                           │                           │
  │── POST /answer ───────────►│                           │
  │   {answer_text: "..."}    │── ainvoke(               │
  │                           │     Command(resume=text)) ►│ ask_question resumes
  │                           │                           │   records Answer
  │                           │                           │ route_after_answer
  │                           │                           │   → ask_question (loop)
  │                           │                           │     OR → score_session
  │                           │                           │
  │                           │── aget_state(config) ─────►│
  │◄── {phase, next_question} │◄──────────────────────────│
```

### Final Answer → Scoring

```
                        LangGraph Graph
                              │
                        ask_question (last Q)
                              │  interrupt() → resume with answer
                              │
                        route_after_answer → score_session
                              │
                        score_session (async node)
                              │
                        asyncio.gather([
                              │   score_answer(Q1, A1),   ← parallel LLM calls
                              │   score_answer(Q2, A2),   ← all 6 concurrent
                              │   score_answer(Q3, A3),
                              │   ...
                        ])
                              │
                        aggregate_scores()  ← deterministic
                              │
                        generate_summary (LLM)
                              │
                        phase = "complete"
                              │
                           __end__
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/sessions/stream` | Create session. Multipart: `resume` (File) + `jd_text` (Form) or `jd_file` (File). Returns SSE stream. |
| `GET` | `/sessions/{id}` | Full session state including answered transcript. |
| `POST` | `/sessions/{id}/answer` | Submit answer. Body: `{"answer_text": "..."}`. Returns next `SessionResponse`. |
| `GET` | `/sessions/{id}/resume-analysis` | Resume vs JD analysis. Available after session creation. |
| `GET` | `/sessions/{id}/report` | Full `ScoreReport`. Available after `phase == "complete"`. |
| `POST` | `/transcribe` | Transcribe audio. Multipart: `audio` (File, webm/ogg/wav). Returns `{"text": "..."}`. |

### SSE Event Types (`POST /sessions/stream`)

```json
{"type": "progress",        "step": "extracting|analyzing|questioning|ready", "message": "..."}
{"type": "resume_analysis", "data": { ResumeAnalysis }}
{"type": "session",         "data": { SessionResponse }}
{"type": "error",           "message": "..."}
```

---

## Pydantic Schema Design

### Why Pydantic Everywhere

All LLM outputs are validated through Pydantic models. An LLM call either returns a valid model instance or raises — it never silently returns garbage. This is enforced by the forced tool-call pattern in `call_structured()`.

### Handling Groq Array Schema Limitations

Groq's Llama models are unreliable with `List[str]` fields in tool schemas (they return empty arrays or malformed JSON). The workaround used throughout: **flat string fields** instead of arrays, then parse on the Python side:

```python
# Instead of:
class SummaryOutput(BaseModel):
    strengths: List[str]        # ← Groq fails here

# Use:
class SummaryOutput(BaseModel):
    strength_1: str             # ← Groq handles reliably
    strength_2: str

# Then reconstruct:
strengths = [summary.strength_1, summary.strength_2]
```

Same pattern used in `SemanticSkillMatch` (comma-separated strings), `ResumeQualitativeFeedback`, and `SummaryOutput`.

---

## Frontend Architecture

### 4-Phase State Machine (`App.tsx`)

```
'setup'
  │  SetupScreen — upload form, 4-step SSE progress, stale-closure-safe via useRef
  │  onSessionCreated(session, analysis)
  ▼
'analyzing'
  │  ResumeAnalysisScreen — match score bar, skill chips, strengths/improvements
  │  onStart()
  ▼
'interviewing'
  │  InterviewScreen — question card, voice input, answer textarea, transcript
  │  onAnswerSubmitted() → if phase == 'complete' → fetch report
  ▼
'scoring'  (brief loading state while report is fetched)
  ▼
'complete'
  │  ReportScreen — score circle, category bars, skill coverage, per-Q accordion
  │  onRestart() → back to 'setup'
```

### SSE Streaming & Stale Closure Fix

`SetupScreen` reads SSE events inside a `while(true)` loop. React `useState` inside an async closure captures the initial value (always `null`), so `resumeAnalysis` state would never be visible when the `session` event fires.

**Fix**: store the analysis in a `useRef` instead of state. Refs are mutable and always reflect the latest value regardless of closure capture time:

```typescript
const analysisRef = useRef<ResumeAnalysis | null>(null)

// In SSE loop:
} else if (payload.type === 'resume_analysis') {
  analysisRef.current = payload.data   // ref update — visible immediately
} else if (payload.type === 'session') {
  onSessionCreated(payload.data, analysisRef.current)  // always reads latest
}
```

### Voice Input (`useVoiceInput` hook)

```
start() → getUserMedia({ audio: true })
        → MediaRecorder.start(200ms chunks)
        → setState('recording') + timer

stop()  → MediaRecorder.stop()
        → onstop: Blob → FormData → POST /transcribe
        → setState('transcribing')
        → response.text → onTranscribed(text)  ← appended to textarea
        → setState('idle')
```

Browser records in `audio/webm;codecs=opus` (Chrome) or `audio/ogg;codecs=opus` (Firefox). Both accepted by Groq Whisper. Transcribed text appends to the textarea — multiple voice clips can be combined, and the user can edit before submitting.

### `import type` Requirement

All imports from `session.ts` use `import type { ... }` because `tsconfig.app.json` sets `"verbatimModuleSyntax": true`. Without `type`, Vite 8's esbuild strips interface declarations at transform time and the browser's native ES module resolver throws `SyntaxError: does not provide an export named`.

---

## Running the Project

### Prerequisites
- Python 3.10+
- Node.js 18+
- Redis (`brew install redis`)
- Groq API key — free at [console.groq.com](https://console.groq.com)

### Setup

```bash
# 1. Redis
brew services start redis

# 2. Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "GROQ_API_KEY=gsk_..." > .env
python main.py          # → http://localhost:8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev             # → http://localhost:5173
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key. Free tier sufficient for demos. |
| `REDIS_URL` | No | Redis connection string. Defaults to `redis://localhost:6379`. |

### Key Design Trade-offs

| Decision | Alternative | Why this way |
|---|---|---|
| SQLite checkpointer | Redis checkpointer | `langgraph-checkpoint-redis` requires Redis Stack (RediSearch). Standard Homebrew Redis doesn't include it. SQLite works out of the box. |
| Groq (free) | Anthropic Claude | No Gemini/Anthropic API key available. Groq free tier covers all demo usage. |
| Flat string fields in schemas | `List[str]` | Groq's Llama models are unreliable with array tool schemas — returns empty lists or malformed JSON. Flat fields + Python-side parsing is reliable. |
| Parallel `asyncio.gather` for scoring | Sequential scoring | 6 concurrent LLM calls take ~3s total vs ~18s sequential. Latency matters on the final answer submit. |
| SSE for session creation | Regular POST | Setup takes 15–20s. SSE lets the frontend show live progress (4 animated steps) instead of a blank wait. |
