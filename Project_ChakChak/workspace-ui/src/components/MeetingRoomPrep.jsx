import React, { useState } from 'react'
import { FileText, Loader2, Mic, Upload } from 'lucide-react'
import { createMeetingSession } from '../services/realtimeMeetingService'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export default function MeetingRoomPrep({ onStartMeeting }) {
  const [meetingTitle, setMeetingTitle] = useState('')
  const [meetingType, setMeetingType] = useState('general')
  const [meetingTime, setMeetingTime] = useState('')
  const [keywords, setKeywords] = useState('')
  const [planText, setPlanText] = useState('')
  const [planFile, setPlanFile] = useState(null)
  const [isStarting, setIsStarting] = useState(false)
  const [errorText, setErrorText] = useState('')

  const extractDocumentText = async (file) => {
    if (!file) return ''

    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/api/document/extract/`, {
      method: 'POST',
      body: formData,
    })

    const data = await response.json().catch(() => null)

    if (!response.ok) {
      throw new Error(data?.detail || data?.message || '문서 추출 실패')
    }

    return data?.text || data?.content || data?.extracted_text || data?.result || ''
  }

  const handleStartMeeting = async () => {
    if (isStarting) return

    setIsStarting(true)
    setErrorText('')

    try {
      const extractedText = await extractDocumentText(planFile)

      const finalPlanText = [planText.trim(), extractedText.trim()]
        .filter(Boolean)
        .join('\n\n')

      const payload = {
        title: meetingTitle.trim() || '새 회의',
        meetingTitle: meetingTitle.trim() || '새 회의',
        meeting_type: meetingType,
        meetingType,
        meeting_time: meetingTime,
        meetingTime,
        keywords,
        plan_text: finalPlanText,
        planText: finalPlanText,
        realtime_recording_enabled: true,
        realtimeRecordingEnabled: true,
      }

      const session = await createMeetingSession(payload)

      const sessionId =
        session?.sessionId ||
        session?.session_id ||
        session?.id ||
        session?.data?.sessionId ||
        session?.data?.id

      if (!sessionId) {
        throw new Error(`sessionId를 받지 못했습니다: ${JSON.stringify(session)}`)
      }

      const merged = {
        ...payload,
        ...session,
        sessionId,
        id: sessionId,
        planFileName: planFile?.name || '',
      }

      alert(`SESSION CREATED: ${sessionId}`)
      console.log('SESSION CREATED:', merged)

      onStartMeeting?.(merged)
    } catch (error) {
      console.error(error)
      setErrorText(error.message || '회의 시작 실패')
    } finally {
      setIsStarting(false)
    }
  }

  return (
    <div className="flex-1 h-full overflow-y-auto bg-[#f7f8fb]">
      <div className="max-w-5xl mx-auto px-8 py-10">
        <h1 className="text-3xl font-black text-gray-900">실시간 회의 준비</h1>
        <p className="text-sm text-gray-500 mt-2">
          회의 정보를 입력하고 회의 시작을 누르면 sessionId가 생성됩니다.
        </p>

        {errorText && (
          <div className="mt-6 rounded-2xl bg-red-50 text-red-600 px-5 py-4 text-sm">
            {errorText}
          </div>
        )}

        <div className="mt-8 grid grid-cols-[1fr_360px] gap-6">
          <section className="rounded-3xl bg-white border border-gray-200 shadow-sm p-6 space-y-5">
            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">회의 제목</label>
              <input
                value={meetingTitle}
                onChange={(e) => setMeetingTitle(e.target.value)}
                placeholder="예: 캡스톤 중간 점검 회의"
                className="w-full h-12 rounded-2xl border border-gray-200 px-4 outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">회의 종류</label>
                <select
                  value={meetingType}
                  onChange={(e) => setMeetingType(e.target.value)}
                  className="w-full h-12 rounded-2xl border border-gray-200 px-4 outline-none"
                >
                  <option value="general">일반 회의</option>
                  <option value="capstone">캡스톤 회의</option>
                  <option value="research">연구 회의</option>
                  <option value="paper">논문/리뷰 회의</option>
                  <option value="planning">기획 회의</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">회의 시간</label>
                <input
                  value={meetingTime}
                  onChange={(e) => setMeetingTime(e.target.value)}
                  placeholder="예: 2026-04-25 15:00"
                  className="w-full h-12 rounded-2xl border border-gray-200 px-4 outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">키워드</label>
              <input
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="예: STT, 회의 분석, Progress Bar, RAG"
                className="w-full h-12 rounded-2xl border border-gray-200 px-4 outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">회의 계획서 직접 입력</label>
              <textarea
                value={planText}
                onChange={(e) => setPlanText(e.target.value)}
                placeholder="회의 목표, 안건, 논의할 내용 등을 입력하세요."
                className="w-full min-h-[220px] rounded-2xl border border-gray-200 p-4 outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>
          </section>

          <aside className="rounded-3xl bg-white border border-gray-200 shadow-sm p-6 h-fit">
            <div className="flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-blue-600" />
              <h2 className="text-lg font-bold text-gray-900">회의 계획서 업로드</h2>
            </div>

            <p className="text-sm text-gray-500 leading-6">
              PDF, TXT, DOCX, HWP 등 회의 관련 문서를 올리면 텍스트를 추출해 세션에 함께 저장합니다.
            </p>

            <div className="mt-5 rounded-2xl bg-gray-50 border border-gray-100 p-4">
              <input
                type="file"
                accept=".txt,.pdf,.docx,.hwp,.json"
                onChange={(e) => setPlanFile(e.target.files?.[0] || null)}
                className="block w-full text-sm"
              />
              <div className="text-sm text-gray-700 mt-3">
                {planFile ? planFile.name : '선택된 파일 없음'}
              </div>
            </div>

            <button
              onClick={handleStartMeeting}
              disabled={isStarting}
              className="mt-6 w-full h-12 rounded-2xl bg-blue-600 text-white font-bold inline-flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {isStarting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mic className="w-4 h-4" />}
              {isStarting ? '회의 세션 생성 중...' : '회의 시작'}
            </button>

            <div className="mt-5 text-sm text-gray-500 flex items-center gap-2">
              <Upload className="w-4 h-4" />
              회의 중에도 추가 자료 업로드가 가능합니다.
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}
