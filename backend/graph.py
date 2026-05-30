import asyncio
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langgraph.checkpoint.base import BaseCheckpointSaver

from schemas import (
    ResumeSchema, JobDescriptionSchema, Answer,
    Question, AnswerEvaluation, ScoreReport, SummaryOutput,
    ResumeAnalysis, ResumeQualitativeFeedback,
)
from services.skill_taxonomy import match_skills, semantic_match_skills
from services.interview_service import (
    extract_resume_schema,
    extract_jd_schema,
    generate_questions_from_schemas,
)
from services.scoring import score_answer, aggregate_scores
from services.claude_service import call_structured, FAST_MODEL, QUALITY_MODEL


# ── Graph state ───────────────────────────────────────────────────────────────

class InterviewState(TypedDict):
    session_id: str
    resume_text: str
    jd_text: str
    resume_preview: str
    jd_preview: str
    resume_schema: Optional[dict]      # ResumeSchema.model_dump()
    jd_schema: Optional[dict]          # JobDescriptionSchema.model_dump()
    cache_hit: bool
    questions: list[dict]              # List[Question.model_dump()]
    current_question_index: int
    answers: list[dict]                # List[Answer.model_dump()]
    phase: str                         # "setup" | "interviewing" | "scoring" | "complete" | "error"
    score_report: Optional[dict]       # ScoreReport.model_dump()
    resume_analysis: Optional[dict]    # ResumeAnalysis.model_dump()
    error: Optional[str]               # set if any node fails


# ── Setup nodes ───────────────────────────────────────────────────────────────

async def extract_schemas_node(state: InterviewState) -> dict:
    """
    Extracts structured schemas from resume and JD text.
    Resume schema is cached in Redis by content hash — skips Claude call on cache hit.
    """
    try:
        resume_schema, cache_hit = await extract_resume_schema(state["resume_text"])
        jd_schema = extract_jd_schema(state["jd_text"])
        return {
            "resume_schema": resume_schema.model_dump(),
            "jd_schema": jd_schema.model_dump(),
            "cache_hit": cache_hit,
        }
    except Exception as e:
        return {"phase": "error", "error": f"Failed to parse documents: {e}"}


def analyze_resume_node(state: InterviewState) -> dict:
    """
    Runs after schema extraction. Deterministic skill match + one LLM call
    for qualitative feedback. Result stored in state and surfaced via SSE
    before the interview begins.
    """
    if state.get("phase") == "error":
        return {}

    try:
        resume = ResumeSchema.model_validate(state["resume_schema"])
        jd     = JobDescriptionSchema.model_validate(state["jd_schema"])

        # Collect all technologies from work history entries
        work_techs = [tech for exp in resume.work_history for tech in exp.technologies]

        # Semantic LLM-based matching (falls back to alias matching on failure)
        skill_match = semantic_match_skills(resume.skills, work_techs, jd.required_skills)
        score       = skill_match["coverage_pct"]
        label       = ("Strong Match" if score >= 75 else
                       "Good Match"   if score >= 50 else
                       "Partial Match" if score >= 25 else
                       "Weak Match")

        # LLM qualitative feedback (flat fields to avoid array schema issues)
        exp_years = resume.total_experience_years
        prompt = f"""You are a career coach reviewing a candidate's resume against a job description.

Candidate: {resume.full_name}, {exp_years} years experience
Resume skills: {', '.join(resume.skills[:20])}
JD role: {jd.role_title}
Required skills matched: {', '.join(skill_match['matched'][:10]) or 'none'}
Required skills missing: {', '.join(skill_match['missing'][:10]) or 'none'}

Provide brief, actionable feedback:
- strength_1: one specific strength of this resume for this role
- strength_2: a second specific strength
- improvement_1: most important thing to add or improve
- improvement_2: second improvement
- improvement_3: third improvement (could be formatting, quantifying achievements, etc.)"""

        try:
            fb = call_structured(prompt, ResumeQualitativeFeedback, model=FAST_MODEL)
            strengths    = [fb.strength_1, fb.strength_2]
            improvements = [fb.improvement_1, fb.improvement_2, fb.improvement_3]
        except Exception:
            strengths    = ["Resume demonstrates relevant technical experience",
                            "Skills align with core role requirements"]
            improvements = [f"Add missing required skills: {', '.join(skill_match['missing'][:3]) or 'none listed'}",
                            "Quantify achievements with metrics (e.g. reduced latency by X%)",
                            "Tailor experience bullet points to mirror JD language"]

        analysis = ResumeAnalysis(
            match_score=round(score, 1),
            match_label=label,
            matched_skills=skill_match["matched"],
            missing_skills=skill_match["missing"],
            extra_skills=skill_match["extra"][:10],
            strengths=strengths,
            improvements=improvements,
        )
        return {"resume_analysis": analysis.model_dump()}

    except Exception as e:
        # Non-fatal: interview can still proceed without the analysis
        return {"resume_analysis": None}


def generate_questions_node(state: InterviewState) -> dict:
    """
    Generates interview questions from extracted schemas.
    All output is Pydantic-validated JSON — no free-form LLM text.
    """
    if state.get("phase") == "error":
        return {}
    try:
        resume = ResumeSchema.model_validate(state["resume_schema"])
        jd = JobDescriptionSchema.model_validate(state["jd_schema"])
        questions = generate_questions_from_schemas(resume, jd)
        return {
            "questions": [q.model_dump() for q in questions],
            "phase": "interviewing",
        }
    except Exception as e:
        return {"phase": "error", "error": f"Failed to generate questions: {e}"}


# ── Interview loop nodes ──────────────────────────────────────────────────────

def ask_question_node(state: InterviewState) -> dict:
    """
    Presents the current question via interrupt().
    Graph execution pauses and is checkpointed to Redis.
    Resumes when POST /sessions/{id}/answer supplies the candidate's answer.
    """
    question = state["questions"][state["current_question_index"]]
    answer_text: str = interrupt(question)

    answer = Answer(
        question_id=question["id"],
        question_text=question["text"],
        answer_text=answer_text,
    )
    return {
        "answers": state["answers"] + [answer.model_dump()],
        "current_question_index": state["current_question_index"] + 1,
    }


# ── Scoring nodes ─────────────────────────────────────────────────────────────

async def score_session_node(state: InterviewState) -> dict:
    """
    Hybrid scoring: all answers evaluated concurrently via LLM (quality score)
    + keyword matching (informational breakdown). Parallel calls keep total
    latency to ~3-5s regardless of question count.
    """
    questions = [Question.model_validate(q) for q in state["questions"]]
    answers   = [Answer.model_validate(a) for a in state["answers"]]

    evaluations: list[AnswerEvaluation] = await asyncio.gather(
        *[score_answer(answer, question) for answer, question in zip(answers, questions)]
    )

    jd = JobDescriptionSchema.model_validate(state["jd_schema"])
    category_scores, skill_coverage, overall_score, grade = aggregate_scores(
        evaluations,
        jd.required_skills,
        answers,
    )

    # Partial ScoreReport — narrative and strengths filled by generate_summary_node
    report = ScoreReport(
        session_id=state["session_id"],
        overall_score=overall_score,
        grade=grade,
        category_scores=category_scores,
        skill_coverage=skill_coverage,
        evaluations=evaluations,
        strengths=[],
        development_areas=[],
        summary_narrative="",
    )
    return {"score_report": report.model_dump()}


def generate_summary_node(state: InterviewState) -> dict:
    """
    Single LLM call to produce narrative summary, strengths, and development areas.
    Falls back to a default summary if the LLM call fails, so the graph always
    completes cleanly regardless of Groq errors.
    """
    report = ScoreReport.model_validate(state["score_report"])
    covered   = [s.skill for s in report.skill_coverage if s.mentioned]
    uncovered = [s.skill for s in report.skill_coverage if not s.mentioned]

    prompt = f"""You are an interview coach giving written feedback after a mock interview.

Candidate results:
- Overall score: {report.overall_score}/100 (Grade: {report.grade})
- Category scores: {', '.join(f'{cs.category} {cs.average_score:.1f}/10' for cs in report.category_scores)}
- Skills demonstrated: {', '.join(covered[:8]) or 'none detected'}
- Skills not mentioned: {', '.join(uncovered[:8]) or 'none'}

Fill in the output fields:
- summary_narrative: 2 sentences summarising overall performance
- strength_1: first observed strength (one sentence)
- strength_2: second observed strength (one sentence)
- development_1: first area to improve (one sentence)
- development_2: second area to improve (one sentence)"""

    try:
        summary = call_structured(prompt, SummaryOutput, model=QUALITY_MODEL)
        strengths         = [summary.strength_1, summary.strength_2]
        development_areas = [summary.development_1, summary.development_2]
        narrative         = summary.summary_narrative
    except Exception:
        grade = report.grade
        strengths         = ["Completed the full interview", "Provided answers across all question categories"]
        development_areas = ["Review expected keywords in the rubric hints", "Practice using precise technical terminology in answers"]
        narrative         = f"Interview completed with an overall grade of {grade} ({report.overall_score:.0f}/100). Review the question breakdown below for detailed keyword feedback."

    updated = state["score_report"].copy()
    updated["strengths"]          = strengths
    updated["development_areas"]  = development_areas
    updated["summary_narrative"]  = narrative

    return {"score_report": updated, "phase": "complete"}


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_setup(state: InterviewState) -> str:
    """Short-circuit to a terminal node if setup failed."""
    if state.get("phase") == "error":
        return "error_node"
    return "ask_question"


def error_node(state: InterviewState) -> dict:
    """Terminal node for failed sessions — surfaces the error in state."""
    return {"phase": "error"}


def route_after_answer(state: InterviewState) -> str:
    """Deterministic routing — no LLM. Loops until all questions are answered."""
    if state["current_question_index"] >= len(state["questions"]):
        return "score_session"
    return "ask_question"


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph(checkpointer: BaseCheckpointSaver):
    workflow = StateGraph(InterviewState)

    workflow.add_node("extract_schemas", extract_schemas_node)
    workflow.add_node("analyze_resume", analyze_resume_node)
    workflow.add_node("generate_questions", generate_questions_node)
    workflow.add_node("ask_question", ask_question_node)
    workflow.add_node("score_session", score_session_node)
    workflow.add_node("generate_summary", generate_summary_node)
    workflow.add_node("error_node", error_node)

    workflow.set_entry_point("extract_schemas")
    workflow.add_edge("extract_schemas", "analyze_resume")
    workflow.add_edge("analyze_resume", "generate_questions")
    workflow.add_conditional_edges(
        "generate_questions",
        route_after_setup,
        {"ask_question": "ask_question", "error_node": "error_node"},
    )
    workflow.add_conditional_edges(
        "ask_question",
        route_after_answer,
        {"ask_question": "ask_question", "score_session": "score_session"},
    )
    workflow.add_edge("score_session", "generate_summary")
    workflow.add_edge("generate_summary", END)
    workflow.add_edge("error_node", END)

    return workflow.compile(checkpointer=checkpointer)
