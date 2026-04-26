import sqlite3
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage_paths import DATA_DIR, get_room_sessions_dir, sanitize_room_name

router = APIRouter(prefix="/rooms", tags=["Rooms"])

DB_PATH = DATA_DIR / "meeting_app.sqlite3"
DEFAULT_USER_ID = "default_user"


def conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ensure_room_tables():
    c = conn()
    cur = c.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY,
            room_name TEXT UNIQUE NOT NULL,
            owner_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS room_members (
            id TEXT PRIMARY KEY,
            room_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            created_at TEXT NOT NULL,
            UNIQUE(room_name, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_sessions (
            id TEXT PRIMARY KEY,
            room_name TEXT DEFAULT 'default_room',
            title TEXT NOT NULL,
            meeting_time TEXT,
            keywords TEXT,
            meeting_type TEXT,
            realtime_recording_enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            stopped_at TEXT,
            status TEXT DEFAULT 'live'
        )
        """
    )

    cur.execute("PRAGMA table_info(meeting_sessions)")
    cols = {row[1] for row in cur.fetchall()}
    if "room_name" not in cols:
        cur.execute("ALTER TABLE meeting_sessions ADD COLUMN room_name TEXT DEFAULT 'default_room'")

    c.commit()
    c.close()


class RoomCreatePayload(BaseModel):
    roomName: str


@router.get("")
def list_rooms():
    ensure_room_tables()

    c = conn()
    rows = c.execute(
        """
        SELECT r.*
        FROM rooms r
        JOIN room_members m ON r.room_name = m.room_name
        WHERE m.user_id = ?
        ORDER BY r.created_at DESC
        """,
        (DEFAULT_USER_ID,),
    ).fetchall()
    c.close()

    return {
        "rooms": [
            {
                "id": row["id"],
                "roomName": row["room_name"],
                "ownerUserId": row["owner_user_id"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
    }


@router.post("")
def create_room(payload: RoomCreatePayload):
    ensure_room_tables()

    room_name = sanitize_room_name(payload.roomName)
    now = datetime.now().isoformat()

    sessions_dir = get_room_sessions_dir(room_name)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    c = conn()

    exists = c.execute(
        "SELECT id FROM rooms WHERE room_name = ?",
        (room_name,),
    ).fetchone()

    if exists:
        c.close()
        raise HTTPException(status_code=409, detail="이미 존재하는 룸입니다.")

    room_id = str(uuid.uuid4())

    c.execute(
        """
        INSERT INTO rooms (id, room_name, owner_user_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (room_id, room_name, DEFAULT_USER_ID, now),
    )

    c.execute(
        """
        INSERT OR IGNORE INTO room_members (id, room_name, user_id, role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), room_name, DEFAULT_USER_ID, "owner", now),
    )

    c.commit()
    c.close()

    return {
        "id": room_id,
        "roomName": room_name,
        "sessionsDir": str(sessions_dir),
        "createdAt": now,
    }


@router.get("/{room_name}/sessions")
def list_room_sessions(room_name: str):
    ensure_room_tables()

    safe_room_name = sanitize_room_name(room_name)

    c = conn()
    rows = c.execute(
        """
        SELECT *
        FROM meeting_sessions
        WHERE room_name = ?
        ORDER BY created_at DESC
        """,
        (safe_room_name,),
    ).fetchall()
    c.close()

    return {
        "roomName": safe_room_name,
        "sessions": [
            {
                "id": row["id"],
                "sessionId": row["id"],
                "roomName": row["room_name"],
                "title": row["title"],
                "meetingType": row["meeting_type"],
                "meetingTime": row["meeting_time"],
                "keywords": row["keywords"],
                "status": row["status"],
                "createdAt": row["created_at"],
                "stoppedAt": row["stopped_at"],
            }
            for row in rows
        ],
    }