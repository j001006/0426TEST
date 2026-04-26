import React, { useEffect, useState } from 'react'
import { createRoom, fetchRooms } from '../services/roomApi'

export default function RoomSelector({ onBackHome, onSelectRoom }) {
  const [rooms, setRooms] = useState([])
  const [newRoomName, setNewRoomName] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const loadRooms = async () => {
    try {
      setLoading(true)
      setMessage('')
      const data = await fetchRooms()
      setRooms(data.rooms || [])
    } catch (err) {
      setMessage(err.message || '룸 목록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const handleCreateRoom = async () => {
    const roomName = newRoomName.trim()

    if (!roomName) {
      setMessage('룸 이름을 입력하세요.')
      return
    }

    try {
      setLoading(true)
      setMessage('')
      await createRoom(roomName)
      setNewRoomName('')
      setMessage('룸이 생성되었습니다.')
      await loadRooms()
    } catch (err) {
      setMessage(err.message || '룸 생성에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRooms()
  }, [])

  return (
    <div className="h-screen w-screen overflow-auto bg-slate-950 text-white">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">룸 선택</h1>
            <p className="mt-2 text-sm text-slate-400">
              참여 중인 프로젝트 룸을 선택하세요.
            </p>
          </div>

          <button
            onClick={onBackHome}
            className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
          >
            홈으로
          </button>
        </header>

        {message && (
          <div className="mb-6 rounded-xl border border-slate-700 bg-slate-900 p-4 text-sm text-slate-200">
            {message}
          </div>
        )}

        <section className="mb-8 rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="mb-4 text-xl font-semibold">새 룸 생성</h2>

          <div className="flex flex-col gap-3 md:flex-row">
            <input
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              placeholder="예: 캡스톤프로젝트"
              className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-blue-500"
            />

            <button
              onClick={handleCreateRoom}
              disabled={loading}
              className="rounded-xl bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-500 disabled:opacity-50"
            >
              새 룸 생성
            </button>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-semibold">참여 중인 룸</h2>

            <button
              onClick={loadRooms}
              disabled={loading}
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
            >
              새로고침
            </button>
          </div>

          {loading && (
            <p className="text-slate-400">불러오는 중...</p>
          )}

          {!loading && rooms.length === 0 && (
            <p className="text-slate-400">아직 생성된 룸이 없습니다.</p>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {rooms.map((room) => (
              <button
                key={room.id || room.roomName}
                onClick={() => onSelectRoom(room.roomName)}
                className="rounded-xl border border-slate-700 bg-slate-950 p-5 text-left hover:border-blue-500"
              >
                <div className="text-xl font-semibold">{room.roomName}</div>
                <div className="mt-2 text-xs text-slate-500">
                  생성일: {room.createdAt || '-'}
                </div>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}