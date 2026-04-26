import React, { useEffect, useState } from 'react'
import { BarChart3, Eye, FileAudio, FileText, FolderOpen, Loader2, RefreshCw, Upload } from 'lucide-react'
import { getGlobalLibraryTree, uploadGlobalKnowledgeFile } from '../services/realtimeMeetingService'
import { getMeetingTranscript, uploadAudioForMeetingReport } from '../services/meetingReportService'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export default function STTWorkspace({ onOpenMeetingReport }) {
  const [tree, setTree] = useState(null)
  const [sessions, setSessions] = useState([])
  const [knowledgeFile, setKnowledgeFile] = useState(null)
  const [audioFile, setAudioFile] = useState(null)
  const [sttModel, setSttModel] = useState('medium')
  const [language, setLanguage] = useState('ko')
  const [isUploadingKnowledge, setIsUploadingKnowledge] = useState(false)
  const [isUploadingAudio, setIsUploadingAudio] = useState(false)
  const [message, setMessage] = useState('')
  const [selectedTranscript, setSelectedTranscript] = useState(null)

  const refreshTree = async () => {
    try {
      const data = await getGlobalLibraryTree()
      setTree(data)
    } catch (error) {
      console.error(error)
      setMessage(error.message || '자료함을 불러오지 못했습니다.')
    }
  }

  const refreshSessions = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/meeting/sessions`)
      const data = await res.json()
      setSessions(data.sessions || [])
    } catch (error) {
      console.error(error)
    }
  }

  const refreshAll = async () => {
    await Promise.all([refreshTree(), refreshSessions()])
  }

  useEffect(() => {
    refreshAll()
  }, [])

  const handleKnowledgeUpload = async () => {
    if (!knowledgeFile) {
      setMessage('공통 참고 문서를 선택하세요.')
      return
    }

    setIsUploadingKnowledge(true)
    setMessage('')

    try {
      await uploadGlobalKnowledgeFile(knowledgeFile)
      setKnowledgeFile(null)
      setMessage('공통 참고 문서 업로드 완료')
      await refreshAll()
    } catch (error) {
      console.error(error)
      setMessage(error.message || '공통 참고 문서 업로드 실패')
    } finally {
      setIsUploadingKnowledge(false)
    }
  }

  const handleAudioUpload = async () => {
    if (!audioFile) {
      setMessage('회의 녹음 음성/영상 파일을 선택하세요.')
      return
    }

    setIsUploadingAudio(true)
    setSelectedTranscript(null)
    setMessage(`STT 변환 및 SLM 회의 분석 중입니다. 선택 모델: ${sttModel}`)

    try {
      const result = await uploadAudioForMeetingReport(audioFile, { sttModel, language })
      setAudioFile(null)
      setMessage(`완료. sessionId=${result.sessionId}`)
      await refreshAll()
      onOpenMeetingReport?.(result.sessionId)
    } catch (error) {
      console.error(error)
      setMessage(error.message || '음성파일 업로드/STT 변환 실패')
    } finally {
      setIsUploadingAudio(false)
    }
  }

  const handleViewTranscript = async (sessionId) => {
    try {
      const data = await getMeetingTranscript(sessionId)
      setSelectedTranscript(data)
    } catch (error) {
      console.error(error)
      setMessage(error.message || 'STT transcript 로딩 실패')
    }
  }

  return (
    <div className="h-full bg-[#f7f8fb] overflow-y-auto">
      <div className="max-w-7xl mx-auto px-8 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-black text-gray-900">STT / 자료 보관함</h1>
            <p className="text-sm text-gray-500 mt-2">
              회의 중 녹음본, 회의 후 녹음파일, 일반 업로드 문서를 분리해서 봅니다.
            </p>
          </div>
          <button
            onClick={refreshAll}
            className="rounded-2xl bg-gray-900 text-white px-4 py-2 text-sm font-bold inline-flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            새로고침
          </button>
        </div>

        {message && (
          <div className="mb-6 rounded-2xl bg-violet-50 text-violet-700 px-5 py-4 text-sm whitespace-pre-wrap">
            {message}
          </div>
        )}

        <div className="grid grid-cols-2 gap-6 mb-8">
          <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
            <div className="flex items-center gap-3 mb-4">
              <Upload className="w-5 h-5 text-violet-600" />
              <div>
                <h2 className="text-lg font-bold">공통 참고 문서 업로드</h2>
                <p className="text-sm text-gray-500">
                  평소 SLM과 실시간 회의용 SLM이 함께 참고하는 공통 문서 저장소입니다.
                </p>
              </div>
            </div>

            <input
              type="file"
              accept=".txt,.pdf,.docx,.hwp,.json,.csv"
              onChange={(e) => setKnowledgeFile(e.target.files?.[0] || null)}
              className="block w-full text-sm"
            />
            <div className="text-sm text-gray-700 mt-3">
              {knowledgeFile ? knowledgeFile.name : '선택된 파일 없음'}
            </div>
            <button
              onClick={handleKnowledgeUpload}
              disabled={isUploadingKnowledge}
              className="mt-4 rounded-2xl bg-violet-600 text-white px-4 py-2 text-sm font-bold disabled:opacity-50"
            >
              {isUploadingKnowledge ? '업로드 중...' : '업로드'}
            </button>
          </section>

          <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
            <div className="flex items-center gap-3 mb-4">
              <FileAudio className="w-5 h-5 text-blue-600" />
              <div>
                <h2 className="text-lg font-bold">회의 후 녹음/영상파일 업로드</h2>
                <p className="text-sm text-gray-500">
                  wav, mp3, m4a, webm, mp4, wma, wmv 등을 올려 STT, 회의록, Progress Bar를 생성합니다.
                </p>
              </div>
            </div>

            <input
              type="file"
              accept=".wav,.mp3,.m4a,.webm,.mp4,.aac,.ogg,.flac,.wma,.wmv"
              onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
              className="block w-full text-sm"
            />
            <div className="text-sm text-gray-700 mt-3">
              {audioFile ? audioFile.name : '선택된 음성/영상파일 없음'}
            </div>

            <div className="grid grid-cols-2 gap-3 mt-4">
              <div>
                <label className="text-xs font-bold text-gray-500">STT 모델</label>
                <select
                  value={sttModel}
                  onChange={(e) => setSttModel(e.target.value)}
                  className="w-full h-10 rounded-xl border border-gray-200 px-3 text-sm"
                >
                  <option value="base">base 빠름/낮은 정확도</option>
                  <option value="small">small</option>
                  <option value="medium">medium 추천</option>
                  <option value="large-v3">large-v3 고정확도/느림</option>
                  <option value="large-v3-turbo">large-v3-turbo</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-bold text-gray-500">언어</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full h-10 rounded-xl border border-gray-200 px-3 text-sm"
                >
                  <option value="ko">한국어</option>
                  <option value="en">영어</option>
                  <option value="auto">자동 감지</option>
                </select>
              </div>
            </div>

            <button
              onClick={handleAudioUpload}
              disabled={isUploadingAudio}
              className="mt-4 rounded-2xl bg-blue-600 text-white px-4 py-2 text-sm font-bold disabled:opacity-50 inline-flex items-center gap-2"
            >
              {isUploadingAudio && <Loader2 className="w-4 h-4 animate-spin" />}
              STT 후 회의 분석 생성
            </button>
          </section>
        </div>

        <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6 mb-8">
          <h2 className="text-xl font-black text-gray-900 mb-4">회의 세션 목록</h2>
          {sessions.length === 0 ? (
            <div className="rounded-2xl bg-gray-50 text-gray-400 px-4 py-4 text-sm">
              저장된 회의 세션이 없습니다.
            </div>
          ) : (
            <div className="space-y-3">
              {sessions.map((session) => (
                <div key={session.sessionId} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="font-bold text-gray-900">{session.title}</h3>
                      <p className="text-xs text-gray-500 mt-1">
                        sessionId={session.sessionId} · 상태={session.status} · STT={session.liveRecordingCount} · 종료기록={session.postRecordingCount}
                      </p>
                      {session.previewLine && (
                        <p className="text-sm text-gray-700 mt-2 line-clamp-2">{session.previewLine}</p>
                      )}
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button
                        onClick={() => handleViewTranscript(session.sessionId)}
                        className="px-3 py-2 rounded-xl bg-white border border-gray-200 text-sm inline-flex items-center gap-2"
                      >
                        <Eye className="w-4 h-4" />
                        STT 보기
                      </button>
                      <button
                        onClick={() => onOpenMeetingReport?.(session.sessionId)}
                        className="px-3 py-2 rounded-xl bg-blue-600 text-white text-sm inline-flex items-center gap-2"
                      >
                        <BarChart3 className="w-4 h-4" />
                        분석 보기
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {selectedTranscript && (
          <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6 mb-8">
            <h2 className="text-xl font-black text-gray-900 mb-2">STT 변환 결과</h2>
            <p className="text-sm text-gray-500 mb-4">{selectedTranscript.diarizationNote}</p>
            <div className="max-h-[420px] overflow-y-auto rounded-2xl bg-gray-50 border border-gray-200 p-4">
              {selectedTranscript.transcriptLines?.map((line, idx) => (
                <div key={idx} className="py-2 border-b border-gray-100 last:border-0">
                  <span className="text-xs font-bold text-violet-600">[{line.start}~{line.end}]</span>
                  <span className="ml-2 text-xs font-semibold text-gray-500">{line.speaker}</span>
                  <span className="ml-2 text-sm text-gray-800">{line.text}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="grid grid-cols-3 gap-6">
          <Panel title="회의 중 녹음본" icon={<FileAudio className="w-5 h-5 text-violet-600" />} items={tree?.realtimeMeetings || []} empty="표시할 회의 중 녹음본이 없습니다." />
          <Panel title="회의 후 녹음본" icon={<FileText className="w-5 h-5 text-blue-600" />} items={tree?.postMeetingRecordings || []} empty="표시할 회의 후 녹음본이 없습니다." />
          <Panel title="업로드 문서" icon={<FolderOpen className="w-5 h-5 text-emerald-600" />} items={tree?.uploadedKnowledge || []} empty="표시할 업로드 문서가 없습니다." />
        </div>
      </div>
    </div>
  )
}

function Panel({ title, icon, items, empty }) {
  return (
    <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h2 className="text-lg font-bold text-gray-900">{title}</h2>
      </div>
      <List items={items} empty={empty} />
    </section>
  )
}

function List({ items, empty }) {
  if (!items || items.length === 0) {
    return (
      <div className="rounded-2xl bg-gray-50 text-gray-400 px-4 py-4 text-sm">
        {empty}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.id || item.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
          <h3 className="text-sm font-bold text-gray-900">{item.title || item.name}</h3>
          <p className="text-xs text-gray-500 mt-1">{item.kindLabel || item.kind || item.createdAt || item.created_at || ''}</p>
          {(item.previewLine || item.preview_line) && (
            <p className="text-sm text-gray-700 mt-2 line-clamp-3">{item.previewLine || item.preview_line}</p>
          )}
        </div>
      ))}
    </div>
  )
}
