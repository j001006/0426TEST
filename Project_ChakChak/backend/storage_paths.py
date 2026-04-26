from pathlib import Path
import re
import unicodedata
from fastapi import HTTPException

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

ROOM_NAME_PATTERN = re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _().-]{1,60}$")
SYSTEM_DIR_NAMES = {"_users", "sessions", "global_library"}


def sanitize_room_name(room_name: str) -> str:
    if room_name is None:
        raise HTTPException(status_code=400, detail="roomName이 필요합니다.")

    cleaned = unicodedata.normalize("NFKC", room_name).strip()

    if not cleaned:
        raise HTTPException(status_code=400, detail="roomName은 비어 있을 수 없습니다.")

    if cleaned in SYSTEM_DIR_NAMES:
        raise HTTPException(status_code=400, detail="예약된 룸 이름은 사용할 수 없습니다.")

    if "/" in cleaned or "\\" in cleaned or ".." in cleaned:
        raise HTTPException(status_code=400, detail="roomName에 경로 문자를 사용할 수 없습니다.")

    if not ROOM_NAME_PATTERN.match(cleaned):
        raise HTTPException(
            status_code=400,
            detail="roomName은 한글, 영어, 숫자, 공백, _, -, ., 괄호만 사용할 수 있습니다.",
        )

    return cleaned


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def get_room_dir(room_name: str) -> Path:
    safe_name = sanitize_room_name(room_name)
    return ensure_data_dir() / safe_name


def get_room_sessions_dir(room_name: str) -> Path:
    return get_room_dir(room_name) / "sessions"


def get_session_dir(room_name: str, session_id: str) -> Path:
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        raise HTTPException(status_code=400, detail="잘못된 session_id입니다.")

    return get_room_sessions_dir(room_name) / session_id


def get_live_recordings_dir(room_name: str, session_id: str) -> Path:
    return get_session_dir(room_name, session_id) / "live_recordings"


def get_post_meeting_recordings_dir(room_name: str, session_id: str) -> Path:
    return get_session_dir(room_name, session_id) / "post_meeting_recordings"


def get_meeting_plan_dir(room_name: str, session_id: str) -> Path:
    return get_session_dir(room_name, session_id) / "meeting_plan"


def get_knowledge_dir(room_name: str, session_id: str) -> Path:
    return get_session_dir(room_name, session_id) / "knowledge"


def get_live_db_path(room_name: str, session_id: str) -> Path:
    return get_session_dir(room_name, session_id) / "live_recordings.sqlite3"


def get_post_db_path(room_name: str, session_id: str) -> Path:
    return get_session_dir(room_name, session_id) / "post_meeting_recordings.sqlite3"


def get_calendar_db_path(user_id: str = "default_user") -> Path:
    safe_user_id = user_id.strip() or "default_user"

    if "/" in safe_user_id or "\\" in safe_user_id or ".." in safe_user_id:
        raise HTTPException(status_code=400, detail="잘못된 user_id입니다.")

    user_dir = ensure_data_dir() / "_users" / safe_user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "calendar.sqlite3"