import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Bot,
  FileUp,
  Loader2,
  Mic,
  MicOff,
  Pause,
  Play,
  RefreshCw,
  Send,
  Square,
  Upload,
  Wifi,
  WifiOff,
} from 'lucide-react'
import {
  getMeetingDetail,
  getMeetingFeedback,
  getMeetingLibraryTree,
  getMeetingMidSummary,
  getRealtimeTopic,
  stopRealtimeMeeting,
  uploadKnowledgeFile,
  uploadMeetingPlanFile,
  uploadRealtimeChunk,
} from '../services/realtimeMeetingService'
import { chatWithAI } from '../services/aiService'
import { logMeetingAIEvent, regenerateMeetingReport } from '../services/meetingReportService'

const CHUNK_MS = 15000

function nowTime() {
  return new Date().toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatSec(sec = 0) {
  sec = Math.max(0, Math.floor(sec))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function MeetingLiveView({
  planData,
  useWebSearch = false,
  setUseWebSearch,
  onOpenMeetingReport,
}) {
  const sessionId = planData?.sessionId || planData?.id
  const [meetingDetail, setMeetingDetail] = useState(null)
  const [libraryTree, setLibraryTree] = useState(null)

  const [messages, setMessages] = useState([
    {
      sender: 'system',
      text: '회의가 시작되었습니다. 녹음을 시작하고 AI에게 질문할 수 있습니다.',
      time: nowTime(),
    },
  ])
  const [inputValue, setInputValue] = useState('')
  const [isChatLoading, setIsChatLoading] = useState(false)

  const [liveTranscriptItems, setLiveTranscriptItems] = useState([])
  const [currentTopic, setCurrentTopic] = useState('아직 분석된 주제가 없습니다.')
  const [topicHistory, setTopicHistory] = useState([])

  const [isRecording, setIsRecording] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [recordingError, setRecordingError] = useState('')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  const [meetingPlanFile, setMeetingPlanFile] = useState(null)
  const [knowledgeFile, setKnowledgeFile] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('')

  const [isSummaryLoading, setIsSummaryLoading] = useState(false)
  const [isFeedbackLoading, setIsFeedbackLoading] = useState(false)
  const [isStopping, setIsStopping] = useState(false)

  const mediaRecorderRef = useRef(null)
  const streamRef = useRef(null)
  const startedAtRef = useRef(null)
  const chunkOffsetRef = useRef(0)
  const messagesEndRef = useRef(null)
  const transcriptEndRef = useRef(null)
  const topicTimerRef = useRef(null)
  const elapsedTimerRef = useRef(null)
  const isRecordingRef = useRef(false)
  const isPausedRef = useRef(false)

  const meetingTitle = planData?.title || planData?.meetingTitle || meetingDetail?.title || '실시간 회의'
  const meetingType = planData?.meetingType || planData?.meeting_type || meetingDetail?.meetingType || 'general'
  const meetingTime = planData?.meetingTime || planData?.meeting_time || meetingDetail?.meetingTime || ''
  const keywords = planData?.keywords || meetingDetail?.keywords || ''

  const transcriptText = useMemo(() => {
    return liveTranscriptItems
      .map((item) => item.previewLine || item.transcript || item.text || '')
      .filter(Boolean)
      .join('\n')
  }, [liveTranscriptItems])

  const appendMessage = (sender, text) => {
    setMessages((prev) => [
      ...prev,
      { sender, text, time: nowTime() },
    ])
  }

  const scrollChatBottom = () => {
    setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }

  const scrollTranscriptBottom = () => {
    setTimeout(() => transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }

  useEffect(() => {
    scrollChatBottom()
  }, [messages])

  useEffect(() => {
    scrollTranscriptBottom()
  }, [liveTranscriptItems])

  const refreshMeeting = async () => {
    if (!sessionId) return

    try {
      const detail = await getMeetingDetail(sessionId)
      setMeetingDetail(detail)
    } catch (e) {
      console.warn(e)
    }

    try {
      const tree = await getMeetingLibraryTree(sessionId)
      setLibraryTree(tree)

      const candidates = [
        ...(tree?.liveRecordings || []),
        ...(tree?.live_recordings || []),
        ...(tree?.realtimeMeetings || []),
        ...(tree?.postMeetingRecordings || []),
      ]

      const normalized = candidates
        .map((item, idx) => ({
          id: item.id || `${idx}-${item.createdAt || Date.now()}`,
          previewLine:
            item.previewLine ||
            item.preview_line ||
            item.textContent ||
            item.text_content ||
            item.transcript ||
            item.text ||
            item.name ||
            '',
          createdAt: item.createdAt || item.created_at || '',
          kind: item.kind || '',
        }))
        .filter((item) => item.previewLine)

      if (normalized.length > 0) {
        setLiveTranscriptItems(normalized)
      }
    } catch (e) {
      console.warn(e)
    }
  }

  const pollRealtimeTopic = async () => {
    try {
      const result = await getRealtimeTopic()
      const topic = result?.topic || result?.currentTopic || result?.summary || ''
      if (!topic) return

      setCurrentTopic(topic)
      setTopicHistory((prev) => {
        const last = prev[prev.length - 1]
        if (last?.topic === topic) return prev
        return [
          ...prev,
          {
            id: Date.now().toString(),
            topic,
            time: formatSec(elapsedSeconds),
          },
        ].slice(-20)
      })
    } catch (e) {
      console.warn('실시간 주제 분석 오류:', e)
    }
  }

  useEffect(() => {
    refreshMeeting()
  }, [sessionId])

  useEffect(() => {
    if (!sessionId) return

    topicTimerRef.current = setInterval(() => {
      pollRealtimeTopic()
      refreshMeeting()
    }, 30000)

    
  console.log('MeetingLiveView planData:', planData)
  console.log('MeetingLiveView sessionId:', sessionId)

return () => {
      if (topicTimerRef.current) clearInterval(topicTimerRef.current)
    }
  }, [sessionId, elapsedSeconds])

  useEffect(() => {
    if (!isRecording || isPaused) return

    elapsedTimerRef.current = setInterval(() => {
      if (!startedAtRef.current) return
      setElapsedSeconds(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 1000)

    return () => {
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current)
    }
  }, [isRecording, isPaused])

  const uploadAudioBlob = async (blob, offset) => {
    if (!blob || blob.size < 4096) return

    try {
      const result = await uploadRealtimeChunk(sessionId, blob, offset)

      console.log('REALTIME CHUNK RESULT:', result)

      if (result?.skipped) {
        console.warn('STT chunk skipped:', result)
        return
      }

      const transcript =
        result?.transcript ||
        result?.item?.textContent ||
        result?.item?.text_content ||
        result?.item?.previewLine ||
        result?.item?.preview_line ||
        result?.previewLine ||
        ''

      console.log('REALTIME TRANSCRIPT:', transcript)

      if (transcript && transcript.trim()) {
        setLiveTranscriptItems((prev) => [
          ...prev,
          {
            id: `${Date.now()}-${Math.random()}`,
            previewLine: transcript,
            transcript,
            createdAt: new Date().toISOString(),
            kind: 'realtime_audio_chunk_transcript',
          },
        ])
      }

      await refreshMeeting()
    } catch (e) {
      console.error(e)
      setRecordingError(e.message || '실시간 녹음 chunk 업로드에 실패했습니다.')
    }
  }

  const startRecorderCycle = (stream) => {
    if (!streamRef.current || !isRecordingRef.current || isPausedRef.current) return

    const mimeCandidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
    const selectedMime = mimeCandidates.find((m) => window.MediaRecorder?.isTypeSupported?.(m)) || ''

    const recorder = selectedMime
      ? new MediaRecorder(stream, { mimeType: selectedMime })
      : new MediaRecorder(stream)

    const chunks = []
    const offset = chunkOffsetRef.current

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data)
    }

    recorder.onstop = async () => {
      if (chunks.length > 0) {
        const blob = new Blob(chunks, { type: selectedMime || 'audio/webm' })
        await uploadAudioBlob(blob, offset)
        chunkOffsetRef.current += CHUNK_MS / 1000
      }

      if (isRecordingRef.current && !isPausedRef.current) {
        startRecorderCycle(stream)
      }
    }

    mediaRecorderRef.current = recorder
    recorder.start()

    setTimeout(() => {
      if (recorder.state === 'recording') {
        recorder.stop()
      }
    }, CHUNK_MS)
  }

  const startRecording = async () => {
    if (!sessionId) {
      setRecordingError('sessionId가 없어 녹음을 시작할 수 없습니다.')
      return
    }

    try {
      setRecordingError('')
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      startedAtRef.current = Date.now()
      chunkOffsetRef.current = 0

      isRecordingRef.current = true
      isPausedRef.current = false

      setIsRecording(true)
      setIsPaused(false)

      startRecorderCycle(stream)

      appendMessage('system', '실시간 녹음이 시작되었습니다.')
    } catch (e) {
      console.error(e)
      setRecordingError(e.message || '마이크 접근 또는 녹음 시작 실패')
    }
  }

  const pauseRecording = () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state !== 'recording') return

    recorder.pause()
    isPausedRef.current = true
    setIsPaused(true)
    appendMessage('system', '회의 녹음이 일시정지되었습니다.')
  }

  const resumeRecording = () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state !== 'paused') return

    recorder.resume()
    isPausedRef.current = false
    setIsPaused(false)
    startRecorderCycle(streamRef.current)
    appendMessage('system', '회의 녹음이 재개되었습니다.')
  }

  const stopRecordingOnly = () => {
    try {
      const recorder = mediaRecorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        if (recorder.state === 'recording') recorder.requestData()
        recorder.stop()
      }
      streamRef.current?.getTracks?.().forEach((track) => track.stop())
    } catch (e) {
      console.warn(e)
    } finally {
      isRecordingRef.current = false
      isPausedRef.current = false
      setIsRecording(false)
      setIsPaused(false)
      appendMessage('system', '실시간 녹음이 중지되었습니다.')
    }
  }

  const askPreset = async (prompt) => {
    setInputValue(prompt)
    setTimeout(() => {
      const event = new Event('submit', { bubbles: true, cancelable: true })
      const form = document.getElementById('live-ai-chat-form')
      form?.dispatchEvent(event)
    }, 50)
  }

  const handleAskAI = async () => {
    const text = inputValue.trim()
    if (!text || isChatLoading) return

    const askedAtSec = elapsedSeconds
    setInputValue('')
    appendMessage('user', text)
    setIsChatLoading(true)

    try {
      const answer = await chatWithAI(text, transcriptText, 'realtime', {
        sessionId,
        meetingType,
        meetingTitle,
        meetingTime,
        keywords,
        purpose: 'live_meeting_chat',
        useWeb: useWebSearch,
      })

      appendMessage('ai', answer)

      try {
        await logMeetingAIEvent({
          sessionId,
          question: text,
          answer,
          askedAtSec,
          beforeContext: transcriptText,
          afterContext: '',
        })
      } catch (e) {
        console.warn(e)
      }
    } catch (e) {
      appendMessage('ai', `AI 응답 오류: ${e.message}`)
    } finally {
      setIsChatLoading(false)
    }
  }

  const handleMidSummary = async () => {
    if (!sessionId || isSummaryLoading) return

    setIsSummaryLoading(true)
    try {
      const result = await getMeetingMidSummary(sessionId)
      appendMessage('ai', `[중간 요약]\n${result?.summary || result?.message || JSON.stringify(result, null, 2)}`)
    } catch (e) {
      appendMessage('ai', `중간 요약 실패: ${e.message}`)
    } finally {
      setIsSummaryLoading(false)
    }
  }

  const handleFeedback = async () => {
    if (!sessionId || isFeedbackLoading) return

    setIsFeedbackLoading(true)
    try {
      const result = await getMeetingFeedback(sessionId)
      appendMessage('ai', `[회의 피드백]\n${result?.feedback || result?.message || JSON.stringify(result, null, 2)}`)
    } catch (e) {
      appendMessage('ai', `회의 피드백 실패: ${e.message}`)
    } finally {
      setIsFeedbackLoading(false)
    }
  }

  const handleUploadPlan = async () => {
    if (!sessionId || !meetingPlanFile) return

    setUploadStatus('회의 계획서 업로드 중...')
    try {
      await uploadMeetingPlanFile(sessionId, meetingPlanFile)
      setMeetingPlanFile(null)
      setUploadStatus('회의 계획서 업로드 완료')
      await refreshMeeting()
    } catch (e) {
      setUploadStatus(`회의 계획서 업로드 실패: ${e.message}`)
    }
  }

  const handleUploadKnowledge = async () => {
    if (!sessionId || !knowledgeFile) return

    setUploadStatus('회의 참고자료 업로드 중...')
    try {
      await uploadKnowledgeFile(sessionId, knowledgeFile)
      setKnowledgeFile(null)
      setUploadStatus('회의 참고자료 업로드 완료')
      await refreshMeeting()
    } catch (e) {
      setUploadStatus(`회의 참고자료 업로드 실패: ${e.message}`)
    }
  }

  const handleStopMeeting = async () => {
    if (!sessionId || isStopping) return

    setIsStopping(true)
    appendMessage('system', '회의를 종료하고 전체 STT 기반 회의 분석을 생성하는 중입니다...')

    try {
      if (isRecording) {
        stopRecordingOnly()
        await new Promise((resolve) => setTimeout(resolve, 1200))
      }

      const result = await stopRealtimeMeeting(sessionId)

      if (result?.finalSummary) {
        appendMessage('ai', `[최종 회의록 초안]\n${result.finalSummary}`)
      }

      appendMessage('system', '전체 STT를 SLM으로 재분석합니다.')

      try {
        await regenerateMeetingReport(sessionId)
      } catch (e) {
        appendMessage('system', `회의 분석 재생성 경고: ${e.message}`)
      }

      appendMessage('system', '회의 분석이 완료되었습니다. 분석 화면으로 이동합니다.')
      onOpenMeetingReport?.(sessionId)
    } catch (e) {
      appendMessage('system', `회의 종료 실패: ${e.message}`)
    } finally {
      setIsStopping(false)
    }
  }

  return (
    <div className="flex-1 h-full bg-[#111322] text-gray-900 overflow-hidden flex flex-col">
      <header className="h-20 px-8 flex items-center justify-between shrink-0 text-white">
        <div>
          <div className="text-xs tracking-[0.3em] text-pink-400 font-bold">LIVE CONTEXT</div>
          <h1 className="text-2xl font-black mt-1">"{currentTopic}"</h1>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setUseWebSearch?.(!useWebSearch)}
            className={`h-10 px-4 rounded-2xl font-bold inline-flex items-center gap-2 ${
              useWebSearch ? 'bg-emerald-500 text-white' : 'bg-gray-700 text-gray-200'
            }`}
          >
            {useWebSearch ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4" />}
            웹검색 {useWebSearch ? 'ON' : 'OFF'}
          </button>

          <div className="h-10 px-4 rounded-2xl bg-white/10 flex items-center text-sm">
            {formatSec(elapsedSeconds)}
          </div>

          {!isRecording ? (
            <button onClick={startRecording} className="h-10 px-4 rounded-2xl bg-blue-600 text-white font-bold inline-flex items-center gap-2">
              <Mic className="w-4 h-4" /> 녹음 시작
            </button>
          ) : isPaused ? (
            <button onClick={resumeRecording} className="h-10 px-4 rounded-2xl bg-emerald-600 text-white font-bold inline-flex items-center gap-2">
              <Play className="w-4 h-4" /> 재개
            </button>
          ) : (
            <button onClick={pauseRecording} className="h-10 px-4 rounded-2xl bg-amber-500 text-white font-bold inline-flex items-center gap-2">
              <Pause className="w-4 h-4" /> 일시정지
            </button>
          )}

          {isRecording && (
            <button onClick={stopRecordingOnly} className="h-10 px-4 rounded-2xl bg-red-600 text-white font-bold inline-flex items-center gap-2">
              <MicOff className="w-4 h-4" /> 녹음 중지
            </button>
          )}

          <button
            onClick={handleStopMeeting}
            disabled={isStopping}
            className="h-10 px-4 rounded-2xl bg-white text-gray-900 font-black inline-flex items-center gap-2 disabled:opacity-50"
          >
            {isStopping ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
            회의 종료
          </button>
        </div>
      </header>

      {recordingError && (
        <div className="mx-8 mb-4 rounded-2xl bg-red-50 text-red-600 px-5 py-3 text-sm">
          {recordingError}
        </div>
      )}

      <main className="flex-1 min-h-0 bg-white rounded-t-[2rem] mx-6 overflow-hidden grid grid-cols-[minmax(360px,0.75fr)_minmax(0,1.25fr)_360px]">
        <section className="min-h-0 border-r border-gray-200 flex flex-col">
          <div className="h-16 px-5 flex items-center gap-2 border-b border-gray-200 shrink-0">
            <Bot className="w-5 h-5 text-blue-600" />
            <div className="font-black">AI 실시간 어시스턴트</div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[88%] rounded-3xl px-5 py-4 text-sm leading-6 whitespace-pre-wrap ${
                  msg.sender === 'user'
                    ? 'bg-emerald-400 text-white'
                    : msg.sender === 'ai'
                      ? 'bg-violet-50 border border-violet-100 text-gray-800'
                      : 'bg-[#202033] text-white'
                }`}>
                  {msg.text}
                </div>
              </div>
            ))}
            {isChatLoading && (
              <div className="rounded-3xl bg-violet-50 text-violet-700 px-5 py-4 text-sm inline-flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> AI 응답 생성 중...
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form
            id="live-ai-chat-form"
            onSubmit={(e) => {
              e.preventDefault()
              handleAskAI()
            }}
            className="p-4 border-t border-gray-200 flex gap-2 shrink-0"
          >
            <input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="AI 어시스턴트에게 질문하세요"
              className="flex-1 h-12 rounded-2xl border border-gray-200 px-4 outline-none"
            />
            <button disabled={isChatLoading || !inputValue.trim()} className="h-12 w-12 rounded-2xl bg-violet-600 text-white flex items-center justify-center disabled:opacity-50">
              <Send className="w-5 h-5" />
            </button>
          </form>
        </section>

        <section className="min-h-0 flex flex-col overflow-hidden">
          <div className="h-16 px-6 flex items-center justify-between border-b border-gray-200 shrink-0">
            <button onClick={handleMidSummary} disabled={isSummaryLoading} className="text-blue-600 font-bold underline">
              {isSummaryLoading ? '요약 생성 중...' : '현재까지 진행 내용 요약하기'}
            </button>
            <button onClick={handleFeedback} disabled={isFeedbackLoading} className="rounded-2xl bg-gray-100 px-4 py-2 text-sm font-bold">
              {isFeedbackLoading ? '피드백 생성 중...' : '회의 피드백'}
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-6">
            <div className="rounded-3xl border border-dashed border-gray-300 p-10 text-center text-gray-500">
              <Bot className="w-10 h-10 mx-auto mb-4 text-violet-400" />
              <div className="font-bold text-gray-800">착착이에게 즉시 요청하기</div>
              <div className="text-sm mt-2">
                좌측 채팅창이나 상단 요약 버튼을 사용하세요.
              </div>

              <div className="mt-6 grid gap-3 max-w-md mx-auto">
                <button onClick={handleMidSummary} className="rounded-2xl bg-white border border-gray-200 px-4 py-3 text-sm text-left">
                  📋 현재까지 진행 내용 요약이 필요해요
                </button>
                <button onClick={handleFeedback} className="rounded-2xl bg-white border border-gray-200 px-4 py-3 text-sm text-left">
                  💡 회의가 정체됐어요. 제안해 주세요.
                </button>
                <button onClick={() => askPreset('현재 회의 내용을 바탕으로 다음 스텝을 구체적으로 추천해줘')} className="rounded-2xl bg-white border border-gray-200 px-4 py-3 text-sm text-left">
                  🚀 다음 스텝 추천이 필요해요
                </button>
              </div>
            </div>

            <div className="mt-6 rounded-3xl border border-gray-200 p-5">
              <div className="font-bold mb-3">회의 중 자료 업로드</div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <input type="file" onChange={(e) => setMeetingPlanFile(e.target.files?.[0] || null)} className="text-xs" />
                  <button onClick={handleUploadPlan} disabled={!meetingPlanFile} className="mt-2 rounded-xl bg-violet-600 text-white px-3 py-2 text-xs disabled:opacity-50 inline-flex gap-1 items-center">
                    <FileUp className="w-3 h-3" /> 계획서 업로드
                  </button>
                </div>
                <div>
                  <input type="file" onChange={(e) => setKnowledgeFile(e.target.files?.[0] || null)} className="text-xs" />
                  <button onClick={handleUploadKnowledge} disabled={!knowledgeFile} className="mt-2 rounded-xl bg-blue-600 text-white px-3 py-2 text-xs disabled:opacity-50 inline-flex gap-1 items-center">
                    <Upload className="w-3 h-3" /> 자료 업로드
                  </button>
                </div>
              </div>
              {uploadStatus && <div className="mt-3 text-xs text-violet-600">{uploadStatus}</div>}
            </div>
          </div>
        </section>

        <aside className="min-h-0 border-l border-gray-200 flex flex-col">
          <div className="h-16 px-5 flex items-center justify-between border-b border-gray-200 shrink-0">
            <div className="font-black">회의 중 녹음본 / STT</div>
            <button onClick={refreshMeeting} className="text-xs rounded-lg border px-2 py-1">
              <RefreshCw className="w-3 h-3 inline" /> 갱신
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
            {liveTranscriptItems.length === 0 ? (
              <div className="h-full flex items-center justify-center text-center text-sm text-gray-400">
                아직 STT가 없습니다.
              </div>
            ) : (
              liveTranscriptItems.map((item) => (
                <div key={item.id} className="rounded-2xl bg-gray-50 border border-gray-200 p-3">
                  <div className="text-xs text-violet-600 font-bold">실시간 STT 기록</div>
                  <div className="text-sm mt-1 whitespace-pre-wrap">{item.previewLine}</div>
                </div>
              ))
            )}
            <div ref={transcriptEndRef} />
          </div>
        </aside>
      </main>
    </div>
  )
}
