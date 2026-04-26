const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export async function generateMindmap(text) {
  const res = await fetch(`${API_BASE_URL}/mindmap`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

  if (!res.ok) {
    throw new Error('마인드맵 생성 실패')
  }

  return res.json()
}
