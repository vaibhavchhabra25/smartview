import { useState, useRef, useCallback } from 'react'

export type VoiceState = 'idle' | 'recording' | 'transcribing' | 'error'

interface Options {
  onTranscribed: (text: string) => void
  onError: (message: string) => void
}

export function useVoiceInput({ onTranscribed, onError }: Options) {
  const [state, setState]     = useState<VoiceState>('idle')
  const [seconds, setSeconds] = useState(0)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef   = useRef<Blob[]>([])
  const timerRef    = useRef<ReturnType<typeof setInterval>>()

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

      const mimeType =
        MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' :
        MediaRecorder.isTypeSupported('audio/webm')             ? 'audio/webm'             :
                                                                  'audio/ogg;codecs=opus'

      const recorder  = new MediaRecorder(stream, { mimeType })
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        setState('transcribing')

        const blob = new Blob(chunksRef.current, { type: mimeType })
        const ext  = mimeType.includes('webm') ? 'webm' : 'ogg'
        const form = new FormData()
        form.append('audio', blob, `answer.${ext}`)

        try {
          const res = await fetch('http://localhost:8000/transcribe', {
            method: 'POST',
            body: form,
          })
          if (!res.ok) {
            const err = await res.json().catch(() => ({}))
            throw new Error(err.detail ?? `Server error ${res.status}`)
          }
          const { text } = await res.json()
          onTranscribed(text)
        } catch (err: any) {
          onError(err.message ?? 'Transcription failed.')
        } finally {
          setState('idle')
        }
      }

      recorder.start(200)
      recorderRef.current = recorder
      setSeconds(0)
      setState('recording')
      timerRef.current = setInterval(() => setSeconds(s => s + 1), 1000)

    } catch (err: any) {
      const msg =
        err.name === 'NotAllowedError'
          ? 'Microphone access denied. Please allow microphone access in your browser.'
          : err.message ?? 'Could not start recording.'
      onError(msg)
    }
  }, [onTranscribed, onError])

  const stop = useCallback(() => {
    clearInterval(timerRef.current)
    recorderRef.current?.stop()
  }, [])

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

  return { state, seconds, formattedTime: fmt(seconds), start, stop }
}
