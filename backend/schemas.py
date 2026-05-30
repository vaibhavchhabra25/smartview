from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
import uuid


# ── Resume / JD schemas ───────────────────────────────────────────────────────

class WorkExperience(BaseModel):
    company: Optional[str] = "Unknown"
    title: Optional[str] = "Unknown"
    duration_months: Optional[int] = None
    technologies: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: Optional[str] = "Unknown"
    degree: Optional[str] = "Unknown"
    field: Optional[str] = "Unknown"
    year: Optional[int] = None


class ResumeSchema(BaseModel):
    full_name: str
    total_experience_years: float
    skills: List[str]
    work_history: List[WorkExperience]
    education: List[Education]
    certifications: List[str] = Field(default_factory=list)


class JobDescriptionSchema(BaseModel):
    role_title: Optional[str] = "Software Engineer"
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience_required_years: Optional[float] = None
    key_responsibilities: List[str] = Field(default_factory=list)


# ── Interview question / answer ───────────────────────────────────────────────

class QuestionRubric(BaseModel):
    expected_keywords: List[str]
    weight: float = 1.0
    ideal_answer_hint: str


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    category: Literal["technical", "behavioral", "situational", "resume_specific"]
    difficulty: Literal["easy", "medium", "hard"]
    rubric: QuestionRubric


class QuestionList(BaseModel):
    questions: List[Question]


class Answer(BaseModel):
    question_id: str
    question_text: str
    answer_text: str
    submitted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Session state (stored in Redis) ──────────────────────────────────────────

class InterviewSessionState(BaseModel):
    session_id: str
    phase: Literal["interviewing", "complete"] = "interviewing"
    questions: List[Question]
    current_question_index: int = 0
    answers: List[Answer] = Field(default_factory=list)
    resume_preview: str = ""
    jd_preview: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Resume analysis ──────────────────────────────────────────────────────────

class SemanticSkillMatch(BaseModel):
    """LLM output for semantic skill matching — comma-separated strings avoid array schema issues."""
    covered: str   # comma-separated JD skills the candidate HAS (exact names from JD list)
    missing: str   # comma-separated JD skills the candidate LACKS (exact names from JD list)


class ResumeQualitativeFeedback(BaseModel):
    strength_1: str
    strength_2: str
    improvement_1: str
    improvement_2: str
    improvement_3: str


class ResumeAnalysis(BaseModel):
    match_score: float                  # 0–100 (% of JD required skills covered)
    match_label: str                    # "Strong Match" | "Good Match" | "Partial Match" | "Weak Match"
    matched_skills: List[str]
    missing_skills: List[str]
    extra_skills: List[str]             # in resume but not required by JD
    strengths: List[str]
    improvements: List[str]


# ── Scoring ───────────────────────────────────────────────────────────────────

class AnswerScore(BaseModel):
    """Structured output for a single LLM answer evaluation."""
    score: float           # 0.0 – 10.0
    what_went_well: str    # one sentence
    what_to_improve: str   # one sentence


class AnswerEvaluation(BaseModel):
    question_id: str
    question_text: str
    category: str
    score: float                           # 0.0 – 10.0  (from LLM)
    what_went_well: str
    what_to_improve: str
    keywords_matched: List[str]            # informational only
    keywords_missed: List[str]
    weight: float


class CategoryScore(BaseModel):
    category: str
    average_score: float
    weighted_contribution: float
    question_count: int


class SkillCoverage(BaseModel):
    skill: str
    mentioned: bool


class SummaryOutput(BaseModel):
    summary_narrative: str
    strength_1: str
    strength_2: str
    development_1: str
    development_2: str


class ScoreReport(BaseModel):
    session_id: str
    overall_score: float                   # 0–100
    grade: Literal["A", "B", "C", "D", "F"]
    category_scores: List[CategoryScore]
    skill_coverage: List[SkillCoverage]
    evaluations: List[AnswerEvaluation]
    strengths: List[str]
    development_areas: List[str]
    summary_narrative: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── API request / response models ────────────────────────────────────────────

class SessionResponse(BaseModel):
    session_id: str
    phase: Literal["interviewing", "complete"]
    current_question: Optional[Question] = None
    question_number: int
    total_questions: int
    resume_preview: str = ""
    jd_preview: str = ""


class AnswerSubmitRequest(BaseModel):
    answer_text: str


class TranscriptEntry(BaseModel):
    question_number: int
    question: Question
    answer: Optional[Answer] = None


class ReportResponse(BaseModel):
    session_id: str
    report: ScoreReport


class SessionDetailResponse(BaseModel):
    session_id: str
    phase: Literal["interviewing", "complete"]
    current_question: Optional[Question] = None
    question_number: int
    total_questions: int
    transcript: List[TranscriptEntry]
