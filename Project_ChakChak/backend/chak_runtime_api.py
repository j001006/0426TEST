import os
import re
import sys
import sqlite3
import subprocess
import tempfile
import uuid
import wave
import contextlib
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import requests
import webrtcvad
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from faster_whisper import WhisperModel

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "meeting_app.sqlite3"

GENERAL_SLM_MODEL = os.environ.get("GENERAL_SLM_MODEL", "qwen2.5:3b")
REALTIME_SLM_MODEL = os.environ.get("REALTIME_SLM_MODEL", "qwen2.5:3b")
WHISPER_REALTIME_MODEL_NAME = os.environ.get("WHISPER_REALTIME_MODEL_NAME", "base")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

WEB_SEARCH_PROVIDER = os.environ.get("WEB_SEARCH_PROVIDER", "serpapi").lower()
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
SERPAPI_ENGINE = os.environ.get("SERPAPI_ENGINE", "google")
SERPAPI_GL = os.environ.get("SERPAPI_GL", "kr")
SERPAPI_HL = os.environ.get("SERPAPI_HL", "ko")
SERPAPI_LOCATION = os.environ.get("SERPAPI_LOCATION", "South Korea")

_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        _whisper_model = WhisperModel(
            WHISPER_REALTIME_MODEL_NAME,
            device="cuda",
            compute_type="float16",
        )
    except Exception:
        _whisper_model = WhisperModel(
            WHISPER_REALTIME_MODEL_NAME,
            device="cpu",
            compute_type="int8",
        )
    return _whisper_model


class MeetingSessionCreate(BaseModel):
    title: str
    meetingTime: str
    keywords: str = ""
    meetingType: str = "brainstorming"
    realtimeRecordingEnabled: bool = True


class AIChatRequest(BaseModel):
    text: str
    meetingText: str = ""
    mode: str = "general"
    meta: dict = {}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_sessions (
        id TEXT PRIMARY KEY,
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
    CREATE TABLE IF NOT EXISTS rag_chunks (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        scope TEXT NOT NULL,
        source_item_id TEXT,
        source_name TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        token_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()


def session_dir(session_id: str) -> Path:
    base = DATA_DIR / "sessions" / session_id
    (base / "live_recordings").mkdir(parents=True, exist_ok=True)
    (base / "post_meeting_recordings").mkdir(parents=True, exist_ok=True)
    (base / "meeting_plan").mkdir(parents=True, exist_ok=True)
    (base / "knowledge").mkdir(parents=True, exist_ok=True)
    return base


def global_library_dir() -> Path:
    base = DATA_DIR / "global_library"
    base.mkdir(parents=True, exist_ok=True)
    return base


def guess_kind_from_name(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".txt"):
        return "txt"
    if lowered.endswith(".docx"):
        return "docx"
    if lowered.endswith(".hwp"):
        return "hwp"
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".wav") or lowered.endswith(".mp3") or lowered.endswith(".m4a") or lowered.endswith(".webm"):
        return "audio"
    return "file"


def insert_library_item(
    session_id: Optional[str],
    scope: str,
    bucket: str,
    kind: str,
    name: str,
    file_path: str,
    text_content: Optional[str],
    preview_line: Optional[str],
):
    conn = get_conn()
    cur = conn.cursor()
    item_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO library_items
        (id, session_id, scope, bucket, kind, name, file_path, text_content, preview_line, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id,
        session_id,
        scope,
        bucket,
        kind,
        name,
        file_path,
        text_content,
        preview_line,
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()
    return item_id


def read_text_safely(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def ffmpeg_to_wav_16k_mono(src_path: str, dst_path: str):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", src_path,
        "-ac", "1",
        "-ar", "16000",
        dst_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def transcribe_audio_file(file_path: str) -> str:
    model = get_whisper_model()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
        wav_path = tmp_wav.name

    try:
        ffmpeg_to_wav_16k_mono(file_path, wav_path)
        segments, _ = model.transcribe(wav_path, vad_filter=False)

        lines = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            start_sec = int(seg.start)
            end_sec = int(seg.end)
            mm1, ss1 = divmod(start_sec, 60)
            mm2, ss2 = divmod(end_sec, 60)
            lines.append(f"[{mm1:02d}:{ss1:02d}~{mm2:02d}:{ss2:02d}] 익명1: {text}")

        return "\n".join(lines)
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass


def vad_total_silence_seconds(wav_path: str) -> float:
    vad = webrtcvad.Vad(2)

    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()

        if channels != 1 or sample_width != 2 or sample_rate not in (8000, 16000, 32000, 48000):
            return 0.0

        audio = wf.readframes(n_frames)

    frame_ms = 30
    frame_bytes = int(sample_rate * (frame_ms / 1000.0) * sample_width)

    total_silence = 0.0
    cursor = 0
    while cursor + frame_bytes <= len(audio):
        frame = audio[cursor:cursor + frame_bytes]
        is_speech = vad.is_speech(frame, sample_rate)
        if not is_speech:
            total_silence += frame_ms / 1000.0
        cursor += frame_bytes

    return round(total_silence, 2)


def extract_text_for_knowledge(file_path: Path) -> Optional[str]:
    kind = guess_kind_from_name(file_path.name)
    if kind in {"txt", "json"}:
        return read_text_safely(file_path)
    return None


def summarize_stub_from_text(text: str, max_len: int = 220) -> str:
    if not text:
        return ""
    return text.strip().replace("\n", " ")[:max_len]


def tokenize_korean_english(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[가-힣A-Za-z0-9_]+", text.lower())


def split_text_into_chunks(text: str, chunk_size: int = 700, overlap: int = 120) -> List[str]:
    if not text:
        return []

    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(text_len, start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == text_len:
            break
        start = max(0, end - overlap)

    return chunks


def rebuild_chunks_for_item(
    session_id: Optional[str],
    scope: str,
    source_item_id: str,
    source_name: str,
    text_content: Optional[str],
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM rag_chunks WHERE source_item_id = ?", (source_item_id,))

    if not text_content or not text_content.strip():
        conn.commit()
        conn.close()
        return

    chunks = split_text_into_chunks(text_content)
    now = datetime.now().isoformat()

    for idx, chunk_text in enumerate(chunks):
        cur.execute("""
            INSERT INTO rag_chunks
            (id, session_id, scope, source_item_id, source_name, chunk_index, chunk_text, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            session_id,
            scope,
            source_item_id,
            source_name,
            idx,
            chunk_text,
            len(tokenize_korean_english(chunk_text)),
            now,
        ))

    conn.commit()
    conn.close()


def bm25_like_score(query_tokens: List[str], chunk_text: str) -> float:
    if not query_tokens or not chunk_text:
        return 0.0

    chunk_tokens = tokenize_korean_english(chunk_text)
    if not chunk_tokens:
        return 0.0

    counter = Counter(chunk_tokens)
    score = 0.0
    chunk_len = len(chunk_tokens)

    for token in query_tokens:
        tf = counter.get(token, 0)
        if tf == 0:
            continue
        score += (tf / (1.0 + chunk_len * 0.01)) * 10.0

    if any(token in chunk_text.lower() for token in query_tokens):
        score += 1.0

    return score


def retrieve_rag_chunks(session_id: str, query: str, top_k: int = 5) -> List[dict]:
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT id, scope, source_name, chunk_index, chunk_text
        FROM rag_chunks
        WHERE session_id = ? OR scope = 'global'
    """, (session_id,)).fetchall()
    conn.close()

    query_tokens = tokenize_korean_english(query)
    scored = []

    for row in rows:
        score = bm25_like_score(query_tokens, row["chunk_text"])
        if score > 0:
            scored.append({
                "id": row["id"],
                "scope": row["scope"],
                "source_name": row["source_name"],
                "chunk_index": row["chunk_index"],
                "chunk_text": row["chunk_text"],
                "score": score,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def build_rag_context_text(session_id: str, query: str, top_k: int = 5) -> str:
    chunks = retrieve_rag_chunks(session_id, query, top_k=top_k)
    if not chunks:
        return ""

    parts = []
    for chunk in chunks:
        parts.append(
            f"[source={chunk['source_name']} chunk={chunk['chunk_index']} score={chunk['score']:.2f}]\n{chunk['chunk_text']}"
        )
    return "\n\n".join(parts)


def get_meeting_session(session_id: str):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM meeting_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return row


def build_meeting_summary_text(session_id: str):
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT preview_line
        FROM library_items
        WHERE session_id = ? AND bucket = 'live_recordings'
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()
    conn.close()
    return "\n".join([r["preview_line"] for r in rows if r["preview_line"]])


def call_ollama_chat(model_name: str, system_prompt: str, user_prompt: str) -> str:
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model_name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("AI 응답이 비어 있습니다.")
        return content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {str(e)}")


def maybe_web_search(query: str, use_web: bool) -> str:
    if not use_web:
        return ""

    if WEB_SEARCH_PROVIDER != "serpapi":
        return ""

    if not SERPAPI_API_KEY:
        return ""

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": SERPAPI_ENGINE,
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "hl": SERPAPI_HL,
                "gl": SERPAPI_GL,
                "location": SERPAPI_LOCATION,
                "num": 5,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        parts = []

        answer_box = data.get("answer_box") or {}
        if isinstance(answer_box, dict):
            for key in ["title", "answer", "snippet", "result"]:
                value = answer_box.get(key)
                if value:
                    parts.append(f"[answer_box:{key}] {value}")

        knowledge_graph = data.get("knowledge_graph") or {}
        if isinstance(knowledge_graph, dict):
            kg_title = knowledge_graph.get("title")
            if kg_title:
                parts.append(f"[knowledge_graph:title] {kg_title}")
            for key in ["description", "type"]:
                value = knowledge_graph.get(key)
                if value:
                    parts.append(f"[knowledge_graph:{key}] {value}")
            for attr_key, attr_val in (knowledge_graph.get("attributes") or {}).items():
                parts.append(f"[knowledge_graph:attribute] {attr_key}: {attr_val}")

        organic_results = data.get("organic_results") or []
        for item in organic_results[:5]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            source = item.get("source", "")
            block = f"[organic] title={title} source={source} link={link} snippet={snippet}".strip()
            parts.append(block)

        related_questions = data.get("related_questions") or []
        for item in related_questions[:3]:
            question = item.get("question", "")
            snippet = item.get("snippet", "")
            if question or snippet:
                parts.append(f"[related_question] {question} {snippet}".strip())

        return "\n".join([p for p in parts if p]).strip()
    except Exception:
        return ""


@app.get("/")
def root():
    return {
        "message": "meeting backend running",
        "general_slm_model": GENERAL_SLM_MODEL,
        "realtime_slm_model": REALTIME_SLM_MODEL,
        "whisper_realtime_model": WHISPER_REALTIME_MODEL_NAME,
        "ollama_base_url": OLLAMA_BASE_URL,
        "web_search_provider": WEB_SEARCH_PROVIDER,
        "serpapi_engine": SERPAPI_ENGINE,
        "serpapi_gl": SERPAPI_GL,
        "serpapi_hl": SERPAPI_HL,
        "serpapi_location": SERPAPI_LOCATION,
        "has_serpapi_key": bool(SERPAPI_API_KEY),
    }


@app.post("/ai/chat")
def ai_chat(req: AIChatRequest):
    mode = req.mode or "general"
    model_name = GENERAL_SLM_MODEL if mode == "general" else REALTIME_SLM_MODEL

    session_id = None
    use_web = False
    if isinstance(req.meta, dict):
        session_id = req.meta.get("sessionId")
        use_web = bool(req.meta.get("useWeb", False))

    rag_text = ""
    if session_id:
        try:
            rag_text = build_rag_context_text(session_id, req.text, top_k=5)
        except Exception:
            rag_text = ""

    web_text = maybe_web_search(req.text, use_web)

    system_prompt = """
너는 회의 보조 AI다.

매우 중요한 규칙:
1. 한국어로만 답변해라.
2. 회의 기록, 업로드 문서, RAG 검색 문맥, 웹검색 문맥에 근거해서만 답해라.
3. 근거가 부족하면 절대 추측하지 마라.
4. useWeb=false 인 경우:
   - 외부 지식이 필요한 질문에는 모른다고 답해라.
5. useWeb=true 인 경우:
   - 웹검색 결과가 있으면 그 내용을 우선 근거로 사용해라.
6. 답할 근거가 부족하면 반드시 아래 문장으로 시작해라:
   "현재 업로드된 문서/회의 기록/RAG 검색 결과만으로는 확인할 수 없습니다."
7. 사실을 지어내지 마라.
8. 웹검색 결과와 회의/RAG 결과가 충돌하면, 웹검색 결과를 우선하되
   "웹검색 기준"이라고 짧게 밝혀라.
""".strip()

    user_prompt = f"""
[사용자 질문]
{req.text}

[회의 기록 참고]
{req.meetingText or '(회의 기록 없음)'}

[RAG 검색 문맥]
{rag_text or '(검색 결과 없음)'}

[웹검색 문맥]
{web_text or '(검색 결과 없음)'}

[웹검색 사용]
{use_web}

[부가 정보]
{req.meta if req.meta else '(없음)'}
""".strip()

    content = call_ollama_chat(model_name, system_prompt, user_prompt)

    return {
        "text": content,
        "model": model_name,
        "mode": mode,
        "ragContext": rag_text,
        "webContext": web_text,
    }


@app.post("/meeting/session/create")
def create_meeting_session(payload: MeetingSessionCreate):
    _runtime_ensure_tables()
    session_id = str(uuid.uuid4())

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO meeting_sessions
        (id, title, meeting_time, keywords, meeting_type, realtime_recording_enabled, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        payload.title,
        payload.meetingTime,
        payload.keywords,
        payload.meetingType,
        1 if payload.realtimeRecordingEnabled else 0,
        datetime.now().isoformat(),
        "live",
    ))
    conn.commit()
    conn.close()

    session_dir(session_id)

    return {
        "sessionId": session_id,
        "title": payload.title,
    }


@app.post("/meeting/session/{session_id}/plan")
async def upload_meeting_plan(session_id: str, file: UploadFile = File(...)):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    base = session_dir(session_id) / "meeting_plan"
    destination = base / file.filename

    with open(destination, "wb") as f:
        f.write(await file.read())

    text_content = extract_text_for_knowledge(destination)
    preview_line = summarize_stub_from_text(text_content) or file.filename

    item_id = insert_library_item(
        session_id=session_id,
        scope="session",
        bucket="meeting_plan",
        kind=guess_kind_from_name(file.filename),
        name=file.filename,
        file_path=str(destination),
        text_content=text_content,
        preview_line=preview_line,
    )

    rebuild_chunks_for_item(
        session_id=session_id,
        scope="session",
        source_item_id=item_id,
        source_name=file.filename,
        text_content=text_content,
    )

    return {"itemId": item_id, "name": file.filename}


@app.post("/meeting/session/{session_id}/knowledge")
async def upload_session_knowledge(session_id: str, file: UploadFile = File(...)):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    base = session_dir(session_id) / "knowledge"
    destination = base / file.filename

    with open(destination, "wb") as f:
        f.write(await file.read())

    text_content = extract_text_for_knowledge(destination)
    preview_line = summarize_stub_from_text(text_content) or file.filename

    item_id = insert_library_item(
        session_id=session_id,
        scope="session",
        bucket="knowledge",
        kind=guess_kind_from_name(file.filename),
        name=file.filename,
        file_path=str(destination),
        text_content=text_content,
        preview_line=preview_line,
    )

    rebuild_chunks_for_item(
        session_id=session_id,
        scope="session",
        source_item_id=item_id,
        source_name=file.filename,
        text_content=text_content,
    )

    return {"itemId": item_id, "name": file.filename}


@app.post("/library/global/upload")
async def upload_global_knowledge(file: UploadFile = File(...)):
    base = global_library_dir()
    destination = base / file.filename

    with open(destination, "wb") as f:
        f.write(await file.read())

    text_content = extract_text_for_knowledge(destination)
    preview_line = summarize_stub_from_text(text_content) or file.filename

    item_id = insert_library_item(
        session_id=None,
        scope="global",
        bucket="uploaded_knowledge",
        kind=guess_kind_from_name(file.filename),
        name=file.filename,
        file_path=str(destination),
        text_content=text_content,
        preview_line=preview_line,
    )

    rebuild_chunks_for_item(
        session_id=None,
        scope="global",
        source_item_id=item_id,
        source_name=file.filename,
        text_content=text_content,
    )

    return {"itemId": item_id, "name": file.filename}


@app.post("/meeting/session/{session_id}/realtime-chunk")
async def upload_realtime_chunk_endpoint(
    session_id: str,
    file: UploadFile = File(...),
    offset_sec: float = Form(0),
):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    base = session_dir(session_id) / "live_recordings"
    raw_destination = base / file.filename

    with open(raw_destination, "wb") as f:
        f.write(await file.read())

    transcript = ""
    silence_seconds = 0.0

    try:
        transcript = transcribe_audio_file(str(raw_destination))
    except Exception as e:
        transcript = f"[오류] STT 변환 실패: {str(e)}"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
            wav_path = tmp_wav.name
        ffmpeg_to_wav_16k_mono(str(raw_destination), wav_path)
        silence_seconds = vad_total_silence_seconds(wav_path)
        try:
            os.remove(wav_path)
        except Exception:
            pass
    except Exception:
        silence_seconds = 0.0

    preview = transcript.splitlines()[0] if transcript else file.filename
    if silence_seconds > 0:
        preview = f"{preview} / 무음 {silence_seconds:.1f}s"

    item_id = insert_library_item(
        session_id=session_id,
        scope="session",
        bucket="live_recordings",
        kind="realtime_chunk",
        name=file.filename,
        file_path=str(raw_destination),
        text_content=transcript,
        preview_line=preview,
    )

    rebuild_chunks_for_item(
        session_id=session_id,
        scope="session",
        source_item_id=item_id,
        source_name=file.filename,
        text_content=transcript,
    )

    return {
        "itemId": item_id,
        "previewLine": preview,
        "offsetSec": offset_sec,
        "silenceSeconds": silence_seconds,
    }


@app.post("/meeting/session/{session_id}/stop")
def stop_meeting_session(session_id: str):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE meeting_sessions
        SET status = 'stopped', stopped_at = ?
        WHERE id = ?
    """, (datetime.now().isoformat(), session_id))
    conn.commit()

    live_rows = cur.execute("""
        SELECT * FROM library_items
        WHERE session_id = ? AND bucket = 'live_recordings'
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()

    final_text = "\n".join([r["text_content"] or r["preview_line"] or "" for r in live_rows]).strip()
    if not final_text:
        final_text = "회의 종료 후 정리된 최종 기록이 아직 없습니다."

    preview_line = final_text.splitlines()[0][:220]

    item_id = insert_library_item(
        session_id=session_id,
        scope="session",
        bucket="post_meeting_recordings",
        kind="meeting_final_transcript",
        name=f"{session['title']}_final_transcript.txt",
        file_path="generated://final_transcript",
        text_content=final_text,
        preview_line=preview_line,
    )

    rebuild_chunks_for_item(
        session_id=session_id,
        scope="session",
        source_item_id=item_id,
        source_name=f"{session['title']}_final_transcript.txt",
        text_content=final_text,
    )

    conn.close()

    return {"status": "stopped", "sessionId": session_id}


@app.get("/meeting/session/{session_id}")
def get_meeting_detail_endpoint(session_id: str):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    conn = get_conn()
    cur = conn.cursor()
    live_rows = cur.execute("""
        SELECT id, kind, name, preview_line, created_at
        FROM library_items
        WHERE session_id = ? AND bucket = 'live_recordings'
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()
    conn.close()

    live_items = []
    for row in live_rows:
        live_items.append({
            "id": row["id"],
            "kind": row["kind"],
            "kindLabel": "실시간 STT 기록",
            "name": row["name"],
            "previewLine": row["preview_line"] or row["name"],
            "createdAt": row["created_at"],
        })

    return {
        "sessionId": session["id"],
        "title": session["title"],
        "meetingTime": session["meeting_time"],
        "keywords": session["keywords"],
        "meetingType": session["meeting_type"],
        "status": session["status"],
        "liveTranscriptItems": live_items,
    }


@app.get("/meeting/session/{session_id}/library-tree")
def get_meeting_library_tree(session_id: str):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    conn = get_conn()
    cur = conn.cursor()

    plan_rows = cur.execute("""
        SELECT id, name, kind, preview_line, created_at
        FROM library_items
        WHERE session_id = ? AND bucket = 'meeting_plan'
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()

    knowledge_rows = cur.execute("""
        SELECT id, name, kind, preview_line, created_at
        FROM library_items
        WHERE session_id = ? AND bucket = 'knowledge'
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()

    after_rows = cur.execute("""
        SELECT id, name, kind, preview_line, created_at
        FROM library_items
        WHERE session_id = ? AND bucket = 'post_meeting_recordings'
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()

    conn.close()

    meeting_plan_items = [{
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "kindLabel": "계획서",
        "previewLine": row["preview_line"] or row["name"],
        "createdAt": row["created_at"],
    } for row in plan_rows]

    knowledge_items = [{
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "kindLabel": "관련 자료",
        "previewLine": row["preview_line"] or row["name"],
        "createdAt": row["created_at"],
    } for row in knowledge_rows]

    after_meeting_items = [{
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "kindLabel": "회의 종료 후 정리본",
        "previewLine": row["preview_line"] or row["name"],
        "createdAt": row["created_at"],
    } for row in after_rows]

    return {
        "meetingPlanItems": meeting_plan_items,
        "knowledgeItems": knowledge_items,
        "afterMeetingRecordings": after_meeting_items,
    }


@app.get("/library/global/tree")
def get_global_library_tree():
    conn = get_conn()
    cur = conn.cursor()

    realtime_sessions = cur.execute("""
        SELECT id, title, created_at
        FROM meeting_sessions
        WHERE realtime_recording_enabled = 1
        ORDER BY created_at DESC
    """).fetchall()

    post_rows = cur.execute("""
        SELECT id, session_id, name, created_at
        FROM library_items
        WHERE bucket = 'post_meeting_recordings'
        ORDER BY created_at DESC
    """).fetchall()

    knowledge_rows = cur.execute("""
        SELECT id, name, kind, created_at
        FROM library_items
        WHERE scope = 'global'
        ORDER BY created_at DESC
    """).fetchall()

    conn.close()

    return {
        "realtimeMeetings": [
            {
                "id": row["id"],
                "title": row["title"],
                "createdAt": row["created_at"],
            }
            for row in realtime_sessions
        ],
        "postMeetingRecordings": [
            {
                "id": row["id"],
                "title": row["name"],
                "createdAt": row["created_at"],
            }
            for row in post_rows
        ],
        "uploadedKnowledge": [
            {
                "id": row["id"],
                "name": row["name"],
                "kindLabel": row["kind"],
                "createdAt": row["created_at"],
            }
            for row in knowledge_rows
        ],
    }


@app.get("/meeting/session/{session_id}/rag-search")
def rag_search(session_id: str, query: str):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    chunks = retrieve_rag_chunks(session_id, query, top_k=5)
    return {"results": chunks}


@app.post("/meeting/session/{session_id}/mid-summary")
def get_mid_summary(session_id: str):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    transcript_text = build_meeting_summary_text(session_id)
    query = f"{session['meeting_type']} {session['title']} {session['keywords']} 중간 요약 결정 쟁점 계획서"
    rag_text = build_rag_context_text(session_id, query, top_k=5)

    system_prompt = """
너는 실시간 회의 요약 보조 AI다.
회의 종류, 키워드, 계획서, 실시간 회의 기록, RAG 검색 문맥을 함께 참고하여
1) 지금까지 논의 핵심
2) 결정된 것
3) 아직 남은 쟁점
4) 다음 액션
을 한국어로 간결하게 정리해라.
없는 사실은 추정하지 마라.
한국어로만 답해라.
""".strip()

    user_prompt = f"""
[회의 종류]
{session['meeting_type']}

[회의 제목]
{session['title']}

[회의 키워드]
{session['keywords']}

[실시간 회의 기록]
{transcript_text or '(없음)'}

[RAG 참고 문맥]
{rag_text or '(없음)'}
""".strip()

    try:
        summary = call_ollama_chat(REALTIME_SLM_MODEL, system_prompt, user_prompt)
    except HTTPException:
        summary = f"""[회의 종류] {session['meeting_type']}
[회의 제목] {session['title']}

1. 지금까지 논의된 핵심
- {transcript_text[:300] if transcript_text else '아직 충분한 회의 기록이 없습니다.'}

2. RAG 참고 문맥
- {rag_text[:500] if rag_text else '검색된 참고 문서가 없습니다.'}

3. 다음 액션
- 지금까지 나온 쟁점을 기준으로 우선순위를 다시 정리해 보세요.
"""

    item_id = insert_library_item(
        session_id=session_id,
        scope="session",
        bucket="live_recordings",
        kind="mid_summary",
        name=f"{session['title']}_mid_summary.txt",
        file_path="generated://mid_summary",
        text_content=summary,
        preview_line=summary.splitlines()[0] if summary else "mid_summary",
    )

    rebuild_chunks_for_item(
        session_id=session_id,
        scope="session",
        source_item_id=item_id,
        source_name=f"{session['title']}_mid_summary.txt",
        text_content=summary,
    )

    return {"summary": summary, "ragContext": rag_text}


@app.post("/meeting/session/{session_id}/feedback")
def get_feedback(session_id: str):
    session = get_meeting_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    transcript_text = build_meeting_summary_text(session_id)
    query = f"{session['meeting_type']} {session['title']} {session['keywords']} 피드백 정체 문제 계획서"
    rag_text = build_rag_context_text(session_id, query, top_k=5)

    system_prompt = """
너는 실시간 회의 피드백 AI다.
회의가 목표에서 벗어났는지, 반복되는 논점이 있는지, 누락된 관점이 있는지 판단하고,
바로 이어서 던질 질문이나 다음 스텝을 제안해라.
출력은 한국어로 하고,
1) 현재 문제
2) 이유
3) 제안 질문 / 행동
순서로 써라.
없는 사실은 추정하지 마라.
한국어로만 답해라.
""".strip()

    user_prompt = f"""
[회의 종류]
{session['meeting_type']}

[회의 제목]
{session['title']}

[회의 키워드]
{session['keywords']}

[실시간 회의 기록]
{transcript_text or '(없음)'}

[RAG 참고 문맥]
{rag_text or '(없음)'}
""".strip()

    try:
        feedback = call_ollama_chat(REALTIME_SLM_MODEL, system_prompt, user_prompt)
    except HTTPException:
        feedback = f"""[회의 피드백]
- 회의 종류: {session['meeting_type']}
- 회의 제목: {session['title']}

현재 문제
- 논의가 길어질 경우 목표 대비 결정 포인트가 흐려질 수 있습니다.

이유
- 실시간 회의 기록: {transcript_text[:220] if transcript_text else '기록 부족'}
- RAG 참고 문맥: {rag_text[:350] if rag_text else '문서 부족'}

제안 질문 / 행동
- 지금 가장 먼저 확정해야 하는 한 가지를 정해보세요.
- 계획서 기준에서 벗어난 항목이 있는지 다시 확인해보세요.
"""

    item_id = insert_library_item(
        session_id=session_id,
        scope="session",
        bucket="live_recordings",
        kind="meeting_feedback",
        name=f"{session['title']}_feedback.txt",
        file_path="generated://feedback",
        text_content=feedback,
        preview_line=feedback.splitlines()[0] if feedback else "feedback",
    )

    rebuild_chunks_for_item(
        session_id=session_id,
        scope="session",
        source_item_id=item_id,
        source_name=f"{session['title']}_feedback.txt",
        text_content=feedback,
    )

    return {"feedback": feedback, "ragContext": rag_text}

# ============================================================
# Stable realtime meeting API override
# - Fixes realtime-chunk 500
# - Fixes stop 500
# - Fixes mid-summary/feedback failure path
# ============================================================

from fastapi import Form
import uuid as _uuid
from pathlib import Path as _Path
from datetime import datetime as _datetime
import sqlite3 as _sqlite3
import subprocess as _subprocess
import os as _os
import tempfile as _tempfile

_RUNTIME_BASE_DIR = _Path(__file__).resolve().parent
_RUNTIME_DATA_DIR = _RUNTIME_BASE_DIR / "data"
_RUNTIME_DB_PATH = _RUNTIME_DATA_DIR / "meeting_app.sqlite3"


def _runtime_conn():
    _RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _sqlite3.connect(_RUNTIME_DB_PATH)
    conn.row_factory = _sqlite3.Row
    return conn


def _runtime_ensure_tables():
    conn = _runtime_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_sessions (
        id TEXT PRIMARY KEY,
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

    conn.commit()
    conn.close()


def _runtime_get_session(session_id: str):
    _runtime_ensure_tables()
    conn = _runtime_conn()
    row = conn.execute(
        "SELECT * FROM meeting_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    return row


def _runtime_insert_library_item(
    session_id: str,
    bucket: str,
    kind: str,
    name: str,
    file_path: str,
    text_content: str,
):
    _runtime_ensure_tables()
    item_id = str(_uuid.uuid4())
    preview = ""
    if text_content:
        preview = text_content.splitlines()[0][:220]

    conn = _runtime_conn()
    conn.execute("""
        INSERT INTO library_items
        (id, session_id, scope, bucket, kind, name, file_path, text_content, preview_line, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id,
        session_id,
        "session",
        bucket,
        kind,
        name,
        file_path,
        text_content or "",
        preview,
        _datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()

    return {
        "id": item_id,
        "sessionId": session_id,
        "bucket": bucket,
        "kind": kind,
        "name": name,
        "filePath": file_path,
        "textContent": text_content or "",
        "previewLine": preview,
    }


def _runtime_read_session_transcript(session_id: str) -> str:
    _runtime_ensure_tables()
    conn = _runtime_conn()
    rows = conn.execute("""
        SELECT text_content, preview_line
        FROM library_items
        WHERE session_id = ?
          AND bucket IN ('live_recordings', 'post_meeting_recordings')
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()
    conn.close()

    texts = []
    for row in rows:
        t = row["text_content"] or row["preview_line"] or ""
        if t.strip():
            texts.append(t.strip())
    return "\n".join(texts)


def _runtime_format_sec(sec: float) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _runtime_ffmpeg_to_wav(src: str, dst: str):
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-ac",
        "1",
        "-ar",
        "16000",
        "-vn",
        dst,
    ]
    result = _subprocess.run(
        cmd,
        stdout=_subprocess.PIPE,
        stderr=_subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:])


def _runtime_transcribe_chunk(file_path: str, offset_sec: float = 0.0) -> str:
    """
    실시간 chunk용 STT.
    기존 transcribe_audio_file이 segments 형식/시그니처 문제를 내도 여기서 안전하게 처리.
    """
    # 1순위: 기존 프로젝트 함수가 있으면 사용
    try:
        try:
            return transcribe_audio_file(file_path, offset_sec=offset_sec)
        except TypeError:
            raw = transcribe_audio_file(file_path)
            # 기존 함수가 이미 timestamp를 만들었다면 그대로 반환
            if raw and "[" in raw and "~" in raw:
                return raw
            return f"[{_runtime_format_sec(offset_sec)}~{_runtime_format_sec(offset_sec + 5)}] 익명1: {raw or ''}"
    except Exception:
        pass

    # 2순위: faster-whisper 직접 사용
    wav_path = None
    try:
        with _tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            wav_path = tmp.name

        _runtime_ffmpeg_to_wav(file_path, wav_path)

        model = get_whisper_model()
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
            text = (getattr(seg, "text", "") or "").strip()
            if not text:
                continue

            start = float(offset_sec) + float(getattr(seg, "start", 0.0))
            end = float(offset_sec) + float(getattr(seg, "end", 0.0))
            if end <= start:
                end = start + 1

            lines.append(
                f"[{_runtime_format_sec(start)}~{_runtime_format_sec(end)}] 익명1: {text}"
            )

        if lines:
            return "\n".join(lines)

        return f"[{_runtime_format_sec(offset_sec)}~{_runtime_format_sec(offset_sec + 1)}] 시스템: 음성 감지 없음"

    finally:
        if wav_path:
            try:
                _os.remove(wav_path)
            except Exception:
                pass


def _runtime_call_ai(system_prompt: str, user_prompt: str, model: str = None) -> str:
    model = model or globals().get("REALTIME_SLM_MODEL", "qwen2.5:3b")

    try:
        return call_ollama_chat(model, system_prompt, user_prompt)
    except TypeError:
        try:
            return call_ollama_chat({
                "model": model,
                "systemPrompt": system_prompt,
                "userPrompt": user_prompt,
            })
        except Exception as e:
            raise RuntimeError(str(e))
    except Exception as e:
        raise RuntimeError(str(e))


def _runtime_remove_routes(paths: list[str]):
    remove_set = set(paths)
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", None) not in remove_set
    ]


_runtime_remove_routes([
    "/meeting/session/{session_id}/realtime-chunk",
    "/meeting/session/{session_id}/stop",
    "/meeting/session/{session_id}/mid-summary",
    "/meeting/session/{session_id}/feedback",
])


@app.post("/meeting/session/{session_id}/realtime-chunk")
async def stable_upload_realtime_chunk(
    session_id: str,
    file: UploadFile = File(...),
    offset_sec: float = Form(0),
):
    session = _runtime_get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="회의 세션을 찾을 수 없습니다.")

    session_dir = _RUNTIME_DATA_DIR / "sessions" / session_id / "live_recordings"
    session_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"chunk_{int(float(offset_sec) * 1000)}_{file.filename or 'audio.webm'}"
    raw_path = session_dir / safe_name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="빈 audio chunk입니다.")

    raw_path.write_bytes(content)

    try:
        transcript = _runtime_transcribe_chunk(str(raw_path), offset_sec=offset_sec)
    except Exception as e:
        err = str(e)
        # MediaRecorder webm 조각이 너무 짧거나 헤더가 불완전하면 ffmpeg가 실패할 수 있음.
        # 이 경우 회의 전체를 깨지 말고 해당 chunk만 skip 처리.
        if (
            "EBML header parsing failed" in err
            or "Invalid data found when processing input" in err
            or "Error opening input" in err
            or raw_path.stat().st_size < 2048
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "invalid_or_too_short_audio_chunk",
                "detail": err[-500:],
                "sessionId": session_id,
                "offsetSec": offset_sec,
                "transcript": "",
            }

        raise HTTPException(status_code=500, detail=f"실시간 STT 변환 실패: {err}")

    item = _runtime_insert_library_item(
        session_id=session_id,
        bucket="live_recordings",
        kind="realtime_audio_chunk_transcript",
        name=safe_name,
        file_path=str(raw_path),
        text_content=transcript,
    )

    return {
        "ok": True,
        "sessionId": session_id,
        "offsetSec": offset_sec,
        "transcript": transcript,
        "item": item,
    }


@app.post("/meeting/session/{session_id}/mid-summary")
def stable_mid_summary(session_id: str):
    session = _runtime_get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="회의 세션을 찾을 수 없습니다.")

    transcript = _runtime_read_session_transcript(session_id)

    if not transcript.strip():
        return {
            "summary": "아직 누적된 STT 기록이 없습니다.",
            "sessionId": session_id,
        }

    system_prompt = """
너는 실시간 회의 중간 요약 AI다.
반드시 한국어로 간결하게 답한다.
회의 transcript에 근거해서만 요약한다.
없는 사실은 만들지 않는다.
출력 형식:
1. 지금까지 논의 핵심
2. 결정된 내용
3. 남은 쟁점
4. 다음 액션
""".strip()

    user_prompt = f"""
[회의 제목]
{session["title"]}

[회의 종류]
{session["meeting_type"]}

[키워드]
{session["keywords"]}

[누적 STT]
{transcript[-12000:]}
""".strip()

    try:
        summary = _runtime_call_ai(system_prompt, user_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"중간 요약 생성 실패: {str(e)}")

    return {
        "summary": summary,
        "sessionId": session_id,
    }


@app.post("/meeting/session/{session_id}/feedback")
def stable_feedback(session_id: str):
    session = _runtime_get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="회의 세션을 찾을 수 없습니다.")

    transcript = _runtime_read_session_transcript(session_id)

    if not transcript.strip():
        return {
            "feedback": "아직 누적된 STT 기록이 없어 피드백을 생성할 수 없습니다.",
            "sessionId": session_id,
        }

    system_prompt = """
너는 회의 진행 피드백 AI다.
회의가 목표에서 벗어났는지, 반복되는 논점이 있는지, 누락된 관점이 있는지 판단한다.
반드시 한국어로 답한다.
출력 형식:
1. 현재 문제
2. 이유
3. 바로 던질 질문
4. 다음 행동
""".strip()

    user_prompt = f"""
[회의 제목]
{session["title"]}

[회의 종류]
{session["meeting_type"]}

[키워드]
{session["keywords"]}

[누적 STT]
{transcript[-12000:]}
""".strip()

    try:
        feedback = _runtime_call_ai(system_prompt, user_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"회의 피드백 생성 실패: {str(e)}")

    return {
        "feedback": feedback,
        "sessionId": session_id,
    }


@app.post("/meeting/session/{session_id}/stop")
def stable_stop_realtime_meeting(session_id: str):
    session = _runtime_get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="회의 세션을 찾을 수 없습니다.")

    transcript = _runtime_read_session_transcript(session_id)
    now = _datetime.now().isoformat()

    conn = _runtime_conn()
    conn.execute(
        "UPDATE meeting_sessions SET status = ?, stopped_at = ? WHERE id = ?",
        ("stopped", now, session_id),
    )
    conn.commit()
    conn.close()

    final_summary = ""
    if transcript.strip():
        system_prompt = """
너는 회의 종료 후 최종 회의록을 작성하는 AI다.
반드시 한국어로 작성한다.
없는 사실은 만들지 말고 STT 기록에 근거한다.
출력 형식:
# 최종 회의록
## 핵심 요약
## 결정 사항
## 미해결 쟁점
## 다음 액션
""".strip()

        user_prompt = f"""
[회의 제목]
{session["title"]}

[회의 종류]
{session["meeting_type"]}

[키워드]
{session["keywords"]}

[전체 STT]
{transcript[-20000:]}
""".strip()

        try:
            final_summary = _runtime_call_ai(system_prompt, user_prompt)
        except Exception as e:
            final_summary = f"최종 요약 생성 실패: {str(e)}"
    else:
        final_summary = "저장된 STT 기록이 없습니다."

    summary_dir = _RUNTIME_DATA_DIR / "sessions" / session_id / "post_meeting_recordings"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / "final_summary.md"
    summary_path.write_text(final_summary, encoding="utf-8")

    _runtime_insert_library_item(
        session_id=session_id,
        bucket="post_meeting_recordings",
        kind="final_meeting_summary",
        name="final_summary.md",
        file_path=str(summary_path),
        text_content=final_summary,
    )

    return {
        "ok": True,
        "sessionId": session_id,
        "status": "stopped",
        "finalSummary": final_summary,
    }


# ============================================================
# Stable AI chat + realtime topic fallback
# ============================================================

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional

class _StableAIChatRequest(_BaseModel):
    message: str = ""
    meetingText: str = ""
    mode: str = "general"
    useWeb: bool = False
    sessionId: _Optional[str] = None
    meetingType: str = ""
    meetingTitle: str = ""
    keywords: str = ""
    purpose: str = "chat"


def _runtime_latest_transcript_text(limit_chars: int = 8000) -> str:
    _runtime_ensure_tables()
    conn = _runtime_conn()
    rows = conn.execute("""
        SELECT text_content, preview_line
        FROM library_items
        WHERE bucket IN ('live_recordings', 'post_meeting_recordings')
        ORDER BY created_at DESC
        LIMIT 30
    """).fetchall()
    conn.close()

    texts = []
    for row in reversed(rows):
        t = row["text_content"] or row["preview_line"] or ""
        if t.strip():
            texts.append(t.strip())

    return "\n".join(texts)[-limit_chars:]


@app.post("/ai/chat")
def stable_ai_chat(payload: _StableAIChatRequest):
    user_msg = payload.message.strip()
    meeting_text = (payload.meetingText or "").strip()

    if payload.sessionId and not meeting_text:
        meeting_text = _runtime_read_session_transcript(payload.sessionId)

    web_context = ""
    if payload.useWeb:
        try:
            q = f"{payload.meetingTitle} {payload.keywords} {user_msg}"
            web_context = maybe_web_search(q, True)
        except Exception as e:
            web_context = f"웹검색 실패: {str(e)}"

    system_prompt = """
너는 회의 보조 AI다.
반드시 한국어로 답한다.
회의 STT, 회의 자료, 사용자의 질문을 근거로 답한다.
없는 사실은 만들지 말고, 정보가 부족하면 부족하다고 말한다.
답변은 바로 회의에 쓸 수 있게 간결하고 구체적으로 작성한다.
""".strip()

    user_prompt = f"""
[회의 제목]
{payload.meetingTitle}

[회의 종류]
{payload.meetingType}

[키워드]
{payload.keywords}

[웹검색 참고]
{web_context or "(웹검색 사용 안 함 또는 결과 없음)"}

[회의 STT]
{meeting_text[-12000:] if meeting_text else "(아직 STT 없음)"}

[사용자 질문]
{user_msg}
""".strip()

    try:
        answer = _runtime_call_ai(system_prompt, user_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 응답 생성 실패: {str(e)}")

    return {
        "answer": answer,
        "message": answer,
        "mode": payload.mode,
        "usedWeb": payload.useWeb,
    }


@app.get("/api/realtime-topic")
def stable_realtime_topic():
    transcript = _runtime_latest_transcript_text()

    if not transcript.strip():
        return {
            "topic": "아직 분석할 STT가 없습니다.",
            "summary": "실시간 녹음을 시작하면 회의 주제가 표시됩니다.",
        }

    system_prompt = """
너는 실시간 회의 주제 분석 AI다.
최근 STT를 보고 현재 회의에서 논의 중인 주제를 한 문장으로 요약한다.
반드시 한국어 한 문장만 출력한다.
키워드 나열 금지.
""".strip()

    user_prompt = f"""
[최근 STT]
{transcript[-6000:]}

현재 논의 중인 회의 주제를 20~35자 정도의 한 문장형 제목으로 출력해.
""".strip()

    try:
        topic = _runtime_call_ai(system_prompt, user_prompt).strip().splitlines()[0]
    except Exception:
        topic = "실시간 회의 내용 분석 중"

    return {
        "topic": topic,
        "currentTopic": topic,
        "summary": topic,
    }


# ============================================================
# FINAL STABLE OVERRIDE: meeting session create
# Fixes: sqlite3.OperationalError: no such table: meeting_sessions
# ============================================================

from pydantic import BaseModel as __BaseModel
from typing import Optional as __Optional
import sqlite3 as __sqlite3
import uuid as __uuid
from pathlib import Path as __Path
from datetime import datetime as __datetime

__BASE_DIR = __Path(__file__).resolve().parent
__DATA_DIR = __BASE_DIR / "data"
__DB_PATH = __DATA_DIR / "meeting_app.sqlite3"


class __StableMeetingCreateRequest(__BaseModel):
    title: str = "새 회의"
    meetingTitle: __Optional[str] = None
    meeting_type: str = "general"
    meetingType: __Optional[str] = None
    meeting_time: str = ""
    meetingTime: __Optional[str] = None
    keywords: str = ""
    plan_text: str = ""
    planText: __Optional[str] = None
    realtime_recording_enabled: bool = True
    realtimeRecordingEnabled: __Optional[bool] = None


def __stable_conn():
    __DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = __sqlite3.connect(__DB_PATH)
    conn.row_factory = __sqlite3.Row
    return conn


def __stable_ensure_tables():
    conn = __stable_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_sessions (
        id TEXT PRIMARY KEY,
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

    conn.commit()
    conn.close()


def __stable_remove_route(path: str, methods=None):
    methods = set(methods or [])
    app.router.routes = [
        r for r in app.router.routes
        if not (
            getattr(r, "path", None) == path
            and (not methods or set(getattr(r, "methods", []) or []) == methods)
        )
    ]


__stable_remove_route("/meeting/session/create", {"POST"})


@app.post("/meeting/session/create")
def stable_create_meeting_session(payload: __StableMeetingCreateRequest):
    __stable_ensure_tables()

    session_id = str(__uuid.uuid4())
    now = __datetime.now().isoformat()

    title = payload.meetingTitle or payload.title or "새 회의"
    meeting_type = payload.meetingType or payload.meeting_type or "general"
    meeting_time = payload.meetingTime or payload.meeting_time or ""
    plan_text = payload.planText or payload.plan_text or ""
    realtime_enabled = (
        payload.realtimeRecordingEnabled
        if payload.realtimeRecordingEnabled is not None
        else payload.realtime_recording_enabled
    )

    conn = __stable_conn()
    conn.execute("""
        INSERT INTO meeting_sessions
        (id, title, meeting_time, keywords, meeting_type, realtime_recording_enabled, created_at, stopped_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        title,
        meeting_time,
        payload.keywords or "",
        meeting_type,
        1 if realtime_enabled else 0,
        now,
        None,
        "live",
    ))

    if plan_text.strip():
        item_id = str(__uuid.uuid4())
        conn.execute("""
            INSERT INTO library_items
            (id, session_id, scope, bucket, kind, name, file_path, text_content, preview_line, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_id,
            session_id,
            "session",
            "meeting_plan",
            "meeting_plan_text",
            "meeting_plan.txt",
            "",
            plan_text,
            plan_text[:220],
            now,
        ))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "id": session_id,
        "sessionId": session_id,
        "session_id": session_id,
        "title": title,
        "meetingTitle": title,
        "meetingType": meeting_type,
        "meeting_type": meeting_type,
        "meetingTime": meeting_time,
        "meeting_time": meeting_time,
        "keywords": payload.keywords or "",
        "status": "live",
    }
