import React, { useState } from 'react'
import Sidebar from './components/Sidebar'
import MeetingRoomPrep from './components/MeetingRoomPrep'
import MeetingLiveView from './components/MeetingLiveView'
import STTWorkspace from './components/STTWorkspace'
import MeetingReportView from './components/MeetingReportView'
import Mindmap from './components/Mindmap'
import CalendarView from './components/CalendarView'
import HomeGate from './components/HomeGate'
import RoomSelector from './components/RoomSelector'

export default function App() {
  const [entryView, setEntryView] = useState('home')
  const [activeView, setActiveView] = useState('prep')

  const [selectedRoomName, setSelectedRoomName] = useState(null)
  const [sessionData, setSessionData] = useState(null)
  const [reportSessionId, setReportSessionId] = useState(null)
  const [useWebSearch, setUseWebSearch] = useState(false)

  const openReport = (sessionId) => {
    if (sessionId) setReportSessionId(sessionId)
    setActiveView('analysis')
  }

  const enterRoom = (roomName) => {
    setSelectedRoomName(roomName)
    setSessionData(null)
    setReportSessionId(null)
    setUseWebSearch(false)
    setActiveView('prep')
    setEntryView('workspace')
  }

  const openCalendarFromHome = () => {
    setSelectedRoomName(null)
    setSessionData(null)
    setReportSessionId(null)
    setActiveView('calendar')
    setEntryView('workspace')
  }

  const goHome = () => {
    setEntryView('home')
    setActiveView('prep')
    setSelectedRoomName(null)
    setSessionData(null)
    setReportSessionId(null)
    setUseWebSearch(false)
  }

  const goRooms = () => {
    setEntryView('rooms')
    setActiveView('prep')
  }

  if (entryView === 'home') {
    return (
      <HomeGate
        onOpenRooms={() => setEntryView('rooms')}
        onOpenCalendar={openCalendarFromHome}
      />
    )
  }

  if (entryView === 'rooms') {
    return (
      <RoomSelector
        onBackHome={goHome}
        onSelectRoom={enterRoom}
      />
    )
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white">
      <Sidebar activeView={activeView} setActiveView={setActiveView} />

      <main className="flex-1 min-w-0 overflow-hidden">
        {activeView !== 'calendar' && (
          <div className="flex items-center justify-between border-b bg-white px-6 py-3">
            <div>
              <div className="text-xs text-gray-500">현재 룸</div>
              <div className="font-semibold text-gray-900">
                {selectedRoomName || '룸 미선택'}
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={goRooms}
                className="rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
              >
                룸 목록
              </button>

              <button
                onClick={goHome}
                className="rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
              >
                홈
              </button>
            </div>
          </div>
        )}

        {activeView === 'calendar' && (
          <div className="flex items-center justify-between border-b bg-white px-6 py-3">
            <div>
              <div className="text-xs text-gray-500">캘린더</div>
              <div className="font-semibold text-gray-900">
                사용자 캘린더
              </div>
            </div>

            <button
              onClick={goHome}
              className="rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
            >
              홈
            </button>
          </div>
        )}

        <div className="h-[calc(100%-57px)] overflow-hidden">
          {activeView === 'prep' && (
            <MeetingRoomPrep
              roomName={selectedRoomName}
              onStartMeeting={(data) => {
                const mergedData = {
                  ...data,
                  roomName: data?.roomName || selectedRoomName,
                }

                setSessionData(mergedData)
                setReportSessionId(mergedData?.sessionId || mergedData?.id)
                setActiveView('live')
              }}
            />
          )}

          {activeView === 'live' && (
            sessionData ? (
              <MeetingLiveView
                planData={sessionData}
                roomName={selectedRoomName}
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
            <STTWorkspace
              roomName={selectedRoomName}
              onOpenMeetingReport={openReport}
            />
          )}

          {activeView === 'analysis' && (
            <MeetingReportView
              roomName={selectedRoomName}
              sessionId={reportSessionId || sessionData?.sessionId || sessionData?.id}
            />
          )}

          {activeView === 'calendar' && (
            <CalendarView />
          )}

          {activeView === 'mindmap' && (
            <div className="h-full overflow-hidden">
              <Mindmap />
            </div>
          )}
        </div>
      </main>
    </div>
  )
}