import sqlite3
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage_paths import get_calendar_db_path

router = APIRouter(prefix="/calendar", tags=["Calendar"])

DEFAULT_USER_ID = "default_user"


def conn(user_id: str = DEFAULT_USER_ID):
    db_path = get_calendar_db_path(user_id)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def ensure_calendar_tables(user_id: str = DEFAULT_USER_ID):
    c = conn(user_id)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            room_name TEXT,
            session_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    c.commit()
    c.close()


class CalendarEventCreatePayload(BaseModel):
    title: str
    description: str | None = ""
    startTime: str
    endTime: str | None = None
    roomName: str | None = None
    sessionId: str | None = None


class CalendarEventUpdatePayload(BaseModel):
    title: str | None = None
    description: str | None = None
    startTime: str | None = None
    endTime: str | None = None
    roomName: str | None = None
    sessionId: str | None = None


@router.get("/events")
def list_calendar_events():
    ensure_calendar_tables()

    c = conn()
    rows = c.execute(
        """
        SELECT *
        FROM calendar_events
        WHERE user_id = ?
        ORDER BY start_time ASC
        """,
        (DEFAULT_USER_ID,),
    ).fetchall()
    c.close()

    return {
        "events": [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "startTime": row["start_time"],
                "endTime": row["end_time"],
                "roomName": row["room_name"],
                "sessionId": row["session_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]
    }


@router.post("/events")
def create_calendar_event(payload: CalendarEventCreatePayload):
    ensure_calendar_tables()

    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="일정 제목이 필요합니다.")

    if not payload.startTime.strip():
        raise HTTPException(status_code=400, detail="시작 시간이 필요합니다.")

    now = datetime.now().isoformat()
    event_id = str(uuid.uuid4())

    c = conn()
    c.execute(
        """
        INSERT INTO calendar_events (
            id, user_id, title, description, start_time, end_time,
            room_name, session_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            DEFAULT_USER_ID,
            payload.title,
            payload.description or "",
            payload.startTime,
            payload.endTime,
            payload.roomName,
            payload.sessionId,
            now,
            now,
        ),
    )
    c.commit()
    c.close()

    return {
        "id": event_id,
        "title": payload.title,
        "description": payload.description or "",
        "startTime": payload.startTime,
        "endTime": payload.endTime,
        "roomName": payload.roomName,
        "sessionId": payload.sessionId,
        "createdAt": now,
        "updatedAt": now,
    }


@router.put("/events/{event_id}")
def update_calendar_event(event_id: str, payload: CalendarEventUpdatePayload):
    ensure_calendar_tables()

    c = conn()
    row = c.execute(
        "SELECT * FROM calendar_events WHERE id = ? AND user_id = ?",
        (event_id, DEFAULT_USER_ID),
    ).fetchone()

    if not row:
        c.close()
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")

    updated = {
        "title": payload.title if payload.title is not None else row["title"],
        "description": payload.description if payload.description is not None else row["description"],
        "start_time": payload.startTime if payload.startTime is not None else row["start_time"],
        "end_time": payload.endTime if payload.endTime is not None else row["end_time"],
        "room_name": payload.roomName if payload.roomName is not None else row["room_name"],
        "session_id": payload.sessionId if payload.sessionId is not None else row["session_id"],
        "updated_at": datetime.now().isoformat(),
    }

    c.execute(
        """
        UPDATE calendar_events
        SET title = ?, description = ?, start_time = ?, end_time = ?,
            room_name = ?, session_id = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            updated["title"],
            updated["description"],
            updated["start_time"],
            updated["end_time"],
            updated["room_name"],
            updated["session_id"],
            updated["updated_at"],
            event_id,
            DEFAULT_USER_ID,
        ),
    )
    c.commit()
    c.close()

    return {"ok": True, "id": event_id}


@router.delete("/events/{event_id}")
def delete_calendar_event(event_id: str):
    ensure_calendar_tables()

    c = conn()
    cur = c.execute(
        "DELETE FROM calendar_events WHERE id = ? AND user_id = ?",
        (event_id, DEFAULT_USER_ID),
    )
    c.commit()
    deleted = cur.rowcount
    c.close()

    if deleted == 0:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")

    return {"ok": True, "id": event_id}