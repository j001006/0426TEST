import React from 'react'
import { BarChart3, Calendar, FileAudio, Network, Radio } from 'lucide-react'

export default function Sidebar({ activeView, setActiveView }) {
  const items = [
    { key: 'prep', label: '실시간 회의 준비', icon: Radio },
    { key: 'stt', label: '회의 기록 / STT 보관함', icon: FileAudio },
    { key: 'analysis', label: '회의 분석', icon: BarChart3 },
    { key: 'calendar', label: '캘린더', icon: Calendar },
    { key: 'mindmap', label: '마인드맵', icon: Network },
  ]

  return (
    <aside className="w-[280px] h-full bg-[#f6f7fb] border-r border-gray-200 flex flex-col">
      <div className="px-5 py-5 border-b border-gray-200">
        <div className="text-[28px] font-black tracking-tight text-gray-900">
          Workspace.
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2">
        {items.map((item) => {
          const Icon = item.icon
          const active = activeView === item.key
          return (
            <button
              key={item.key}
              onClick={() => setActiveView(item.key)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-2xl text-sm font-bold transition ${
                active
                  ? 'bg-blue-600 text-white shadow'
                  : 'bg-white text-gray-700 border border-gray-200 hover:bg-gray-50'
              }`}
            >
              <Icon className="w-4 h-4" />
              {item.label}
            </button>
          )
        })}
      </div>
    </aside>
  )
}
