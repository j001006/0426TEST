import React from 'react'

export default function HomeGate({ onOpenRooms, onOpenCalendar }) {
  return (
    <div className="h-screen w-screen bg-slate-950 text-white flex items-center justify-center">
      <div className="w-full max-w-4xl px-6">
        <div className="mb-10 text-center">
          <h1 className="text-4xl font-bold">ChakChak AI 회의 어시스턴트</h1>
          <p className="mt-3 text-slate-400">
            룸 기반 회의 관리와 사용자별 캘린더
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <button
            onClick={onOpenRooms}
            className="rounded-3xl bg-blue-600 p-12 text-left shadow-xl transition hover:bg-blue-500"
          >
            <div className="text-4xl font-bold">룸</div>
            <p className="mt-4 text-blue-100">
              참여 중인 프로젝트 룸을 선택하거나 새 룸을 생성합니다.
            </p>
          </button>

          <button
            onClick={onOpenCalendar}
            className="rounded-3xl bg-emerald-600 p-12 text-left shadow-xl transition hover:bg-emerald-500"
          >
            <div className="text-4xl font-bold">캘린더</div>
            <p className="mt-4 text-emerald-100">
              기존 캘린더 화면으로 이동합니다.
            </p>
          </button>
        </div>
      </div>
    </div>
  )
}