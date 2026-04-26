"use client";

import { useEffect, useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

type ViewMode = "home" | "rooms" | "room-detail" | "calendar";

type Room = {
  id: string;
  roomName: string;
  createdAt: string;
};

type MeetingSession = {
  id: string;
  sessionId: string;
  roomName: string;
  title: string;
  meetingType: string;
  meetingTime: string;
  keywords: string;
  status: string;
  createdAt: string;
  stoppedAt?: string | null;
};

type CalendarEvent = {
  id: string;
  title: string;
  description?: string;
  startTime: string;
  endTime?: string | null;
  roomName?: string | null;
  sessionId?: string | null;
};

export default function Home() {
  const [view, setView] = useState<ViewMode>("home");

  const [rooms, setRooms] = useState<Room[]>([]);
  const [selectedRoom, setSelectedRoom] = useState<string>("");
  const [sessions, setSessions] = useState<MeetingSession[]>([]);

  const [newRoomName, setNewRoomName] = useState("");
  const [newMeetingTitle, setNewMeetingTitle] = useState("");

  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [newEventTitle, setNewEventTitle] = useState("");
  const [newEventStartTime, setNewEventStartTime] = useState("");

  const [message, setMessage] = useState("");

  async function loadRooms() {
    setMessage("");

    const res = await fetch(`${API_BASE}/rooms`);
    if (!res.ok) {
      setMessage("룸 목록을 불러오지 못했습니다.");
      return;
    }

    const data = await res.json();
    setRooms(data.rooms || []);
  }

  async function createRoom() {
    const roomName = newRoomName.trim();
    if (!roomName) {
      setMessage("룸 이름을 입력하세요.");
      return;
    }

    const res = await fetch(`${API_BASE}/rooms`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ roomName }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      setMessage(err?.detail || "룸 생성에 실패했습니다.");
      return;
    }

    setNewRoomName("");
    setMessage("룸이 생성되었습니다.");
    await loadRooms();
  }

  async function openRooms() {
    setView("rooms");
    await loadRooms();
  }

  async function openRoomDetail(roomName: string) {
    setSelectedRoom(roomName);
    setView("room-detail");
    await loadRoomSessions(roomName);
  }

  async function loadRoomSessions(roomName: string) {
    const res = await fetch(`${API_BASE}/rooms/${encodeURIComponent(roomName)}/sessions`);

    if (!res.ok) {
      setMessage("룸 회의 목록을 불러오지 못했습니다.");
      return;
    }

    const data = await res.json();
    setSessions(data.sessions || []);
  }

  async function startMeeting() {
    if (!selectedRoom) {
      setMessage("룸을 먼저 선택하세요.");
      return;
    }

    const title = newMeetingTitle.trim() || "새 회의";

    const res = await fetch(`${API_BASE}/meeting/session/create`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        roomName: selectedRoom,
        title,
        meetingType: "general",
        meetingTime: new Date().toISOString(),
        keywords: "",
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      setMessage(err?.detail || "회의 시작에 실패했습니다.");
      return;
    }

    const data = await res.json();
    setNewMeetingTitle("");
    setMessage(`회의가 시작되었습니다. sessionId=${data.sessionId}`);
    await loadRoomSessions(selectedRoom);
  }

  async function loadCalendarEvents() {
    setMessage("");

    const res = await fetch(`${API_BASE}/calendar/events`);
    if (!res.ok) {
      setMessage("캘린더를 불러오지 못했습니다.");
      return;
    }

    const data = await res.json();
    setCalendarEvents(data.events || []);
  }

  async function openCalendar() {
    setView("calendar");
    await loadCalendarEvents();
  }

  async function createCalendarEvent() {
    const title = newEventTitle.trim();
    const startTime = newEventStartTime.trim();

    if (!title || !startTime) {
      setMessage("일정 제목과 시작 시간을 입력하세요.");
      return;
    }

    const res = await fetch(`${API_BASE}/calendar/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        title,
        description: "",
        startTime,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      setMessage(err?.detail || "일정 생성에 실패했습니다.");
      return;
    }

    setNewEventTitle("");
    setNewEventStartTime("");
    setMessage("일정이 생성되었습니다.");
    await loadCalendarEvents();
  }

  async function deleteCalendarEvent(eventId: string) {
    const res = await fetch(`${API_BASE}/calendar/events/${eventId}`, {
      method: "DELETE",
    });

    if (!res.ok) {
      setMessage("일정 삭제에 실패했습니다.");
      return;
    }

    setMessage("일정이 삭제되었습니다.");
    await loadCalendarEvents();
  }

  useEffect(() => {
    // 초기 화면에서는 아무 API도 호출하지 않는다.
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-white">
      <div className="mx-auto max-w-5xl">
        <header className="mb-10 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">ChakChak AI 회의 어시스턴트</h1>
            <p className="mt-2 text-sm text-slate-400">
              룸 기반 회의 관리와 사용자별 캘린더
            </p>
          </div>

          {view !== "home" && (
            <button
              onClick={() => {
                setView("home");
                setMessage("");
              }}
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
            >
              홈으로
            </button>
          )}
        </header>

        {message && (
          <div className="mb-6 rounded-xl border border-slate-700 bg-slate-900 p-4 text-sm text-slate-200">
            {message}
          </div>
        )}

        {view === "home" && (
          <section className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <button
              onClick={openRooms}
              className="rounded-2xl bg-blue-600 p-10 text-left shadow-lg transition hover:bg-blue-500"
            >
              <div className="text-3xl font-bold">룸</div>
              <p className="mt-3 text-blue-100">
                참여 중인 프로젝트 룸을 선택하거나 새 룸을 생성합니다.
              </p>
            </button>

            <button
              onClick={openCalendar}
              className="rounded-2xl bg-emerald-600 p-10 text-left shadow-lg transition hover:bg-emerald-500"
            >
              <div className="text-3xl font-bold">캘린더</div>
              <p className="mt-3 text-emerald-100">
                사용자별 회의 일정과 개인 일정을 확인합니다.
              </p>
            </button>
          </section>
        )}

        {view === "rooms" && (
          <section className="space-y-8">
            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <h2 className="mb-4 text-2xl font-semibold">새 룸 생성</h2>

              <div className="flex flex-col gap-3 md:flex-row">
                <input
                  value={newRoomName}
                  onChange={(e) => setNewRoomName(e.target.value)}
                  placeholder="예: 캡스톤프로젝트"
                  className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-blue-500"
                />

                <button
                  onClick={createRoom}
                  className="rounded-xl bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-500"
                >
                  새 룸 생성
                </button>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-2xl font-semibold">참여 중인 룸</h2>

                <button
                  onClick={loadRooms}
                  className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
                >
                  새로고침
                </button>
              </div>

              {rooms.length === 0 ? (
                <p className="text-slate-400">아직 생성된 룸이 없습니다.</p>
              ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {rooms.map((room) => (
                    <button
                      key={room.id}
                      onClick={() => openRoomDetail(room.roomName)}
                      className="rounded-xl border border-slate-700 bg-slate-950 p-5 text-left hover:border-blue-500"
                    >
                      <div className="text-xl font-semibold">{room.roomName}</div>
                      <div className="mt-2 text-xs text-slate-500">
                        생성일: {room.createdAt}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {view === "room-detail" && (
          <section className="space-y-8">
            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h2 className="text-2xl font-semibold">{selectedRoom}</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    이 룸 안에서 회의를 시작하면 data/{selectedRoom}/sessions/sessionId 경로가 생성됩니다.
                  </p>
                </div>

                <button
                  onClick={() => setView("rooms")}
                  className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
                >
                  룸 목록
                </button>
              </div>

              <div className="flex flex-col gap-3 md:flex-row">
                <input
                  value={newMeetingTitle}
                  onChange={(e) => setNewMeetingTitle(e.target.value)}
                  placeholder="회의 제목"
                  className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-blue-500"
                />

                <button
                  onClick={startMeeting}
                  className="rounded-xl bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-500"
                >
                  회의 시작
                </button>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-2xl font-semibold">이 룸의 회의 목록</h2>

                <button
                  onClick={() => loadRoomSessions(selectedRoom)}
                  className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
                >
                  새로고침
                </button>
              </div>

              {sessions.length === 0 ? (
                <p className="text-slate-400">아직 이 룸에서 시작한 회의가 없습니다.</p>
              ) : (
                <div className="space-y-3">
                  {sessions.map((session) => (
                    <div
                      key={session.sessionId}
                      className="rounded-xl border border-slate-700 bg-slate-950 p-4"
                    >
                      <div className="flex items-center justify-between gap-4">
                        <div>
                          <div className="font-semibold">{session.title}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            sessionId: {session.sessionId}
                          </div>
                        </div>

                        <span className="rounded-full bg-slate-800 px-3 py-1 text-xs">
                          {session.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {view === "calendar" && (
          <section className="space-y-8">
            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <h2 className="mb-4 text-2xl font-semibold">새 일정 추가</h2>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <input
                  value={newEventTitle}
                  onChange={(e) => setNewEventTitle(e.target.value)}
                  placeholder="일정 제목"
                  className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-emerald-500"
                />

                <input
                  value={newEventStartTime}
                  onChange={(e) => setNewEventStartTime(e.target.value)}
                  placeholder="예: 2026-04-26T21:30:00"
                  className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-emerald-500"
                />

                <button
                  onClick={createCalendarEvent}
                  className="rounded-xl bg-emerald-600 px-6 py-3 font-semibold hover:bg-emerald-500"
                >
                  일정 생성
                </button>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-2xl font-semibold">캘린더 일정</h2>

                <button
                  onClick={loadCalendarEvents}
                  className="rounded-xl border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
                >
                  새로고침
                </button>
              </div>

              {calendarEvents.length === 0 ? (
                <p className="text-slate-400">등록된 일정이 없습니다.</p>
              ) : (
                <div className="space-y-3">
                  {calendarEvents.map((event) => (
                    <div
                      key={event.id}
                      className="flex items-center justify-between rounded-xl border border-slate-700 bg-slate-950 p-4"
                    >
                      <div>
                        <div className="font-semibold">{event.title}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          시작: {event.startTime}
                        </div>
                      </div>

                      <button
                        onClick={() => deleteCalendarEvent(event.id)}
                        className="rounded-xl border border-red-700 px-4 py-2 text-sm text-red-300 hover:bg-red-950"
                      >
                        삭제
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}