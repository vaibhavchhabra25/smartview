from schemas import ResumeSchema, JobDescriptionSchema, Question, QuestionList
from services.claude_service import call_structured
from services.redis_service import get_cached_resume_schema, set_cached_resume_schema


async def extract_resume_schema(resume_text: str) -> tuple[ResumeSchema, bool]:
    """Returns (schema, cache_hit). Caches result in Redis by SHA-256 of resume text."""
    cached = await get_cached_resume_schema(resume_text)
    if cached:
        return cached, True

    prompt = f"""Extract structured information from this resume text.

Resume:
{resume_text}

Extract all skills (as a flat list of strings), work history, education, and certifications.
For total_experience_years, sum up all work experience durations. If duration is unclear, estimate from context."""
    schema = call_structured(prompt, ResumeSchema)
    await set_cached_resume_schema(resume_text, schema)
    return schema, False


def extract_jd_schema(jd_text: str) -> JobDescriptionSchema:
    prompt = f"""Extract structured information from this job description.

Job Description:
{jd_text}

For required_skills and preferred_skills, extract SHORT skill keywords (1-4 words each), NOT full sentences.
Convert descriptive requirements into concise skill names:
  "Strong programming skills in Python"              → "Python"
  "Experience building RAG pipelines"                → "RAG"
  "Hands-on experience with Generative AI / LLMs"   → "Generative AI", "LLMs"
  "Experience with LangChain / LlamaIndex"           → "LangChain", "LlamaIndex"
  "Experience with AWS / Azure / GCP"                → "AWS", "Azure", "GCP"  (list each separately)
  "Strong SQL skills"                                → "SQL"
  "Understanding of embeddings and vector search"    → "vector embeddings", "vector search"
  "Experience with PySpark / Spark"                  → "PySpark"
  "Strong knowledge of prompt engineering"           → "prompt engineering"
  "Experience processing structured/unstructured data" → "data processing"
  "Experience building data pipelines"               → "data pipelines"
  "Experience with data ingestion and modeling"      → "data modeling"

Also extract role title, years of experience required, and key responsibilities."""
    return call_structured(prompt, JobDescriptionSchema)


def generate_questions_from_schemas(
    resume: ResumeSchema,
    jd: JobDescriptionSchema,
) -> list[Question]:
    """
    Generates structured interview questions given pre-extracted schemas.
    Called by the LangGraph generate_questions node.
    """
    prompt = f"""You are an expert technical interviewer. Generate 6 interview questions for this candidate.

Candidate Profile:
- Name: {resume.full_name}
- Experience: {resume.total_experience_years} years
- Skills: {', '.join(resume.skills[:20])}
- Recent role: {resume.work_history[0].title if resume.work_history else 'N/A'} at {resume.work_history[0].company if resume.work_history else 'N/A'}

Target Role: {jd.role_title}
Required Skills: {', '.join(jd.required_skills[:15])}
Key Responsibilities: {'; '.join(jd.key_responsibilities[:5])}

Generate exactly 6 questions:
- 3 technical questions (covering required skills and responsibilities)
- 2 behavioral questions (STAR format, relevant to the role)
- 1 resume_specific question (about a specific project or experience from the resume)

Mix difficulties: at least 1 easy, 2 medium, 2 hard.

For each question's rubric:
- expected_keywords: 4-5 SHORT keywords or phrases (1-3 words each) that would naturally appear in a strong spoken answer. Use common words a candidate would actually say, not formal jargon. For behavioral questions use words like "resolved", "collaborated", "outcome", "stakeholders". For technical questions use the technology names themselves (e.g. "useState", "index", "cache", "Docker").
- ideal_answer_hint: one sentence describing what a strong answer covers."""

    result = call_structured(prompt, QuestionList)
    return result.questions


async def generate_interview_questions(
    resume_text: str,
    jd_text: str,
) -> tuple[list[Question], bool]:
    """Convenience wrapper used by the legacy /analyze endpoint."""
    resume, cache_hit = await extract_resume_schema(resume_text)
    jd = extract_jd_schema(jd_text)
    questions = generate_questions_from_schemas(resume, jd)
    return questions, cache_hit
