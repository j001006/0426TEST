import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from storage_paths import get_live_db_path, get_post_db_path


def _connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_live_recordings_db(db_path: Path):
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS live_transcripts (
            id TEXT PRIMARY KEY,
            room_name TEXT NOT NULL,
            session_id TEXT NOT NULL,
            speaker TEXT,
            start_sec REAL DEFAULT 0,
            end_sec REAL DEFAULT 0,
            text TEXT NOT NULL,
            source_file TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS realtime_ai_events (
            id TEXT PRIMARY KEY,
            room_name TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            question TEXT,
            answer TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def init_post_meeting_recordings_db(db_path: Path):
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS post_meeting_reports (
            id TEXT PRIMARY KEY,
            room_name TEXT NOT NULL,
            session_id TEXT NOT NULL,
            summary TEXT,
            full_transcript TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS timeline_items (
            id TEXT PRIMARY KEY,
            room_name TEXT NOT NULL,
            session_id TEXT NOT NULL,
            start_sec REAL DEFAULT 0,
            end_sec REAL DEFAULT 0,
            title TEXT,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS action_items (
            id TEXT PRIMARY KEY,
            room_name TEXT NOT NULL,
            session_id TEXT NOT NULL,
            task TEXT NOT NULL,
            owner TEXT,
            due_date TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def init_session_databases(room_name: str, session_id: str):
    live_db_path = get_live_db_path(room_name, session_id)
    post_db_path = get_post_db_path(room_name, session_id)

    init_live_recordings_db(live_db_path)
    init_post_meeting_recordings_db(post_db_path)

    return {
        "liveDbPath": str(live_db_path),
        "postDbPath": str(post_db_path),
    }


def insert_live_transcript(
    room_name: str,
    session_id: str,
    text: str,
    speaker: str = "익명1",
    start_sec: float = 0,
    end_sec: float = 0,
    source_file: str | None = None,
):
    db_path = get_live_db_path(room_name, session_id)
    init_live_recordings_db(db_path)

    conn = _connect(db_path)
    conn.execute(
        """
        INSERT INTO live_transcripts (
            id, room_name, session_id, speaker, start_sec, end_sec,
            text, source_file, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            room_name,
            session_id,
            speaker,
            start_sec,
            end_sec,
            text,
            source_file,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def insert_post_summary(
    room_name: str,
    session_id: str,
    summary: str,
    full_transcript: str,
):
    db_path = get_post_db_path(room_name, session_id)
    init_post_meeting_recordings_db(db_path)

    conn = _connect(db_path)
    conn.execute(
        """
        INSERT INTO post_meeting_reports (
            id, room_name, session_id, summary, full_transcript, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            room_name,
            session_id,
            summary,
            full_transcript,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()