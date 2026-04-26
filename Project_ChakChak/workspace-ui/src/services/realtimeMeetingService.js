const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

async function parseJsonSafe(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function request(url, options = {}, fallbackMessage = '요청에 실패했습니다.') {
  const response = await fetch(url, options)
  const data = await parseJsonSafe(response)

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || fallbackMessage)
  }

  return data
}

export async function createMeetingSession(payload) {
  return request(`${BASE_URL}/meeting/session/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, '회의 세션 생성에 실패했습니다.')
}

export async function uploadMeetingPlanFile(sessionId, file) {
  const formData = new FormData()
  formData.append('file', file)

  return request(`${BASE_URL}/meeting/session/${sessionId}/plan`, {
    method: 'POST',
    body: formData,
  }, '회의 계획서 업로드에 실패했습니다.')
}

export async function uploadKnowledgeFile(sessionId, file) {
  const formData = new FormData()
  formData.append('file', file)

  return request(`${BASE_URL}/meeting/session/${sessionId}/knowledge`, {
    method: 'POST',
    body: formData,
  }, '회의 자료 업로드에 실패했습니다.')
}

export async function uploadGlobalKnowledgeFile(file) {
  const formData = new FormData()
  formData.append('file', file)

  return request(`${BASE_URL}/library/global/upload`, {
    method: 'POST',
    body: formData,
  }, '공통 문서 업로드에 실패했습니다.')
}

export async function uploadRealtimeChunk(sessionId, blob, offsetSec) {
  const formData = new FormData()
  formData.append('file', blob, `chunk_${Date.now()}.webm`)
  formData.append('offset_sec', String(offsetSec || 0))

  return request(`${BASE_URL}/meeting/session/${sessionId}/realtime-chunk`, {
    method: 'POST',
    body: formData,
  }, '실시간 녹음 chunk 업로드에 실패했습니다.')
}

export async function stopRealtimeMeeting(sessionId) {
  return request(`${BASE_URL}/meeting/session/${sessionId}/stop`, {
    method: 'POST',
  }, '회의 종료 처리에 실패했습니다.')
}

export async function getMeetingDetail(sessionId) {
  return request(`${BASE_URL}/meeting/session/${sessionId}`, {
    method: 'GET',
  }, '회의 상세 정보를 불러오지 못했습니다.')
}

export async function getMeetingLibraryTree(sessionId) {
  return request(`${BASE_URL}/meeting/session/${sessionId}/library-tree`, {
    method: 'GET',
  }, '회의 자료함을 불러오지 못했습니다.')
}

export async function getGlobalLibraryTree() {
  return request(`${BASE_URL}/library/global/tree`, {
    method: 'GET',
  }, '자료함을 불러오지 못했습니다.')
}

export async function getMeetingMidSummary(sessionId) {
  return request(`${BASE_URL}/meeting/session/${sessionId}/mid-summary`, {
    method: 'POST',
  }, '회의 중간 요약 생성에 실패했습니다.')
}

export async function getMeetingFeedback(sessionId) {
  return request(`${BASE_URL}/meeting/session/${sessionId}/feedback`, {
    method: 'POST',
  }, '회의 피드백 생성에 실패했습니다.')
}

export async function getRealtimeTopic() {
  return request(`${BASE_URL}/api/realtime-topic`, {
    method: 'GET',
  }, '실시간 주제 분석에 실패했습니다.')
}
