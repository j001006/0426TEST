const API_BASE =
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

async function parseResponse(res) {
  const data = await res.json().catch(() => null)

  if (!res.ok) {
    const message = data?.detail || data?.message || '요청 처리 중 오류가 발생했습니다.'
    throw new Error(message)
  }

  return data
}

export async function fetchRooms() {
  const res = await fetch(`${API_BASE}/rooms`)
  return parseResponse(res)
}

export async function createRoom(roomName) {
  const res = await fetch(`${API_BASE}/rooms`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ roomName }),
  })

  return parseResponse(res)
}

export async function fetchRoomSessions(roomName) {
  const res = await fetch(`${API_BASE}/rooms/${encodeURIComponent(roomName)}/sessions`)
  return parseResponse(res)
}

export { API_BASE }