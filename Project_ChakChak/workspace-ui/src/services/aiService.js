const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

async function parseJsonSafe(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

export async function chatWithAI(userText, meetingText = '', mode = 'general', options = {}) {
  const response = await fetch(`${API_BASE_URL}/ai/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: userText,
      meetingText,
      mode,
      useWeb: Boolean(options.useWeb),
      sessionId: options.sessionId || null,
      meetingType: options.meetingType || '',
      meetingTitle: options.meetingTitle || '',
      keywords: options.keywords || '',
      purpose: options.purpose || 'chat',
    }),
  })

  const data = await parseJsonSafe(response)

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || 'AI 호출 실패')
  }

  return data?.answer || data?.message || data?.response || ''
}

export async function summarizeMeeting(sessionId) {
  const response = await fetch(`${API_BASE_URL}/meeting/session/${sessionId}/mid-summary`, {
    method: 'POST',
  })

  const data = await parseJsonSafe(response)

  if (!response.ok) {
    throw new Error(data?.detail || '요약 실패')
  }

  return data
}

export async function fetchQueryTestResult(sessionId) {
  try {
    const response = await fetch(`${API_BASE_URL}/query-test/${sessionId}`)
    if (!response.ok) {
      return { sessionId, summary: '', transcript: '', silenceEvents: [], nodes: [] }
    }
    return await response.json()
  } catch {
    return { sessionId, summary: '', transcript: '', silenceEvents: [], nodes: [] }
  }
}

export function buildTextFromAIInput(input) {
  if (!input) return ''
  if (typeof input === 'string') return input
  if (Array.isArray(input)) return input.map(buildTextFromAIInput).filter(Boolean).join('\n')
  if (typeof input === 'object') {
    const keys = ['summary', 'transcript', 'text', 'content', 'previewLine', 'message']
    const out = []
    keys.forEach((k) => {
      if (input[k]) out.push(String(input[k]))
    })
    return out.length ? out.join('\n') : JSON.stringify(input, null, 2)
  }
  return String(input)
}
