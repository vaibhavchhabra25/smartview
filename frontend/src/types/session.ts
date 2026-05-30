export interface QuestionRubric {
  expected_keywords: string[]
  weight: number
  ideal_answer_hint: string
}

export type QuestionCategory = 'technical' | 'behavioral' | 'situational' | 'resume_specific'
export type QuestionDifficulty = 'easy' | 'medium' | 'hard'

export interface Question {
  id: string
  text: string
  category: QuestionCategory
  difficulty: QuestionDifficulty
  rubric: QuestionRubric
}

export interface Answer {
  question_id: string
  question_text: string
  answer_text: string
  submitted_at: string
}

export interface TranscriptEntry {
  question_number: number
  question: Question
  answer: Answer | null
}

export type SessionPhase = 'interviewing' | 'complete'

export interface SessionResponse {
  session_id: string
  phase: SessionPhase
  current_question: Question | null
  question_number: number
  total_questions: number
  resume_preview: string
  jd_preview: string
}

export interface SessionDetailResponse {
  session_id: string
  phase: SessionPhase
  current_question: Question | null
  question_number: number
  total_questions: number
  transcript: TranscriptEntry[]
}

export interface ResumeAnalysis {
  match_score: number
  match_label: string
  matched_skills: string[]
  missing_skills: string[]
  extra_skills: string[]
  strengths: string[]
  improvements: string[]
}

export interface AnswerEvaluation {
  question_id: string
  question_text: string
  category: string
  score: number
  what_went_well: string
  what_to_improve: string
  keywords_matched: string[]
  keywords_missed: string[]
  weight: number
}

export interface CategoryScore {
  category: string
  average_score: number
  weighted_contribution: number
  question_count: number
}

export interface SkillCoverage {
  skill: string
  mentioned: boolean
}

export interface ScoreReport {
  session_id: string
  overall_score: number
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  category_scores: CategoryScore[]
  skill_coverage: SkillCoverage[]
  evaluations: AnswerEvaluation[]
  strengths: string[]
  development_areas: string[]
  summary_narrative: string
  generated_at: string
}

export interface ReportResponse {
  session_id: string
  report: ScoreReport
}
