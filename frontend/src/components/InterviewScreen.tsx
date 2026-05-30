import { useState, useCallback } from 'react'
import axios from 'axios'
import type { Question, SessionResponse, TranscriptEntry } from '../types/session'
import { useVoiceInput } from '../hooks/useVoiceInput'

interface Props {
  sessionId: string
  currentQuestion: Question
  questionNumber: number
  totalQuestions: number
  transcript: TranscriptEntry[]
  onAnswerSubmitted: (session: SessionResponse) => void
}

const CATEGORY_LABEL: Record<Question['category'], string> = {
  technical: 'Technical', behavioral: 'Behavioral',
  situational: 'Situational', resume_specific: 'Resume',
}

const DIFFICULTY_COLOR: Record<Question['difficulty'], string> = {
  easy: '#4caf50', medium: '#ff9800', hard: '#f44336',
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
      <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2"/>
    </svg>
  )
}

export default function InterviewScreen({
  sessionId, currentQuestion, questionNumber, totalQuestions, transcript, onAnswerSubmitted,
}: Props) {
  const [answerText, setAnswerText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState<string | null>(null)

  const progressPct = ((questionNumber - 1) / totalQuestions) * 100

  const handleTranscribed = useCallback((text: string) => {
    // Append to existing text (allows multiple voice clips) with a space separator
    setAnswerText(prev => prev ? `${prev.trimEnd()} ${text}` : text)
    setError(null)
  }, [])

  const handleVoiceError = useCallback((msg: string) => {
    setError(msg)
  }, [])

  const { state: voiceState, formattedTime, start, stop } = useVoiceInput({
    onTranscribed: handleTranscribed,
    onError: handleVoiceError,
  })

  const handleSubmit = async () => {
    if (!answerText.trim()) { setError('Please write or record an answer first.'); return }
    setSubmitting(true)
    setError(null)
    try {
      const res = await axios.post<SessionResponse>(
        `http://localhost:8000/sessions/${sessionId}/answer`,
        { answer_text: answerText }
      )
      setAnswerText('')
      onAnswerSubmitted(res.data)
    } catch (err: any) {
      setError(err.response?.data?.detail ?? 'Failed to submit answer.')
    } finally {
      setSubmitting(false)
    }
  }

  const busy = submitting || voiceState === 'transcribing'
  const answeredEntries = transcript.filter(e => e.answer !== null)

  return (
    <div>
      {/* Progress */}
      <div className="progress-header">
        <span className="progress-label">Question {questionNumber} of {totalQuestions}</span>
        <div className="progress-bar-track">
          <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
        </div>
        <div className="dot-row">
          {Array.from({ length: totalQuestions }).map((_, i) => (
            <div key={i} className={`dot ${i < questionNumber - 1 ? 'dot-done' : i === questionNumber - 1 ? 'dot-current' : 'dot-pending'}`} />
          ))}
        </div>
      </div>

      {/* Question card */}
      <div className="question-card active-question">
        <div className="question-meta">
          <span className="question-number">Q{questionNumber}</span>
          <span className="category-badge">{CATEGORY_LABEL[currentQuestion.category]}</span>
          <span className="difficulty-badge" style={{ color: DIFFICULTY_COLOR[currentQuestion.difficulty] }}>
            {currentQuestion.difficulty}
          </span>
        </div>
        <p className="question-text">{currentQuestion.text}</p>
      </div>

      {/* Answer input */}
      <div className="answer-section">
        <textarea
          className="answer-textarea"
          placeholder={
            voiceState === 'recording'     ? 'Recording… click Stop when done.' :
            voiceState === 'transcribing'  ? 'Transcribing your answer…' :
            'Type your answer, or use the mic button below to speak it.'
          }
          value={answerText}
          onChange={e => setAnswerText(e.target.value)}
          rows={6}
          disabled={busy}
        />

        {/* Voice controls row */}
        <div className="voice-row">
          <div className="voice-controls">
            {voiceState === 'idle' && (
              <button
                className="mic-btn"
                onClick={start}
                disabled={busy}
                title="Record answer"
                type="button"
              >
                <MicIcon />
                <span>Record</span>
              </button>
            )}

            {voiceState === 'recording' && (
              <button
                className="mic-btn recording"
                onClick={stop}
                type="button"
              >
                <span className="rec-dot" />
                <span>{formattedTime}</span>
                <StopIcon />
                <span>Stop</span>
              </button>
            )}

            {voiceState === 'transcribing' && (
              <div className="mic-btn transcribing">
                <span className="spinner" />
                <span>Transcribing…</span>
              </div>
            )}
          </div>

          <div className="answer-footer">
            <span className="char-count">{answerText.length} chars</span>
            {error && <span className="error-msg inline">{error}</span>}
          </div>
        </div>
      </div>

      <button onClick={handleSubmit} disabled={busy || !answerText.trim()}>
        {submitting ? 'Submitting…' :
         questionNumber < totalQuestions ? 'Submit & Next Question →' : 'Submit Final Answer →'}
      </button>

      {/* Previous Q&A transcript */}
      {answeredEntries.length > 0 && (
        <div className="transcript">
          <h3 className="transcript-title">Previous Questions</h3>
          {answeredEntries.map(entry => (
            <div key={entry.question.id} className="transcript-entry">
              <div className="transcript-q">
                <span className="transcript-num">Q{entry.question_number}</span>
                <span className="transcript-category">{CATEGORY_LABEL[entry.question.category]}</span>
                <span className="transcript-text">{entry.question.text}</span>
              </div>
              <div className="transcript-a">
                <span className="transcript-a-label">Your answer:</span>
                <span className="transcript-a-text">{entry.answer!.answer_text}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
