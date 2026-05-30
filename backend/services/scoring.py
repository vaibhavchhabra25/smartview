"""
Hybrid scoring: LLM evaluates answer quality; keyword matching surfaces
which rubric terms were covered (informational, not the score driver).
"""
from schemas import Question, Answer, AnswerEvaluation, AnswerScore, CategoryScore, SkillCoverage, ScoreReport
from services.skill_taxonomy import CATEGORY_WEIGHTS, normalise_skill
from services.claude_service import call_structured, FAST_MODEL
from datetime import datetime
import asyncio
import concurrent.futures


def _keyword_stats(answer: Answer, question: Question) -> tuple[list[str], list[str]]:
    """Returns (matched_keywords, missed_keywords) — informational only, not the score."""
    text = answer.answer_text.lower()
    matched, missed = [], []
    for keyword in question.rubric.expected_keywords:
        kw = keyword.lower()
        if kw in text:
            matched.append(keyword)
            continue
        words = [w for w in kw.split() if len(w) > 3]
        if len(words) > 1 and all(w in text for w in words):
            matched.append(keyword)
        else:
            missed.append(keyword)
    return matched, missed


def _llm_score_answer(answer: Answer, question: Question) -> AnswerScore:
    """
    Single focused LLM call to evaluate one answer.
    Uses FAST_MODEL — called in parallel across all answers.
    """
    category_guidance = {
        "technical":       "Assess technical accuracy, depth, and use of correct concepts.",
        "behavioral":      "Assess use of a concrete example with situation, action, and outcome (STAR format).",
        "situational":     "Assess problem-solving approach, clarity of reasoning, and practicality.",
        "resume_specific": "Assess how specifically and confidently the candidate described their own experience.",
    }
    guidance = category_guidance.get(question.category, "Assess relevance and clarity.")

    prompt = f"""You are an experienced interviewer scoring a candidate's answer.

Question ({question.category}): {question.text}

Candidate's answer: {answer.answer_text}

Scoring guide (0–10):
  0–3  Did not address the question, very superficial, or off-topic
  4–5  Partial answer — touched the topic but lacked depth or a concrete example
  6–7  Solid answer — addressed the question clearly with reasonable detail
  8–9  Strong answer — specific, well-structured, demonstrated real experience
  10   Exceptional — complete, precise, with compelling examples

{guidance}

Return:
- score: a single number 0.0–10.0
- what_went_well: one concise sentence on the strongest part of the answer
- what_to_improve: one concise sentence on the most important gap"""

    try:
        return call_structured(prompt, AnswerScore, model=FAST_MODEL)
    except Exception:
        # Fallback: give a neutral mid score if LLM call fails
        word_count = len(answer.answer_text.split())
        fallback_score = 6.0 if word_count >= 40 else (4.0 if word_count >= 15 else 2.0)
        return AnswerScore(
            score=fallback_score,
            what_went_well="Answer was provided.",
            what_to_improve="Add more specific examples and technical detail.",
        )


async def score_answer(answer: Answer, question: Question) -> AnswerEvaluation:
    """
    Hybrid evaluation: LLM score (primary) + keyword stats (informational).
    LLM call is run in a thread-pool executor so it doesn't block the event loop.
    """
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        llm_result = await loop.run_in_executor(
            pool, _llm_score_answer, answer, question
        )

    matched, missed = _keyword_stats(answer, question)

    return AnswerEvaluation(
        question_id=question.id,
        question_text=question.text,
        category=question.category,
        score=round(min(max(llm_result.score, 0.0), 10.0), 2),
        what_went_well=llm_result.what_went_well,
        what_to_improve=llm_result.what_to_improve,
        keywords_matched=matched,
        keywords_missed=missed,
        weight=question.rubric.weight,
    )


def _grade(overall: float) -> str:
    if overall >= 80:
        return "A"
    if overall >= 65:
        return "B"
    if overall >= 50:
        return "C"
    if overall >= 35:
        return "D"
    return "F"


def compute_skill_coverage(
    answers: list[Answer],
    required_skills: list[str],
) -> list[SkillCoverage]:
    """
    Checks whether each JD-required skill appears (by name) in the candidate's answers.
    Fully deterministic — scans answer text for skill strings.
    """
    all_answers_text = " ".join(a.answer_text.lower() for a in answers)
    coverage = []
    for skill in required_skills:
        canonical = normalise_skill(skill)
        mentioned = canonical.lower() in all_answers_text or skill.lower() in all_answers_text
        coverage.append(SkillCoverage(skill=canonical, mentioned=mentioned))
    return coverage


def aggregate_scores(
    evaluations: list[AnswerEvaluation],
    required_skills: list[str],
    answers: list[Answer],
) -> tuple[list[CategoryScore], list[SkillCoverage], float, str]:
    """
    Aggregates per-answer evaluations into category scores and an overall score.

    Category weights (from skill_taxonomy.CATEGORY_WEIGHTS):
        technical: 50%,  behavioral: 25%,  situational: 15%,  resume_specific: 10%

    Returns (category_scores, skill_coverage, overall_score_0_100, grade).
    """
    by_category: dict[str, list[AnswerEvaluation]] = {}
    for ev in evaluations:
        by_category.setdefault(ev.category, []).append(ev)

    category_scores: list[CategoryScore] = []
    weighted_sum = 0.0
    total_weight = 0.0

    for category, evs in by_category.items():
        avg = sum(e.score for e in evs) / len(evs)
        cat_weight = CATEGORY_WEIGHTS.get(category, 0.10)
        weighted_sum += avg * cat_weight
        total_weight += cat_weight
        category_scores.append(CategoryScore(
            category=category,
            average_score=round(avg, 2),
            weighted_contribution=round(avg * cat_weight, 2),
            question_count=len(evs),
        ))

    # Normalise to 0–100 scale
    overall = (weighted_sum / total_weight * 10) if total_weight > 0 else 0.0
    overall = round(min(overall, 100.0), 1)

    skill_coverage = compute_skill_coverage(answers, required_skills)

    return category_scores, skill_coverage, overall, _grade(overall)
