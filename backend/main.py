import uuid
import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from services.parser import extract_text
from services.interview_service import generate_interview_questions
from services.claude_service import get_client as get_groq_client
from graph import build_graph, InterviewState
from schemas import (
    SessionResponse,
    SessionDetailResponse,
    ReportResponse,
    ScoreReport,
    AnswerSubmitRequest,
    TranscriptEntry,
    Question,
    Answer,
    ResumeAnalysis,
)
from typing import Optional

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


# ── App lifespan: initialise checkpointer and compile graph ──────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield


app = FastAPI(title="SmartView AI Interview API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _graph_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _build_session_response(session_id: str, state: dict) -> SessionResponse:
    phase = state.get("phase", "interviewing")
    questions = state.get("questions", [])
    idx = state.get("current_question_index", 0)

    current_question = None
    question_number = idx + 1

    if phase == "interviewing" and idx < len(questions):
        current_question = Question.model_validate(questions[idx])
    elif phase == "complete":
        question_number = len(questions)

    return SessionResponse(
        session_id=session_id,
        phase=phase,
        current_question=current_question,
        question_number=question_number,
        total_questions=len(questions),
        resume_preview=state.get("resume_preview", ""),
        jd_preview=state.get("jd_preview", ""),
    )


def _build_detail_response(session_id: str, state: dict) -> SessionDetailResponse:
    phase = state.get("phase", "interviewing")
    questions = state.get("questions", [])
    answers_raw = state.get("answers", [])
    idx = state.get("current_question_index", 0)

    answers_by_qid = {a["question_id"]: Answer.model_validate(a) for a in answers_raw}

    transcript = []
    for i, q_dict in enumerate(questions):
        q = Question.model_validate(q_dict)
        answer = answers_by_qid.get(q.id)
        transcript.append(TranscriptEntry(question_number=i + 1, question=q, answer=answer))

    current_question = None
    question_number = idx + 1
    if phase == "interviewing" and idx < len(questions):
        current_question = Question.model_validate(questions[idx])
    elif phase == "complete":
        question_number = len(questions)

    return SessionDetailResponse(
        session_id=session_id,
        phase=phase,
        current_question=current_question,
        question_number=question_number,
        total_questions=len(questions),
        transcript=transcript,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "SmartView AI Interview API is running"}


@app.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: Request,
    resume: UploadFile = File(...),
    jd_file: Optional[UploadFile] = File(None),
    jd_text: Optional[str] = Form(None),
):
    """
    Upload resume + job description to start an interview session.
    Runs the LangGraph setup subgraph (extract schemas → generate questions)
    and pauses at the first question. Returns session_id and first question.
    """
    try:
        resume_bytes = await resume.read()
        resume_text = extract_text(resume_bytes, resume.filename)

        job_description_text = ""
        if jd_file:
            jd_bytes = await jd_file.read()
            job_description_text = extract_text(jd_bytes, jd_file.filename)
        elif jd_text:
            job_description_text = jd_text
        else:
            raise HTTPException(status_code=400, detail="Job description is required (file or text).")

        session_id = str(uuid.uuid4())
        config = _graph_config(session_id)

        initial_state: InterviewState = {
            "session_id": session_id,
            "resume_text": resume_text,
            "jd_text": job_description_text,
            "resume_preview": resume_text[:200] + "...",
            "jd_preview": job_description_text[:200] + "...",
            "resume_schema": None,
            "jd_schema": None,
            "cache_hit": False,
            "questions": [],
            "current_question_index": 0,
            "answers": [],
            "phase": "setup",
            "score_report": None,
            "resume_analysis": None,
            "error": None,
        }

        # Runs: extract_schemas → analyze_resume → generate_questions → ask_question (interrupt)
        await request.app.state.graph.ainvoke(initial_state, config=config)

        snapshot = await request.app.state.graph.aget_state(config)
        state = snapshot.values

        if state.get("phase") == "error":
            raise HTTPException(status_code=422, detail=state.get("error", "Setup failed."))

        return _build_session_response(session_id, state)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request):
    """Returns full session state including the answered transcript so far."""
    config = _graph_config(session_id)
    snapshot = await request.app.state.graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _build_detail_response(session_id, snapshot.values)


@app.post("/sessions/{session_id}/answer", response_model=SessionResponse)
async def submit_answer(session_id: str, body: AnswerSubmitRequest, request: Request):
    """
    Submit an answer to the current question.
    Resumes the LangGraph graph with the answer text, which triggers the
    ask_question node to record it, then routes to the next question or finish.
    """
    config = _graph_config(session_id)
    snapshot = await request.app.state.graph.aget_state(config)

    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found.")
    if snapshot.values.get("phase") == "complete":
        raise HTTPException(status_code=400, detail="Interview is already complete.")

    # Resume the interrupted graph with the candidate's answer
    await request.app.state.graph.ainvoke(
        Command(resume=body.answer_text),
        config=config,
    )

    updated = await request.app.state.graph.aget_state(config)
    return _build_session_response(session_id, updated.values)


@app.post("/sessions/stream")
async def create_session_stream(
    request: Request,
    resume: UploadFile = File(...),
    jd_file: Optional[UploadFile] = File(None),
    jd_text: Optional[str] = Form(None),
):
    """
    SSE version of POST /sessions.
    Streams progress events while the setup subgraph runs (schema extraction +
    question generation), then emits a final 'session' event with the first question.

    Event types:
      {"type": "progress", "step": "parsing"|"extracting"|"questioning", "message": "..."}
      {"type": "session",  "data": SessionResponse}
      {"type": "error",    "message": "..."}
    """
    try:
        resume_bytes = await resume.read()
        resume_text = extract_text(resume_bytes, resume.filename)

        job_description_text = ""
        if jd_file:
            jd_bytes = await jd_file.read()
            job_description_text = extract_text(jd_bytes, jd_file.filename)
        elif jd_text:
            job_description_text = jd_text
        else:
            raise HTTPException(status_code=400, detail="Job description is required.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    session_id = str(uuid.uuid4())

    async def event_stream():
        config = _graph_config(session_id)
        initial_state: InterviewState = {
            "session_id": session_id,
            "resume_text": resume_text,
            "jd_text": job_description_text,
            "resume_preview": resume_text[:200] + "...",
            "jd_preview": job_description_text[:200] + "...",
            "resume_schema": None,
            "jd_schema": None,
            "cache_hit": False,
            "questions": [],
            "current_question_index": 0,
            "answers": [],
            "phase": "setup",
            "score_report": None,
            "error": None,
        }

        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        try:
            yield sse({"type": "progress", "step": "extracting",
                       "message": "Extracting resume skills and experience..."})

            async for event in request.app.state.graph.astream_events(
                initial_state, config, version="v2"
            ):
                name = event.get("name", "")
                ev = event["event"]

                if ev == "on_chain_end" and name == "extract_schemas":
                    yield sse({"type": "progress", "step": "analyzing",
                               "message": "Analysing resume against job description..."})
                elif ev == "on_chain_end" and name == "analyze_resume":
                    raw = event.get("data", {}).get("output", {}).get("resume_analysis")
                    if raw:
                        yield sse({"type": "resume_analysis", "data": raw})
                    yield sse({"type": "progress", "step": "questioning",
                               "message": "Generating tailored interview questions..."})
                elif ev == "on_chain_end" and name == "generate_questions":
                    yield sse({"type": "progress", "step": "ready",
                               "message": "Finalising interview..."})

            snapshot = await request.app.state.graph.aget_state(config)
            state = snapshot.values

            if state.get("phase") == "error":
                yield sse({"type": "error", "message": state.get("error", "Setup failed.")})
                return

            session_resp = _build_session_response(session_id, state)
            yield sse({"type": "session", "data": session_resp.model_dump()})

        except Exception as e:
            yield sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/sessions/{session_id}/resume-analysis")
async def get_resume_analysis(session_id: str, request: Request):
    config   = _graph_config(session_id)
    snapshot = await request.app.state.graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found.")
    raw = snapshot.values.get("resume_analysis")
    if not raw:
        raise HTTPException(status_code=404, detail="Resume analysis not available.")
    return {"session_id": session_id, "analysis": ResumeAnalysis.model_validate(raw)}


@app.get("/sessions/{session_id}/report", response_model=ReportResponse)
async def get_report(session_id: str, request: Request):
    """
    Returns the full score report after the interview is complete.
    Available only after phase='complete'.
    """
    config = _graph_config(session_id)
    snapshot = await request.app.state.graph.aget_state(config)

    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found.")

    phase = snapshot.values.get("phase")
    if phase != "complete":
        raise HTTPException(status_code=400, detail=f"Interview not complete yet (phase: {phase}).")

    raw_report = snapshot.values.get("score_report")
    if not raw_report:
        raise HTTPException(status_code=404, detail="Score report not found.")

    return ReportResponse(
        session_id=session_id,
        report=ScoreReport.model_validate(raw_report),
    )


@app.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Receives a recorded audio blob (webm/ogg/wav) and returns the transcribed text
    using Groq's Whisper large-v3-turbo model.
    """
    try:
        audio_bytes = await audio.read()
        filename = audio.filename or "answer.webm"

        transcription = get_groq_client().audio.transcriptions.create(
            file=(filename, audio_bytes),
            model="whisper-large-v3-turbo",
            response_format="text",
            language="en",
        )
        return {"text": transcription.strip() if isinstance(transcription, str) else transcription.text.strip()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")


# ── Legacy endpoint (Phase 1 compatibility) ───────────────────────────────────

@app.post("/analyze")
async def analyze_candidate(
    resume: UploadFile = File(...),
    jd_file: Optional[UploadFile] = File(None),
    jd_text: Optional[str] = Form(None),
):
    try:
        resume_bytes = await resume.read()
        resume_text = extract_text(resume_bytes, resume.filename)

        job_description_text = ""
        if jd_file:
            jd_bytes = await jd_file.read()
            job_description_text = extract_text(jd_bytes, jd_file.filename)
        elif jd_text:
            job_description_text = jd_text
        else:
            raise HTTPException(status_code=400, detail="Job description is required.")

        questions, _ = await generate_interview_questions(resume_text, job_description_text)
        return {
            "questions": [q.model_dump() for q in questions],
            "resume_preview": resume_text[:200] + "...",
            "jd_preview": job_description_text[:200] + "...",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
