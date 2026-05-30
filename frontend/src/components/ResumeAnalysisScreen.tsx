import type { ResumeAnalysis } from '../types/session'

interface Props {
  analysis: ResumeAnalysis
  onStart: () => void
}

const LABEL_COLOR: Record<string, string> = {
  'Strong Match':  '#4caf50',
  'Good Match':    '#8bc34a',
  'Partial Match': '#ff9800',
  'Weak Match':    '#f44336',
}

function MatchBar({ score }: { score: number }) {
  const color = score >= 75 ? '#4caf50' : score >= 50 ? '#8bc34a' : score >= 25 ? '#ff9800' : '#f44336'
  return (
    <div className="match-bar-wrap">
      <div className="match-bar-track">
        <div className="match-bar-fill" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="match-bar-pct" style={{ color }}>{score}%</span>
    </div>
  )
}

export default function ResumeAnalysisScreen({ analysis, onStart }: Props) {
  const labelColor = LABEL_COLOR[analysis.match_label] ?? '#ff9800'

  return (
    <div className="resume-analysis">
      {/* Header */}
      <div className="ra-header">
        <h2>Resume Analysis</h2>
        <p className="subtitle" style={{ marginBottom: 0 }}>
          Here's how your resume stacks up against the job description before we begin.
        </p>
      </div>

      {/* Match score */}
      <div className="ra-card ra-match-card">
        <div className="ra-match-top">
          <div>
            <div className="ra-match-label" style={{ color: labelColor }}>
              {analysis.match_label}
            </div>
            <div className="ra-match-sub">JD skill coverage</div>
          </div>
          <div className="ra-match-score" style={{ color: labelColor }}>
            {analysis.match_score}%
          </div>
        </div>
        <MatchBar score={analysis.match_score} />
      </div>

      {/* Skills grid */}
      <div className="ra-two-col">
        <div className="ra-card">
          <h4 className="ra-card-title">
            <span className="ra-dot green" /> Matched Skills ({analysis.matched_skills.length})
          </h4>
          {analysis.matched_skills.length > 0 ? (
            <div className="ra-chips">
              {analysis.matched_skills.map(s => (
                <span key={s} className="ra-chip green">{s}</span>
              ))}
            </div>
          ) : (
            <p className="ra-empty">No required skills detected on resume.</p>
          )}
        </div>

        <div className="ra-card">
          <h4 className="ra-card-title">
            <span className="ra-dot red" /> Missing Skills ({analysis.missing_skills.length})
          </h4>
          {analysis.missing_skills.length > 0 ? (
            <div className="ra-chips">
              {analysis.missing_skills.map(s => (
                <span key={s} className="ra-chip red">{s}</span>
              ))}
            </div>
          ) : (
            <p className="ra-empty">All required skills are covered.</p>
          )}
        </div>
      </div>

      {/* Extra skills */}
      {analysis.extra_skills.length > 0 && (
        <div className="ra-card">
          <h4 className="ra-card-title">
            <span className="ra-dot blue" /> Additional Skills on Resume
          </h4>
          <div className="ra-chips">
            {analysis.extra_skills.map(s => (
              <span key={s} className="ra-chip blue">{s}</span>
            ))}
          </div>
        </div>
      )}

      {/* Strengths + Improvements */}
      <div className="ra-two-col">
        <div className="ra-card ra-strengths">
          <h4 className="ra-card-title">Strengths</h4>
          <ul className="ra-list">
            {analysis.strengths.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
        <div className="ra-card ra-improvements">
          <h4 className="ra-card-title">Improvements</h4>
          <ul className="ra-list">
            {analysis.improvements.map((imp, i) => <li key={i}>{imp}</li>)}
          </ul>
        </div>
      </div>

      <button onClick={onStart} style={{ marginTop: '0.5rem' }}>
        Start Interview →
      </button>
    </div>
  )
}
