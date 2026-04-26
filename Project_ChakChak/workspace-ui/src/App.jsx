import React, { useState } from 'react'
import Sidebar from './components/Sidebar'
import MeetingRoomPrep from './components/MeetingRoomPrep'
import MeetingLiveView from './components/MeetingLiveView'
import STTWorkspace from './components/STTWorkspace'
import MeetingReportView from './components/MeetingReportView'
import Mindmap from './components/Mindmap'
import CalendarView from './components/CalendarView'

export default function App() {
  const [activeView, setActiveView] = useState('prep')
  const [sessionData, setSessionData] = useState(null)
  const [reportSessionId, setReportSessionId] = useState(null)
  const [useWebSearch, setUseWebSearch] = useState(false)

  const openReport = (sessionId) => {
    if (sessionId) setReportSessionId(sessionId)
    setActiveView('analysis')
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white">
      <Sidebar activeView={activeView} setActiveView={setActiveView} />

      <main className="flex-1 min-w-0 overflow-hidden">
        {activeView === 'prep' && (
          <MeetingRoomPrep
            onStartMeeting={(data) => {
              setSessionData(data)
              setReportSessionId(data?.sessionId || data?.id)
              setActiveView('live')
            }}
          />
        )}

        {activeView === 'live' && (
          sessionData ? (
            <MeetingLiveView
              planData={sessionData}
              useWebSearch={useWebSearch}
              setUseWebSearch={setUseWebSearch}
              onOpenMeetingReport={openReport}
            />
          ) : (
            <div className="p-10">
              <h1 className="text-2xl font-bold">sessionId가 없습니다.</h1>
              <button
                onClick={() => setActiveView('prep')}
                className="mt-4 px-4 py-2 rounded-xl bg-blue-600 text-white"
              >
                회의 준비로 돌아가기
              </button>
            </div>
          )
        )}

        {activeView === 'stt' && (
          <STTWorkspace onOpenMeetingReport={openReport} />
        )}

        {activeView === 'analysis' && (
          <MeetingReportView sessionId={reportSessionId || sessionData?.sessionId || sessionData?.id} />
        )}

        {activeView === 'calendar' && (
          <CalendarView />
        )}

        {activeView === 'mindmap' && (
          <div className="h-full overflow-hidden">
            <Mindmap />
          </div>
        )}
      </main>
    </div>
  )
}
