import { useState } from 'react'
import axios from 'axios'
import SetupScreen from './components/SetupScreen'
import ResumeAnalysisScreen from './components/ResumeAnalysisScreen'
import InterviewScreen from './components/InterviewScreen'
import ReportScreen from './components/ReportScreen'
import type { SessionResponse, SessionDetailResponse, TranscriptEntry, ScoreReport, ReportResponse, ResumeAnalysis } from './types/session'
import './App.css'

type AppPhase = 'setup' | 'analyzing' | 'interviewing' | 'scoring' | 'complete'

export default function App() {
  const [phase, setPhase]               = useState<AppPhase>('setup')
  const [sessionId, setSessionId]       = useState<string | null>(null)
  const [session, setSession]           = useState<SessionResponse | null>(null)
  const [transcript, setTranscript]     = useState<TranscriptEntry[]>([])
  const [report, setReport]             = useState<ScoreReport | null>(null)
  const [resumeAnalysis, setResumeAnalysis] = useState<ResumeAnalysis | null>(null)

  const handleSessionCreated = (newSession: SessionResponse, analysis: ResumeAnalysis | null) => {
    setSessionId(newSession.session_id)
    setSession(newSession)
    setTranscript([])
    setReport(null)
    setResumeAnalysis(analysis)
    // If we have analysis, show it first; otherwise go straight to interview
    setPhase(analysis ? 'analyzing' : 'interviewing')
  }

  const handleAnswerSubmitted = async (updated: SessionResponse) => {
    try {
      const detail = await axios.get<SessionDetailResponse>(
        `http://localhost:8000/sessions/${updated.session_id}`
      )
      setTranscript(detail.data.transcript)
    } catch { /* non-fatal */ }

    setSession(updated)

    if (updated.phase === 'complete') {
      setPhase('scoring')
      try {
        const res = await axios.get<ReportResponse>(
          `http://localhost:8000/sessions/${updated.session_id}/report`
        )
        setReport(res.data.report)
        setPhase('complete')
      } catch {
        setPhase('complete')
      }
    }
  }

  const handleRestart = () => {
    setPhase('setup')
    setSessionId(null)
    setSession(null)
    setTranscript([])
    setReport(null)
    setResumeAnalysis(null)
  }

  return (
    <div className="container">
      <h1>SmartView AI Interviewer</h1>

      {phase === 'setup' && (
        <SetupScreen onSessionCreated={handleSessionCreated} />
      )}

      {phase === 'analyzing' && resumeAnalysis && (
        <ResumeAnalysisScreen
          analysis={resumeAnalysis}
          onStart={() => setPhase('interviewing')}
        />
      )}

      {phase === 'interviewing' && session?.current_question && sessionId && (
        <InterviewScreen
          sessionId={sessionId}
          currentQuestion={session.current_question}
          questionNumber={session.question_number}
          totalQuestions={session.total_questions}
          transcript={transcript}
          onAnswerSubmitted={handleAnswerSubmitted}
        />
      )}

      {phase === 'scoring' && (
        <div style={{ textAlign: 'center', padding: '3rem 0' }}>
          <div className="loading-spinner">Scoring your answers and generating feedback...</div>
        </div>
      )}

      {phase === 'complete' && report && (
        <ReportScreen report={report} transcript={transcript} onRestart={handleRestart} />
      )}

      {phase === 'complete' && !report && (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <p>Interview complete. Could not load the score report.</p>
          <button onClick={handleRestart}>Start New Interview</button>
        </div>
      )}
    </div>
  )
}
