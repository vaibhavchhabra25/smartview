import { useState, useRef } from 'react'
import type { SessionResponse, ResumeAnalysis } from '../types/session'

interface Props {
  onSessionCreated: (session: SessionResponse, analysis: ResumeAnalysis | null) => void
}

type ProgressStep = 'idle' | 'extracting' | 'analyzing' | 'questioning' | 'ready' | 'error'

const STEPS: { key: ProgressStep; label: string }[] = [
  { key: 'extracting',  label: 'Extracting skills & experience' },
  { key: 'analyzing',   label: 'Analysing resume fit' },
  { key: 'questioning', label: 'Generating interview questions' },
  { key: 'ready',       label: 'Finalising interview' },
]

function ProgressSteps({ step }: { step: ProgressStep }) {
  const activeIdx = STEPS.findIndex(s => s.key === step)
  return (
    <div className="setup-progress">
      {STEPS.map((s, i) => {
        const done    = activeIdx > i
        const current = activeIdx === i
        return (
          <div key={s.key} className={`setup-step ${done ? 'done' : current ? 'active' : 'pending'}`}>
            <span className="setup-step-dot">{done ? '✓' : i + 1}</span>
            <span className="setup-step-label">{s.label}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function SetupScreen({ onSessionCreated }: Props) {
  const [resume, setResume] = useState<File | null>(null)
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [jdText, setJdText] = useState('')
  const [jdMode, setJdMode] = useState<'file' | 'text'>('text')
  const [loading, setLoading]   = useState(false)
  const [step, setStep]         = useState<ProgressStep>('idle')
  const [progressMsg, setProgressMsg] = useState('')
  const [error, setError]       = useState<string | null>(null)

  // ref so the SSE closure always reads the latest value (avoids stale closure bug)
  const analysisRef = useRef<ResumeAnalysis | null>(null)

  const handleStart = async () => {
    if (!resume)                             { setError('Please upload a resume.'); return }
    if (jdMode === 'file' && !jdFile)        { setError('Please upload a job description file.'); return }
    if (jdMode === 'text' && !jdText.trim()) { setError('Please enter a job description.'); return }

    setLoading(true)
    setError(null)
    analysisRef.current = null
    setStep('extracting')
    setProgressMsg('Extracting resume skills and experience...')

    const formData = new FormData()
    formData.append('resume', resume)
    if (jdMode === 'file' && jdFile) {
      formData.append('jd_file', jdFile)
    } else {
      formData.append('jd_text', jdText)
    }

    try {
      const response = await fetch('http://localhost:8000/sessions/stream', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok || !response.body) {
        throw new Error(`Server error: ${response.status}`)
      }

      const reader  = response.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const payload = JSON.parse(line.slice(6))

            if (payload.type === 'progress') {
              setStep(payload.step as ProgressStep)
              setProgressMsg(payload.message)
            } else if (payload.type === 'resume_analysis') {
              // Store in ref — immediately visible to subsequent lines in this loop
              analysisRef.current = payload.data as ResumeAnalysis
            } else if (payload.type === 'session') {
              setStep('ready')
              await new Promise(r => setTimeout(r, 350))
              // Read from ref, not from stale state closure
              onSessionCreated(payload.data as SessionResponse, analysisRef.current)
              return
            } else if (payload.type === 'error') {
              throw new Error(payload.message)
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      }
    } catch (err: any) {
      setError(err.message ?? 'Failed to start interview session.')
      setStep('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <p className="subtitle">
        Upload your resume and a job description to begin a personalised mock interview.
      </p>

      <div className="upload-section">
        <div className="upload-card">
          <h3>1. Upload Resume</h3>
          <div className="input-group">
            <input
              type="file"
              accept=".pdf,.docx"
              disabled={loading}
              onChange={e => setResume(e.target.files?.[0] || null)}
            />
            {resume && <span className="file-name">{resume.name}</span>}
          </div>
        </div>

        <div className="upload-card">
          <h3>2. Job Description</h3>
          <div className="tabs">
            <button className={`tab-btn ${jdMode === 'text' ? 'active' : ''}`}
              onClick={() => setJdMode('text')} disabled={loading}>Paste Text</button>
            <button className={`tab-btn ${jdMode === 'file' ? 'active' : ''}`}
              onClick={() => setJdMode('file')} disabled={loading}>Upload File</button>
          </div>
          <div className="input-group">
            {jdMode === 'file' ? (
              <>
                <input type="file" accept=".pdf,.docx" disabled={loading}
                  onChange={e => setJdFile(e.target.files?.[0] || null)} />
                {jdFile && <span className="file-name">{jdFile.name}</span>}
              </>
            ) : (
              <textarea
                placeholder="Paste the job description here..."
                value={jdText}
                disabled={loading}
                onChange={e => setJdText(e.target.value)}
              />
            )}
          </div>
        </div>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {loading && step !== 'idle' && step !== 'error' && (
        <div className="setup-loading">
          <ProgressSteps step={step} />
          <p className="setup-loading-msg">{progressMsg}</p>
        </div>
      )}

      <button onClick={handleStart} disabled={loading}>
        {loading ? 'Analysing...' : 'Analyse & Prepare Interview →'}
      </button>
    </div>
  )
}
