const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

async function parseJsonSafe(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function request(url, options = {}, fallback = '요청 실패') {
  const res = await fetch(url, options)
  const data = await parseJsonSafe(res)
  if (!res.ok) throw new Error(data?.detail || data?.message || fallback)
  return data
}

export async function uploadAudioForMeetingReport(file, options = {}) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('stt_model', options.sttModel || 'medium')
  formData.append('language', options.language || 'ko')

  return request(`${API_BASE_URL}/meeting-report/upload-audio`, {
    method: 'POST',
    body: formData,
  }, '음성파일 업로드/STT 변환 실패')
}

export async function getMeetingReport(sessionId) {
  return request(`${API_BASE_URL}/meeting-report/${sessionId}`)
}

export async function regenerateMeetingReport(sessionId) {
  return request(`${API_BASE_URL}/meeting-report/${sessionId}/regenerate`, {
    method: 'POST',
  }, '회의 분석 재생성 실패')
}

export async function getMeetingTranscript(sessionId) {
  return request(`${API_BASE_URL}/meeting-report/${sessionId}/transcript`)
}

export async function logMeetingAIEvent({
  sessionId,
  question,
  answer,
  askedAtSec,
  beforeContext = '',
  afterContext = '',
}) {
  if (!sessionId || !question) return null

  return request(`${API_BASE_URL}/meeting-report/${sessionId}/ai-event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      answer,
      askedAtSec,
      beforeContext,
      afterContext,
    }),
  }, 'AI 사용 기록 저장 실패')
}
