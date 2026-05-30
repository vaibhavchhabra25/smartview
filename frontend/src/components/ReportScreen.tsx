import ReactMarkdown from 'react-markdown'
import type { ScoreReport, TranscriptEntry } from '../types/session'

interface Props {
  report: ScoreReport
  transcript: TranscriptEntry[]
  onRestart: () => void
}

const GRADE_COLOR: Record<string, string> = {
  A: '#4caf50', B: '#8bc34a', C: '#ff9800', D: '#ff5722', F: '#f44336',
}

const CATEGORY_LABEL: Record<string, string> = {
  technical: 'Technical', behavioral: 'Behavioral',
  situational: 'Situational', resume_specific: 'Resume',
}

function ScoreCircle({ score, max = 100 }: { score: number; max?: number }) {
  const pct = (score / max) * 100
  const color = pct >= 80 ? '#4caf50' : pct >= 65 ? '#8bc34a' : pct >= 50 ? '#ff9800' : pct >= 35 ? '#ff5722' : '#f44336'
  const deg = (pct / 100) * 360

  return (
    <div className="score-circle" style={{
      background: `conic-gradient(${color} ${deg}deg, rgba(255,255,255,0.08) ${deg}deg)`,
    }}>
      <div className="score-circle-inner">
        <span className="score-circle-value">{Math.round(score)}</span>
        <span className="score-circle-label">/ {max}</span>
      </div>
    </div>
  )
}

function ScoreBar({ score, max = 10 }: { score: number; max?: number }) {
  const pct = (score / max) * 100
  const color = pct >= 80 ? '#4caf50' : pct >= 60 ? '#8bc34a' : pct >= 40 ? '#ff9800' : '#f44336'
  return (
    <div className="score-bar-track">
      <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

export default function ReportScreen({ report, transcript, onRestart }: Props) {
  const mentionedSkills = report.skill_coverage.filter(s => s.mentioned)
  const missingSkills = report.skill_coverage.filter(s => !s.mentioned)

  return (
    <div className="report-screen">
      {/* Header */}
      <div className="report-header">
        <div className="report-grade" style={{ color: GRADE_COLOR[report.grade] }}>
          {report.grade}
        </div>
        <ScoreCircle score={report.overall_score} />
        <div className="report-narrative">
          <ReactMarkdown>{report.summary_narrative}</ReactMarkdown>
        </div>
      </div>

      {/* Strengths + Development */}
      <div className="report-two-col">
        <div className="report-card strengths-card">
          <h4>Strengths</h4>
          <ul>
            {report.strengths.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
        <div className="report-card develop-card">
          <h4>Areas to Improve</h4>
          <ul>
            {report.development_areas.map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        </div>
      </div>

      {/* Category scores */}
      <div className="report-card">
        <h4>Category Breakdown</h4>
        {report.category_scores.map(cs => (
          <div key={cs.category} className="category-row">
            <div className="category-row-label">
              <span>{CATEGORY_LABEL[cs.category] ?? cs.category}</span>
              <span className="category-row-score">{cs.average_score.toFixed(1)} / 10</span>
            </div>
            <ScoreBar score={cs.average_score} />
          </div>
        ))}
      </div>

      {/* Skill coverage */}
      {report.skill_coverage.length > 0 && (
        <div className="report-card">
          <h4>Skill Coverage</h4>
          <div className="skill-grid">
            {mentionedSkills.map(s => (
              <span key={s.skill} className="skill-chip skill-hit">{s.skill}</span>
            ))}
            {missingSkills.map(s => (
              <span key={s.skill} className="skill-chip skill-miss">{s.skill}</span>
            ))}
          </div>
          <p className="skill-legend">
            <span className="legend-dot hit" /> Mentioned &nbsp;
            <span className="legend-dot miss" /> Not mentioned
          </p>
        </div>
      )}

      {/* Per-question breakdown */}
      <div className="report-card">
        <h4>Question Breakdown</h4>
        {report.evaluations.map((ev, i) => {
          const entry = transcript.find(t => t.question.id === ev.question_id)
          return (
            <details key={ev.question_id} className="eval-entry">
              <summary className="eval-summary">
                <span className="eval-num">Q{i + 1}</span>
                <span className="eval-category">{CATEGORY_LABEL[ev.category] ?? ev.category}</span>
                <span className="eval-q-text">{ev.question_text}</span>
                <span className="eval-score" style={{
                  color: ev.score >= 7 ? '#4caf50' : ev.score >= 4 ? '#ff9800' : '#f44336'
                }}>
                  {ev.score.toFixed(1)}/10
                </span>
              </summary>
              <div className="eval-body">
                {entry?.answer && (
                  <p className="eval-answer">
                    <strong>Your answer:</strong> {entry.answer.answer_text}
                  </p>
                )}
                <div className="eval-feedback-row">
                  <div className="eval-feedback-card went-well">
                    <span className="eval-feedback-label">What went well</span>
                    <span>{ev.what_went_well}</span>
                  </div>
                  <div className="eval-feedback-card improve">
                    <span className="eval-feedback-label">What to improve</span>
                    <span>{ev.what_to_improve}</span>
                  </div>
                </div>
                {(ev.keywords_matched.length > 0 || ev.keywords_missed.length > 0) && (
                  <div className="eval-keywords-section">
                    {ev.keywords_matched.length > 0 && (
                      <div className="eval-keywords">
                        <span className="kw-label hit">Covered:</span>
                        {ev.keywords_matched.map(k => <span key={k} className="keyword-chip kw-hit">{k}</span>)}
                      </div>
                    )}
                    {ev.keywords_missed.length > 0 && (
                      <div className="eval-keywords">
                        <span className="kw-label miss">Missed:</span>
                        {ev.keywords_missed.map(k => <span key={k} className="keyword-chip kw-miss">{k}</span>)}
                      </div>
                    )}
                  </div>
                )}
                {entry?.question.rubric.ideal_answer_hint && (
                  <p className="eval-hint">
                    <strong>Ideal answer hint:</strong> {entry.question.rubric.ideal_answer_hint}
                  </p>
                )}
              </div>
            </details>
          )
        })}
      </div>

      <button onClick={onRestart} style={{ marginTop: '1.5rem' }}>
        Start New Interview
      </button>
    </div>
  )
}
