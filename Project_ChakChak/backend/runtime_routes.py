import os
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from storage_paths import (
    get_room_sessions_dir,
    get_session_dir,
    get_live_recordings_dir,
    get_post_meeting_recordings_dir,
    get_meeting_plan_dir,
    get_knowledge_dir,
    sanitize_room_name,
)

from session_db import (
    init_session_databases,
    insert_live_transcript,
    insert_post_summary,
)

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "meeting_app.sqlite3"

# =========================
# Local SLM direct loader
# 0424test 방식: SLM_Loader.load_slm()
# =========================
SLM_MODEL_CACHE = {
    "model": None,
    "tokenizer": None,
    "device": None,
}

def call_local_slm(prompt: str, max_new_tokens: int = 80):
    import torch
    from SLM_Loader import load_slm

    if SLM_MODEL_CACHE["model"] is None or SLM_MODEL_CACHE["tokenizer"] is None:
        model, tokenizer = load_slm()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        model.eval()

        SLM_MODEL_CACHE["model"] = model
        SLM_MODEL_CACHE["tokenizer"] = tokenizer
        SLM_MODEL_CACHE["device"] = device

    model = SLM_MODEL_CACHE["model"]
    tokenizer = SLM_MODEL_CACHE["tokenizer"]
    device = SLM_MODEL_CACHE["device"]

    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            do_sample=False,
            repetition_penalty=1.2,
        )

    answer = tokenizer.decode(output_ids[0], skip_special_tokens=True)

    if "assistant\n" in answer:
        answer = answer.split("assistant\n")[-1].strip()
    else:
        # prompt까지 같이 decode되는 모델 대응
        answer = answer.replace(prompt, "").strip()

    return answer



WHISPER_MODEL_CACHE = {}

def get_whisper_model(model_name: str = "base"):
    if model_name in WHISPER_MODEL_CACHE:
        return WHISPER_MODEL_CACHE[model_name]

    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    WHISPER_MODEL_CACHE[model_name] = model
    return model


def ffmpeg_to_wav(src_path: str, wav_path: str):
    import subprocess

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        "-ac",
        "1",
        "-ar",
        "16000",
        "-vn",
        wav_path,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:])


def transcribe_realtime_audio(file_path: str, offset_sec: float = 0):
    import os
    import tempfile

    model = get_whisper_model("base")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        wav_path = tmp.name

    try:
        ffmpeg_to_wav(file_path, wav_path)

        segments, _ = model.transcribe(
            wav_path,
            language="ko",
            vad_filter=True,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
        )

        lines = []

        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue

            start = int(float(offset_sec) + float(seg.start))
            end = int(float(offset_sec) + float(seg.end))
            if end <= start:
                end = start + 1

            m1, s1 = divmod(start, 60)
            m2, s2 = divmod(end, 60)

            lines.append(f"[{m1:02d}:{s1:02d}~{m2:02d}:{s2:02d}] 익명1: {text}")

        return "\n".join(lines)
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass




def conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ensure_tables():
    c = conn()
    cur = c.cursor()

    cur.execute("""
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
    """)
    
    cur.execute("PRAGMA table_info(meeting_sessions)")
    cols = {row[1] for row in cur.fetchall()}

    if "room_name" not in cols:
        cur.execute("ALTER TABLE meeting_sessions ADD COLUMN room_name TEXT DEFAULT 'default_room'")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id TEXT PRIMARY KEY,
        room_name TEXT UNIQUE NOT NULL,
        owner_user_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS room_members (
        id TEXT PRIMARY KEY,
        room_name TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT DEFAULT 'member',
        created_at TEXT NOT NULL,
        UNIQUE(room_name, user_id)
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS library_items (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        scope TEXT NOT NULL,
        bucket TEXT NOT NULL,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        text_content TEXT,
        preview_line TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_ai_events (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT,
        asked_at_sec REAL DEFAULT 0,
        before_context TEXT,
        after_context TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_report_cache (
        session_id TEXT PRIMARY KEY,
        report_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    c.commit()
    c.close()


def row_to_dict(row):
    return dict(row) if row else None

def get_room_name_by_session_id(session_id: str) -> str:
    ensure_tables()

    c = conn()
    row = c.execute(
        "SELECT room_name FROM meeting_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    c.close()

    if not row:
        raise HTTPException(status_code=404, detail="회의 세션을 찾을 수 없습니다.")

    return sanitize_room_name(row["room_name"] or "default_room")

def save_library_item(session_id, bucket, kind, name, file_path, text_content=""):
    ensure_tables()
    item_id = str(uuid.uuid4())
    preview = (text_content or name or "").splitlines()[0][:220] if (text_content or name) else ""
    now = datetime.now().isoformat()

    c = conn()
    c.execute("""
    INSERT INTO library_items
    (id, session_id, scope, bucket, kind, name, file_path, text_content, preview_line, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id,
        session_id,
        "session" if session_id else "global",
        bucket,
        kind,
        name,
        file_path,
        text_content or "",
        preview,
        now,
    ))
    c.commit()
    c.close()

    return {
        "id": item_id,
        "sessionId": session_id,
        "bucket": bucket,
        "kind": kind,
        "name": name,
        "filePath": file_path,
        "textContent": text_content or "",
        "previewLine": preview,
        "createdAt": now,
    }


class MeetingCreatePayload(BaseModel):
    title: str | None = None
    meetingTitle: str | None = None
    meeting_type: str | None = None
    meetingType: str | None = None
    meeting_time: str | None = None
    meetingTime: str | None = None
    keywords: str | None = ""
    plan_text: str | None = None
    planText: str | None = None
    realtime_recording_enabled: bool | None = True
    realtimeRecordingEnabled: bool | None = True
    room_name: str | None = None
    roomName: str | None = None


@router.post("/meeting/session/create")
def create_meeting_session(payload: MeetingCreatePayload):
    ensure_tables()

    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    title = payload.title or payload.meetingTitle or "새 회의"
    room_name = sanitize_room_name(payload.room_name or payload.roomName or "default_room")
    session_dir = get_session_dir(room_name, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    init_session_databases(room_name, session_id)
    meeting_type = payload.meeting_type or payload.meetingType or "general"
    meeting_time = payload.meeting_time or payload.meetingTime or now
    keywords = payload.keywords or ""
    plan_text = payload.plan_text or payload.planText or ""

    c = conn()
    c.execute("""
    INSERT INTO meeting_sessions (
        id, room_name, title, meeting_time, keywords, meeting_type,
        realtime_recording_enabled, created_at, stopped_at, status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        room_name,
        title,
        meeting_time,
        keywords,
        meeting_type,
        1,
        now,
        None,
        "live",
    ))
    c.commit()
    c.close()

    if plan_text.strip():
        plan_dir = get_meeting_plan_dir(room_name, session_id)
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "meeting_plan.txt"
        plan_path.write_text(plan_text, encoding="utf-8")

        save_library_item(
            session_id=session_id,
            bucket="meeting_plan",
            kind="meeting_plan_text",
            name="meeting_plan.txt",
            file_path=str(plan_path),
            text_content=plan_text,
        )

    return {
        "sessionId": session_id,
        "id": session_id,
        "roomName": room_name,
        "title": title,
        "meetingType": meeting_type,
        "meetingTime": meeting_time,
        "keywords": keywords,
        "status": "live",
        "sessionDir": str(session_dir),
    }


@router.get("/meeting/session/{session_id}")
def get_meeting_session(session_id: str):
    ensure_tables()
    c = conn()
    row = c.execute("SELECT * FROM meeting_sessions WHERE id = ?", (session_id,)).fetchone()
    c.close()

    if not row:
        raise HTTPException(status_code=404, detail="회의 세션을 찾을 수 없습니다.")

    d = row_to_dict(row)
    d["sessionId"] = d["id"]
    return d


@router.post("/meeting/session/{session_id}/plan")
async def upload_meeting_plan(session_id: str, file: UploadFile = File(...)):
    ensure_tables()
    room_name = get_room_name_by_session_id(session_id)
    target_dir = get_meeting_plan_dir(room_name, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / file.filename
    content = await file.read()
    path.write_bytes(content)

    text = ""
    try:
        text = content.decode("utf-8")
    except Exception:
        text = file.filename

    item = save_library_item(session_id, "meeting_plan", "uploaded_plan", file.filename, str(path), text)
    return item


@router.post("/meeting/session/{session_id}/knowledge")
async def upload_meeting_knowledge(session_id: str, file: UploadFile = File(...)):
    ensure_tables()
    room_name = get_room_name_by_session_id(session_id)
    target_dir = get_knowledge_dir(room_name, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / file.filename
    content = await file.read()
    path.write_bytes(content)

    text = ""
    try:
        text = content.decode("utf-8")
    except Exception:
        text = file.filename

    item = save_library_item(session_id, "knowledge", "uploaded_knowledge", file.filename, str(path), text)
    return item


@router.post("/library/global/upload")
async def upload_global_file(file: UploadFile = File(...)):
    ensure_tables()
    target_dir = DATA_DIR / "global_library"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / file.filename
    content = await file.read()
    path.write_bytes(content)

    text = ""
    try:
        text = content.decode("utf-8")
    except Exception:
        text = file.filename

    item = save_library_item(None, "uploaded_knowledge", "global_file", file.filename, str(path), text)
    return item


@router.get("/library/global/tree")
def get_global_tree():
    ensure_tables()
    c = conn()
    rows = c.execute("""
    SELECT * FROM library_items
    WHERE session_id IS NULL
    ORDER BY created_at DESC
    """).fetchall()
    c.close()

    uploaded = []
    for r in rows:
        d = row_to_dict(r)
        d["createdAt"] = d.get("created_at")
        d["previewLine"] = d.get("preview_line")
        uploaded.append(d)

    return {
        "realtimeMeetings": [],
        "postMeetingRecordings": [],
        "uploadedKnowledge": uploaded,
    }


@router.get("/meeting/session/{session_id}/library-tree")
def get_session_library_tree(session_id: str):
    ensure_tables()
    c = conn()
    rows = c.execute("""
    SELECT * FROM library_items
    WHERE session_id = ?
    ORDER BY created_at DESC
    """, (session_id,)).fetchall()
    c.close()

    live = []
    post = []
    uploaded = []
    plan = []

    for r in rows:
        d = row_to_dict(r)
        d["createdAt"] = d.get("created_at")
        d["previewLine"] = d.get("preview_line")
        bucket = d.get("bucket")

        if bucket == "live_recordings":
            live.append(d)
        elif bucket == "post_meeting_recordings":
            post.append(d)
        elif bucket == "meeting_plan":
            plan.append(d)
        else:
            uploaded.append(d)

    return {
        "liveRecordings": live,
        "postMeetingRecordings": post,
        "uploadedKnowledge": uploaded,
        "meetingPlan": plan,
    }


@router.post("/meeting/session/{session_id}/realtime-chunk")
async def upload_realtime_chunk(
    session_id: str,
    file: UploadFile = File(...),
    offset_sec: float = Form(0),
):
    ensure_tables()
    room_name = get_room_name_by_session_id(session_id)
    target_dir = get_live_recordings_dir(room_name, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    path = target_dir / f"chunk_{int(offset_sec)}_{file.filename}"
    content = await file.read()

    if not content or len(content) < 1024:
        return {
            "ok": True,
            "skipped": True,
            "reason": "too_short_chunk",
            "transcript": "",
        }

    path.write_bytes(content)

    try:
        transcript = transcribe_realtime_audio(str(path), offset_sec)
    except Exception as e:
        err = str(e)
        if (
            "EBML header parsing failed" in err
            or "Invalid data found when processing input" in err
            or "Error opening input" in err
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "invalid_webm_chunk",
                "detail": err[-500:],
                "transcript": "",
            }
        raise HTTPException(status_code=500, detail=f"실시간 STT 변환 실패: {err}")

    if not transcript.strip():
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_speech_detected",
            "transcript": "",
        }

    insert_live_transcript(
        room_name=room_name,
        session_id=session_id,
        text=transcript,
        speaker="익명1",
        start_sec=offset_sec,
        end_sec=offset_sec,
        source_file=str(path),
    )
    
    item = save_library_item(
        session_id=session_id,
        bucket="live_recordings",
        kind="realtime_audio_chunk",
        name=path.name,
        file_path=str(path),
        text_content=transcript,
    )

    return {
        "ok": True,
        "sessionId": session_id,
        "transcript": transcript,
        "item": item,
    }


@router.post("/meeting/session/{session_id}/mid-summary")
def mid_summary(session_id: str):
    ensure_tables()
    transcript = read_session_transcript(session_id)

    if not transcript.strip():
        return {
            "summary": "아직 누적된 STT 기록이 없습니다.",
            "sessionId": session_id,
        }

    return {
        "summary": f"현재까지 {len(transcript.splitlines())}개의 STT 기록이 누적되었습니다.\n\n핵심 요약은 회의 종료 후 전체 STT 기반으로 생성됩니다.",
        "sessionId": session_id,
    }


@router.post("/meeting/session/{session_id}/feedback")
def feedback(session_id: str):
    ensure_tables()
    transcript = read_session_transcript(session_id)

    if not transcript.strip():
        return {
            "feedback": "아직 누적된 STT 기록이 없어 피드백을 생성할 수 없습니다.",
            "sessionId": session_id,
        }

    return {
        "feedback": "회의가 진행 중입니다. 현재 누적된 STT를 기준으로 보면, 논의 흐름을 유지하면서 결정사항과 다음 액션을 명확히 정리하는 것이 좋습니다.",
        "sessionId": session_id,
    }


def read_session_transcript(session_id: str):
    ensure_tables()
    c = conn()
    rows = c.execute("""
    SELECT text_content, preview_line FROM library_items
    WHERE session_id = ?
      AND bucket IN ('live_recordings', 'post_meeting_recordings')
    ORDER BY created_at ASC
    """, (session_id,)).fetchall()
    c.close()

    texts = []
    for r in rows:
        t = r["text_content"] or r["preview_line"] or ""
        if t.strip():
            texts.append(t.strip())

    return "\n".join(texts)


@router.post("/meeting/session/{session_id}/stop")
def stop_meeting(session_id: str):
    ensure_tables()
    
    room_name = get_room_name_by_session_id(session_id)
    now = datetime.now().isoformat()

    transcript = read_session_transcript(session_id)
    final_summary = transcript or "저장된 STT 기록이 없습니다."

    c = conn()
    c.execute("""
    UPDATE meeting_sessions
    SET status = ?, stopped_at = ?
    WHERE id = ?
    """, ("stopped", now, session_id))
    c.commit()
    c.close()

    room_name = get_room_name_by_session_id(session_id)
    target_dir = get_post_meeting_recordings_dir(room_name, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "final_summary.md"
    path.write_text(final_summary, encoding="utf-8")

    insert_post_summary(
        room_name=room_name,
        session_id=session_id,
        summary=final_summary,
        full_transcript=transcript,
    )

    save_library_item(
        session_id=session_id,
        bucket="post_meeting_recordings",
        kind="final_summary",
        name="final_summary.md",
        file_path=str(path),
        text_content=final_summary,
    )

    return {
        "ok": True,
        "sessionId": session_id,
        "status": "stopped",
        "finalSummary": final_summary,
    }


# =========================
# AI chat route
# =========================
class AIChatPayload(BaseModel):
    message: str = ""
    meetingText: str = ""
    mode: str = "general"
    useWeb: bool = False
    sessionId: str | None = None
    meetingType: str = ""
    meetingTitle: str = ""
    keywords: str = ""
    purpose: str = "chat"


def call_ollama_simple(system_prompt: str, user_prompt: str, model: str = "qwen2.5:3b"):
    import requests

    response = requests.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=20,
    )

    if response.status_code != 200:
        raise RuntimeError(response.text)

    data = response.json()
    return data.get("message", {}).get("content", "")


@router.post("/ai/chat")
def ai_chat(payload: AIChatPayload):
    ensure_tables()

    meeting_text = payload.meetingText or ""

    if payload.sessionId and not meeting_text:
        meeting_text = read_session_transcript(payload.sessionId)

    system_prompt = """
너는 회의 보조 AI다.
반드시 한국어로 답한다.
회의 STT와 사용자의 질문을 근거로 답한다.
없는 사실은 만들지 말고, 정보가 부족하면 부족하다고 말한다.
답변은 회의 중 바로 사용할 수 있게 짧고 구체적으로 작성한다.
""".strip()

    user_prompt = f"""
[회의 제목]
{payload.meetingTitle}

[회의 종류]
{payload.meetingType}

[키워드]
{payload.keywords}

[웹검색 사용 여부]
{payload.useWeb}

[회의 STT]
{meeting_text[-12000:] if meeting_text else "(아직 STT 없음)"}

[사용자 질문]
{payload.message}
""".strip()

    try:
        prompt = f"{system_prompt}\n\n{user_prompt}\n\nassistant\n"
        answer = call_local_slm(prompt, max_new_tokens=350)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 응답 생성 실패: {str(e)}")

    return {
        "answer": answer,
        "message": answer,
        "usedWeb": payload.useWeb,
    }


@router.get("/meeting/sessions")
def list_meeting_sessions():
    ensure_tables()
    c = conn()
    sessions = c.execute("""
    SELECT * FROM meeting_sessions
    ORDER BY created_at DESC
    """).fetchall()

    out = []
    for s in sessions:
        session_id = s["id"]
        items = c.execute("""
        SELECT bucket, kind, name, preview_line, created_at
        FROM library_items
        WHERE session_id = ?
        ORDER BY created_at DESC
        """, (session_id,)).fetchall()

        live_count = 0
        post_count = 0
        latest_preview = ""

        for item in items:
            if item["bucket"] == "live_recordings":
                live_count += 1
            if item["bucket"] == "post_meeting_recordings":
                post_count += 1
            if not latest_preview and item["preview_line"]:
                latest_preview = item["preview_line"]

        out.append({
            "id": session_id,
            "sessionId": session_id,
            "title": s["title"],
            "meetingType": s["meeting_type"],
            "meetingTime": s["meeting_time"],
            "keywords": s["keywords"],
            "status": s["status"],
            "createdAt": s["created_at"],
            "stoppedAt": s["stopped_at"],
            "liveRecordingCount": live_count,
            "postRecordingCount": post_count,
            "previewLine": latest_preview,
        })

    c.close()
    return {"sessions": out}


# =========================
# Realtime meeting intelligence
# =========================
@router.get("/api/realtime-topic")
def realtime_topic():
    ensure_tables()

    c = conn()
    rows = c.execute("""
    SELECT text_content, preview_line
    FROM library_items
    WHERE bucket = 'live_recordings'
    ORDER BY created_at DESC
    LIMIT 8
    """).fetchall()
    c.close()

    transcript = "\n".join([
        (r["text_content"] or r["preview_line"] or "").strip()
        for r in reversed(rows)
        if (r["text_content"] or r["preview_line"] or "").strip()
    ])

    if not transcript.strip():
        return {
            "topic": "실시간 STT 대기 중",
            "currentTopic": "실시간 STT 대기 중",
            "summary": "아직 분석할 회의 발화가 없습니다.",
        }

    # 너무 짧으면 SLM 호출하지 않고 즉시 반환
    if len(transcript) < 80:
        return {
            "topic": "회의 발화 수집 중",
            "currentTopic": "회의 발화 수집 중",
            "summary": transcript[-300:],
        }

    system_prompt = """
너는 실시간 회의 주제 분석 AI다.
최근 STT를 보고 지금 논의 중인 주제를 짧은 한 문장으로 만든다.
키워드 나열 금지. 구어체 금지. 한국어로만 답한다.
예: "회의 분석 기능의 STT 저장 구조 점검"
""".strip()

    user_prompt = f"""
[최근 회의 STT]
{transcript[-3000:]}

현재 회의 주제를 15~35자 한 문장으로 출력해.
""".strip()

    try:
        prompt = f"{system_prompt}\n\n{user_prompt}\n\nassistant\n"
        topic = call_local_slm(prompt, max_new_tokens=40).strip().splitlines()[0]
    except Exception:
        # fallback: STT 일부로라도 UI가 멈추지 않게 처리
        topic = "실시간 회의 내용 분석 중"

    return {
        "topic": topic,
        "currentTopic": topic,
        "summary": transcript[-500:],
    }


@router.post("/meeting/session/{session_id}/mid-summary")
def mid_summary(session_id: str):
    ensure_tables()
    transcript = read_session_transcript(session_id)

    if not transcript.strip():
        return {
            "summary": "아직 누적된 STT 기록이 없습니다. 녹음을 조금 더 진행한 뒤 다시 요청하세요.",
            "sessionId": session_id,
        }

    system_prompt = """
너는 회의 중간 요약 AI다.
반드시 한국어로 답한다.
회의 중간에 바로 볼 수 있도록 간결하게 정리한다.
출력 형식:
1. 지금까지 논의 핵심
2. 결정된 내용
3. 아직 남은 쟁점
4. 다음 액션
""".strip()

    user_prompt = f"""
[누적 STT]
{transcript[-12000:]}
""".strip()

    try:
        prompt = f"{system_prompt}\n\n{user_prompt}\n\nassistant\n"
        summary = call_local_slm(prompt, max_new_tokens=350)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"중간 요약 실패: {str(e)}")

    return {
        "summary": summary,
        "sessionId": session_id,
    }


@router.post("/meeting/session/{session_id}/feedback")
def feedback(session_id: str):
    ensure_tables()
    transcript = read_session_transcript(session_id)

    if not transcript.strip():
        return {
            "feedback": "아직 누적된 STT 기록이 없습니다. 녹음을 조금 더 진행한 뒤 다시 요청하세요.",
            "sessionId": session_id,
        }

    system_prompt = """
너는 회의 진행 피드백 AI다.
회의가 정체되었는지, 논점이 반복되는지, 다음 질문이 필요한지 판단한다.
반드시 한국어로 답한다.
출력 형식:
1. 현재 상태
2. 정체/반복 여부
3. 바로 던질 질문
4. 다음 행동 제안
""".strip()

    user_prompt = f"""
[누적 STT]
{transcript[-12000:]}
""".strip()

    try:
        prompt = f"{system_prompt}\n\n{user_prompt}\n\nassistant\n"
        feedback_text = call_local_slm(prompt, max_new_tokens=300)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"피드백 실패: {str(e)}")

    return {
        "feedback": feedback_text,
        "sessionId": session_id,
    }


# =========================
# Post-meeting audio upload + transcript/report API
# Restores Kimsinwooks/Chak STTWorkspace flow
# =========================
from fastapi import Query
import json

ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".webm", ".mp4", ".aac", ".ogg", ".flac", ".wma", ".wmv"}


def seconds_to_mmss(sec: float):
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_mmss_to_sec(t: str):
    try:
        parts = t.strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        pass
    return 0


def extract_transcript_lines(text: str):
    import re
    out = []
    pat = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\s*~\s*(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]{1,30})?:?\s*(.*)")
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = pat.match(line)
        if m:
            start, end, speaker, body = m.groups()
            out.append({
                "start": start,
                "end": end,
                "startSec": parse_mmss_to_sec(start),
                "endSec": parse_mmss_to_sec(end),
                "speaker": (speaker or "익명1").strip(),
                "text": (body or "").strip(),
            })
        else:
            prev = out[-1]["endSec"] if out else 0
            out.append({
                "start": seconds_to_mmss(prev),
                "end": seconds_to_mmss(prev + 5),
                "startSec": prev,
                "endSec": prev + 5,
                "speaker": "익명1",
                "text": line,
            })
    return out


def transcribe_audio_file_for_upload(file_path: str, model_name: str = "medium", language: str = "ko"):
    import os
    import tempfile

    model = get_whisper_model(model_name or "medium")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        wav_path = tmp.name

    try:
        ffmpeg_to_wav(file_path, wav_path)

        segments, _ = model.transcribe(
            wav_path,
            language=None if language == "auto" else language,
            vad_filter=True,
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=True,
        )

        lines = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue

            start = float(seg.start)
            end = float(seg.end)
            if end <= start:
                end = start + 1

            lines.append(
                f"[{seconds_to_mmss(start)}~{seconds_to_mmss(end)}] 익명1: {text}"
            )

        return "\n".join(lines)
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass


def build_simple_report(session_id: str, transcript: str):
    lines = extract_transcript_lines(transcript)
    total_sec = max([x["endSec"] for x in lines], default=0)

    system_prompt = """
너는 회의 STT를 분석해서 회의 후 분석 화면에 쓸 주제 블록을 만드는 AI다.
반드시 JSON만 출력한다.
topic은 키워드 나열이 아니라 한 문장형 주제명으로 작성한다.
고정 2분 단위로 자르지 말고 의미 전환 기준으로 5~12개 블록을 만든다.
""".strip()

    user_prompt = f"""
다음 형식의 JSON만 출력해.

{{
  "topicBlocks": [
    {{
      "id": "topic_1",
      "topic": "한 문장형 주제명",
      "startSec": 0,
      "endSec": 120,
      "keywords": ["키워드1", "키워드2"],
      "summary": "2~3문장 요약",
      "text": "해당 구간 핵심 내용"
    }}
  ],
  "minutesMarkdown": "# 회의록 정리 ...",
  "mindmapText": "[00:00~01:00] 주제 - [01:00~03:00] 주제"
}}

[STT]
{transcript[-24000:]}
""".strip()

    raw = ""
    try:
        raw = call_ollama_simple(system_prompt, user_prompt, model="qwen2.5:3b")
        start = raw.find("{")
        end = raw.rfind("}")
        parsed = json.loads(raw[start:end + 1])
    except Exception:
        # fallback: 전체를 하나의 블록으로
        parsed = {
            "topicBlocks": [{
                "id": "topic_1",
                "topic": "회의 전체 논의 요약",
                "startSec": 0,
                "endSec": total_sec or 1,
                "keywords": [],
                "summary": transcript[:700],
                "text": transcript,
            }],
            "minutesMarkdown": "# 회의록 정리\n\n" + transcript,
            "mindmapText": "[00:00~{}] 회의 전체 논의 요약".format(seconds_to_mmss(total_sec)),
        }

    blocks = []
    for i, b in enumerate(parsed.get("topicBlocks", [])):
        start_sec = int(b.get("startSec", 0))
        end_sec = int(b.get("endSec", start_sec + 1))
        if end_sec <= start_sec:
            end_sec = start_sec + 1
        blocks.append({
            "id": b.get("id") or f"topic_{i+1}",
            "topic": b.get("topic") or "회의 주제 논의",
            "startSec": start_sec,
            "endSec": end_sec,
            "start": seconds_to_mmss(start_sec),
            "end": seconds_to_mmss(end_sec),
            "durationSec": end_sec - start_sec,
            "keywords": b.get("keywords") or [],
            "summary": b.get("summary") or "",
            "text": b.get("text") or "",
        })

    if not blocks:
        blocks = [{
            "id": "topic_1",
            "topic": "회의 전체 논의 요약",
            "startSec": 0,
            "endSec": total_sec or 1,
            "start": "00:00",
            "end": seconds_to_mmss(total_sec or 1),
            "durationSec": total_sec or 1,
            "keywords": [],
            "summary": transcript[:700],
            "text": transcript,
        }]

    total_sec = max([b["endSec"] for b in blocks], default=total_sec)

    return {
        "session": {"id": session_id, "sessionId": session_id, "title": "회의 분석"},
        "totalSec": total_sec or 1,
        "transcriptLines": lines,
        "topicBlocks": blocks,
        "aiEvents": [],
        "minutesMarkdown": parsed.get("minutesMarkdown") or "# 회의록 정리\n\n" + transcript,
        "mindmapText": parsed.get("mindmapText") or " - ".join([f"[{b['start']}~{b['end']}] {b['topic']}" for b in blocks]),
        "analysisMode": "SLM_FULL_TRANSCRIPT_ANALYSIS",
    }


def save_report_cache(session_id: str, report: dict):
    ensure_tables()
    now = datetime.now().isoformat()
    c = conn()
    c.execute("""
    INSERT INTO meeting_report_cache
    (session_id, report_json, created_at, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(session_id) DO UPDATE SET
      report_json = excluded.report_json,
      updated_at = excluded.updated_at
    """, (session_id, json.dumps(report, ensure_ascii=False), now, now))
    c.commit()
    c.close()


def load_report_cache(session_id: str):
    ensure_tables()
    c = conn()
    row = c.execute("SELECT report_json FROM meeting_report_cache WHERE session_id = ?", (session_id,)).fetchone()
    c.close()
    if not row:
        return None
    try:
        return json.loads(row["report_json"])
    except Exception:
        return None


@router.post("/meeting-report/upload-audio")
async def upload_audio_for_meeting_report(
    file: UploadFile = File(...),
    stt_model: str = Form("medium"),
    language: str = Form("ko"),
):
    ensure_tables()

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 음성/영상 형식입니다: {ext}")

    # 새 세션 생성
    payload = MeetingCreatePayload(
        title=f"음성 {Path(file.filename).stem} ({stt_model})",
        meetingType="uploaded_audio",
        meetingTime=datetime.now().isoformat(),
        keywords="uploaded audio, STT, meeting report",
    )
    session = create_meeting_session(payload)
    session_id = session["sessionId"]

    target_dir = DATA_DIR / "sessions" / session_id / "post_meeting_recordings"
    target_dir.mkdir(parents=True, exist_ok=True)

    path = target_dir / file.filename
    content = await file.read()
    path.write_bytes(content)

    transcript = transcribe_audio_file_for_upload(str(path), stt_model, language)

    save_library_item(
        session_id=session_id,
        bucket="post_meeting_recordings",
        kind=f"uploaded_audio_transcript_{stt_model}",
        name=file.filename,
        file_path=str(path),
        text_content=transcript,
    )

    report = build_simple_report(session_id, transcript)
    report["session"]["title"] = f"음성 {Path(file.filename).stem} ({stt_model})"
    report["sttModel"] = stt_model
    report["language"] = language
    save_report_cache(session_id, report)

    return {
        "sessionId": session_id,
        "filename": file.filename,
        "sttModel": stt_model,
        "language": language,
        "transcriptPreview": transcript[:1000],
        "report": report,
    }


@router.get("/meeting-report/{session_id}/transcript")
def get_meeting_report_transcript(session_id: str):
    transcript = read_session_transcript(session_id)
    return {
        "sessionId": session_id,
        "transcriptText": transcript,
        "transcriptLines": extract_transcript_lines(transcript),
        "diarizationStatus": "not_applied",
        "diarizationNote": "현재는 STT segment 기준 익명1로 저장합니다. 화자분리는 pyannote diarization 추가가 필요합니다.",
    }


@router.get("/meeting-report/{session_id}")
def get_meeting_report(session_id: str):
    cached = load_report_cache(session_id)
    if cached:
        return cached

    transcript = read_session_transcript(session_id)
    report = build_simple_report(session_id, transcript)
    save_report_cache(session_id, report)
    return report


@router.post("/meeting-report/{session_id}/regenerate")
def regenerate_meeting_report(session_id: str):
    transcript = read_session_transcript(session_id)
    report = build_simple_report(session_id, transcript)
    save_report_cache(session_id, report)
    return report
