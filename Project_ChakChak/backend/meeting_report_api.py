import json
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from faster_whisper import WhisperModel

try:
    from chak_runtime_api import (
        ffmpeg_to_wav_16k_mono,
        call_ollama_chat,
        maybe_web_search,
        REALTIME_SLM_MODEL,
    )
except Exception:
    ffmpeg_to_wav_16k_mono = None
    call_ollama_chat = None
    maybe_web_search = None
    REALTIME_SLM_MODEL = "qwen2.5:3b"

router = APIRouter(prefix="/meeting-report", tags=["Meeting Report"])

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "meeting_app.sqlite3"

STT_MODEL_CACHE = {}
ALLOWED_STT_MODELS = {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"}


class AIEventCreate(BaseModel):
    question: str
    answer: str = ""
    askedAtSec: float = 0
    beforeContext: str = ""
    afterContext: str = ""


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_report_tables():
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


def parse_time_to_sec(time_text: str) -> int:
    parts = time_text.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def format_sec(sec: float) -> str:
    sec = max(0, int(sec))
    hh = sec // 3600
    mm = (sec % 3600) // 60
    ss = sec % 60
    if hh > 0:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"


def tokenize(text: str) -> List[str]:
    stopwords = {
        "그리고", "그래서", "근데", "일단", "이제", "그냥", "저희", "우리", "제가",
        "있는", "없는", "하면", "해서", "되는", "같은", "회의", "내용", "부분",
        "합니다", "했습니다", "같습니다", "있습니다", "없습니다", "거예요", "네", "어",
        "지금", "이거", "저거", "그거", "아까", "다음", "정도", "뭔가", "계속",
        "the", "and", "for", "with", "this", "that", "you", "are",
    }
    tokens = re.findall(r"[가-힣A-Za-z0-9_]{2,}", text.lower())
    return [t for t in tokens if t not in stopwords]


def get_selected_whisper_model(model_name: str):
    model_name = model_name or "medium"
    if model_name not in ALLOWED_STT_MODELS:
        model_name = "medium"

    if model_name in STT_MODEL_CACHE:
        return STT_MODEL_CACHE[model_name]

    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    STT_MODEL_CACHE[model_name] = model
    return model


def transcribe_audio_with_selected_model(file_path: str, model_name: str = "medium", language: str = "ko") -> str:
    if ffmpeg_to_wav_16k_mono is None:
        raise RuntimeError("ffmpeg_to_wav_16k_mono 함수 연결 실패")

    import tempfile
    import os

    model = get_selected_whisper_model(model_name)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
        wav_path = tmp_wav.name

    try:
        ffmpeg_to_wav_16k_mono(file_path, wav_path)

        segments, info = model.transcribe(
            wav_path,
            language=language or None,
            vad_filter=True,
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=True,
            word_timestamps=False,
        )

        lines = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue

            start_sec = int(float(seg.start))
            end_sec = int(float(seg.end))
            if end_sec <= start_sec:
                end_sec = start_sec + 1

            lines.append(
                f"[{format_sec(start_sec)}~{format_sec(end_sec)}] 익명1: {text}"
            )

        return "\n".join(lines)
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass


def extract_transcript_lines(raw_text: str):
    lines = []
    pattern = re.compile(
        r"\[(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*~\s*(?P<end>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<body>.*)"
    )

    for raw_line in raw_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        m = pattern.search(raw_line)
        if m:
            start_sec = parse_time_to_sec(m.group("start"))
            end_sec = parse_time_to_sec(m.group("end"))
            body = m.group("body").strip()

            speaker = "익명1"
            text = body
            if ":" in body:
                left, right = body.split(":", 1)
                if len(left.strip()) <= 20:
                    speaker = left.strip()
                    text = right.strip()

            if end_sec <= start_sec:
                end_sec = start_sec + 1

            lines.append({
                "startSec": start_sec,
                "endSec": end_sec,
                "start": format_sec(start_sec),
                "end": format_sec(end_sec),
                "speaker": speaker,
                "text": text,
            })
        else:
            prev_end = lines[-1]["endSec"] if lines else 0
            lines.append({
                "startSec": prev_end,
                "endSec": prev_end + 5,
                "start": format_sec(prev_end),
                "end": format_sec(prev_end + 5),
                "speaker": "익명1",
                "text": raw_line,
            })

    return lines


def transcript_to_prompt_lines(transcript_lines):
    return "\n".join([
        f"[{line['start']}~{line['end']}] {line['speaker']}: {line['text']}"
        for line in transcript_lines
    ])


def build_fallback_topic_sentence(text: str) -> str:
    words = [w for w, _ in Counter(tokenize(text)).most_common(5)]
    if not words:
        return "회의 논의 내용 정리"
    return f"{'·'.join(words[:3])} 관련 논의"


def fallback_topic_blocks_by_text_shift(transcript_lines):
    if not transcript_lines:
        return []

    blocks = []
    current = {
        "startSec": transcript_lines[0]["startSec"],
        "endSec": transcript_lines[0]["endSec"],
        "texts": [transcript_lines[0]["text"]],
        "lineIndexes": [0],
    }

    def top_set(texts):
        return set([w for w, _ in Counter(tokenize(" ".join(texts))).most_common(10)])

    for idx, line in enumerate(transcript_lines[1:], start=1):
        cur_tokens = top_set(current["texts"])
        line_tokens = set(tokenize(line["text"]))
        overlap = len(cur_tokens & line_tokens)
        duration = current["endSec"] - current["startSec"]
        gap = line["startSec"] - current["endSec"]
        line_len = len(line["text"])

        should_split = False
        if gap >= 25:
            should_split = True
        elif duration >= 75 and overlap == 0 and line_len >= 20:
            should_split = True
        elif duration >= 180 and overlap <= 1:
            should_split = True
        elif duration >= 360:
            should_split = True

        if should_split:
            blocks.append(current)
            current = {
                "startSec": line["startSec"],
                "endSec": line["endSec"],
                "texts": [line["text"]],
                "lineIndexes": [idx],
            }
        else:
            current["endSec"] = max(current["endSec"], line["endSec"])
            current["texts"].append(line["text"])
            current["lineIndexes"].append(idx)

    blocks.append(current)

    result = []
    for i, b in enumerate(blocks):
        text = " ".join(b["texts"])
        keywords = [w for w, _ in Counter(tokenize(text)).most_common(8)]
        topic = build_fallback_topic_sentence(text)
        result.append({
            "id": f"topic_{i+1}",
            "topic": topic,
            "startSec": b["startSec"],
            "endSec": b["endSec"],
            "start": format_sec(b["startSec"]),
            "end": format_sec(b["endSec"]),
            "durationSec": max(1, b["endSec"] - b["startSec"]),
            "keywords": keywords,
            "summary": text[:420],
            "lineIndexes": b["lineIndexes"],
            "text": text,
        })
    return result


def build_fallback_minutes(topic_blocks, ai_events):
    out = ["# 회의록 정리", "", "## 1. 주제별 진행"]
    for b in topic_blocks:
        out.append(f"- [{b['start']}~{b['end']}] {b['topic']}: {b['summary']}")

    out += ["", "## 2. 주제별 키워드"]
    for b in topic_blocks:
        out.append(f"- [{b['start']}~{b['end']}] {b['topic']} → {', '.join(b['keywords']) or '키워드 없음'}")

    out += ["", "## 3. AI 사용 시점"]
    if not ai_events:
        out.append("- 기록된 AI 질의가 없습니다.")
    else:
        for e in ai_events:
            out.append(f"- [{format_sec(e['asked_at_sec'])}] 질문: {e['question']}")

    return "\n".join(out)


def build_mindmap_text(topic_blocks):
    return " -> ".join([
        f"[{b['start']}~{b['end']}] {b['topic']}"
        for b in topic_blocks
    ])


def save_session(title: str, meeting_type: str = "uploaded_audio"):
    ensure_report_tables()
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    conn = get_conn()
    conn.execute("""
        INSERT INTO meeting_sessions
        (id, title, meeting_time, keywords, meeting_type, realtime_recording_enabled, created_at, stopped_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (session_id, title, now, "", meeting_type, 0, now, now, "stopped"))
    conn.commit()
    conn.close()
    return session_id


def save_library_item(session_id: str, bucket: str, kind: str, name: str, file_path: str, text_content: str):
    ensure_report_tables()
    item_id = str(uuid.uuid4())
    preview = text_content.splitlines()[0][:220] if text_content else name

    conn = get_conn()
    conn.execute("""
        INSERT INTO library_items
        (id, session_id, scope, bucket, kind, name, file_path, text_content, preview_line, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id, session_id, "session", bucket, kind, name, file_path,
        text_content, preview, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()
    return item_id


def read_session(session_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return row


def read_transcript_text(session_id: str):
    conn = get_conn()
    rows = conn.execute("""
        SELECT text_content, preview_line
        FROM library_items
        WHERE session_id = ?
          AND bucket IN ('live_recordings', 'post_meeting_recordings')
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()
    conn.close()

    texts = []
    for r in rows:
        t = r["text_content"] or r["preview_line"] or ""
        if t.strip():
            texts.append(t.strip())
    return "\n".join(texts)


def read_library_items_for_session(session_id: str):
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, session_id, bucket, kind, name, file_path, preview_line, created_at
        FROM library_items
        WHERE session_id = ?
        ORDER BY created_at DESC
    """, (session_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def read_ai_events(session_id: str):
    ensure_report_tables()
    conn = get_conn()
    rows = conn.execute("""
        SELECT *
        FROM meeting_ai_events
        WHERE session_id = ?
        ORDER BY asked_at_sec ASC, created_at ASC
    """, (session_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def extract_json_object(text: str):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON object not found")
    return json.loads(cleaned[start:end + 1])


def looks_bad_topic(topic: str) -> bool:
    topic = (topic or "").strip()

    if not topic:
        return True

    # 너무 긴 문장 = 주제명이 아니라 원문 일부일 가능성 큼
    if len(topic) > 38:
        return True

    # 키워드 나열 형태
    if "·" in topic or "/" in topic or "," in topic:
        return True

    # 조사/구어체가 많은 원문 느낌
    bad_phrases = [
        "이거", "저거", "그거", "아까", "지금", "근데", "그러면",
        "될까요", "했는데", "보는거는", "아니고", "있잖아",
        "목표가 있고", "왜 여쭤봐도", "내가", "우리가"
    ]
    if any(x in topic for x in bad_phrases):
        return True

    # 단어가 너무 적으면 키워드 수준
    if len(topic.split()) <= 2 and len(topic) <= 12:
        return True

    return False


def make_topic_sentence_with_slm(summary: str, text: str, keywords=None) -> str:
    keywords = keywords or []
    source = (summary or text or "").strip()

    if not source:
        if keywords:
            return f"{keywords[0]} 관련 논의"
        return "회의 주요 안건 논의"

    if call_ollama_chat is None:
        if keywords:
            return f"{keywords[0]} 관련 논의"
        return source[:28] + " 논의"

    system_prompt = """
너는 회의록의 주제명을 만드는 AI다.
입력된 회의 발화 내용을 보고 progress bar에 표시할 짧은 주제명을 만든다.

규칙:
- 반드시 한국어 한 줄만 출력한다.
- 12~28자 정도로 쓴다.
- 키워드 나열 금지.
- 발화 원문 복붙 금지.
- '이거', '지금', '근데', '우리가' 같은 구어체 금지.
- 명사구 형태로 작성한다.
- 예시: "GT 자동화 목표 설정 논의", "3D 변환 평가 방식 검토", "리포트웨어 개선 방향 논의"
""".strip()

    user_prompt = f"""
[키워드]
{", ".join(keywords[:8])}

[회의 발화/요약]
{source[:1200]}

위 내용을 대표하는 짧은 주제명 한 줄만 출력해.
""".strip()

    try:
        title = call_ollama_chat(REALTIME_SLM_MODEL, system_prompt, user_prompt)
        title = (title or "").strip()
        title = title.replace('"', '').replace("'", "")
        title = title.splitlines()[0].strip()
        title = re.sub(r"^[\-\*\d\.\)\s]+", "", title).strip()

        if looks_bad_topic(title):
            raise ValueError("bad title")

        return title[:36]
    except Exception:
        if keywords:
            return f"{keywords[0]} 관련 논의"
        return source[:24] + " 논의"


def normalize_topic_sentence(topic: str, summary: str = "", text: str = "", keywords=None):
    keywords = keywords or []
    topic = (topic or "").strip()

    if looks_bad_topic(topic):
        return make_topic_sentence_with_slm(summary, text, keywords)

    return topic

def normalize_report(raw, session, transcript_lines, ai_events):
    total_sec = 0
    if transcript_lines:
        total_sec = max(line["endSec"] for line in transcript_lines)
    if ai_events:
        total_sec = max(total_sec, int(max(e["asked_at_sec"] for e in ai_events)) + 10)

    blocks = raw.get("topicBlocks") or []
    norm_blocks = []

    for i, b in enumerate(blocks):
        start_sec = int(b.get("startSec", 0))
        end_sec = int(b.get("endSec", start_sec + 1))
        if end_sec <= start_sec:
            end_sec = start_sec + 1
        total_sec = max(total_sec, end_sec)

        keywords = b.get("keywords") or []
        summary = b.get("summary") or ""
        topic = normalize_topic_sentence(b.get("topic"), summary, b.get("text") or "", keywords)

        norm_blocks.append({
            "id": b.get("id") or f"topic_{i+1}",
            "topic": topic,
            "startSec": start_sec,
            "endSec": end_sec,
            "start": format_sec(start_sec),
            "end": format_sec(end_sec),
            "durationSec": max(1, end_sec - start_sec),
            "keywords": keywords,
            "summary": summary,
            "lineIndexes": b.get("lineIndexes") or [],
            "text": b.get("text") or "",
        })

    if not norm_blocks:
        norm_blocks = fallback_topic_blocks_by_text_shift(transcript_lines)

    if norm_blocks:
        total_sec = max(total_sec, max(b["endSec"] for b in norm_blocks))

    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "meetingTime": session["meeting_time"],
            "keywords": session["keywords"],
            "meetingType": session["meeting_type"],
            "status": session["status"],
        },
        "totalSec": total_sec,
        "transcriptLines": transcript_lines,
        "topicBlocks": norm_blocks,
        "aiEvents": [
            {
                "id": e["id"],
                "question": e["question"],
                "answer": e["answer"],
                "askedAtSec": e["asked_at_sec"],
                "askedAt": format_sec(e["asked_at_sec"]),
                "beforeContext": e["before_context"],
                "afterContext": e["after_context"],
                "createdAt": e["created_at"],
            }
            for e in ai_events
        ],
        "minutesMarkdown": raw.get("minutesMarkdown") or build_fallback_minutes(norm_blocks, ai_events),
        "mindmapText": raw.get("mindmapText") or build_mindmap_text(norm_blocks),
        "webContext": raw.get("webContext", ""),
        "analysisModel": raw.get("analysisModel", REALTIME_SLM_MODEL),
        "analysisMode": raw.get("analysisMode", "SLM_TOPIC_SENTENCE"),
        "diarizationStatus": "not_applied",
        "diarizationNote": "현재 익명1/익명2 분리는 적용되지 않았습니다. VAD는 무음/발화 분리이고, 화자 분리는 pyannote diarization 추가가 필요합니다.",
    }


def generate_slm_report(session, transcript_text, transcript_lines, ai_events):
    web_query = f"{session['title']} {session['keywords']} 회의 주제 배경 키워드 참고자료"
    web_context = ""
    if maybe_web_search is not None:
        try:
            web_context = maybe_web_search(web_query, True)
        except Exception:
            web_context = ""

    if call_ollama_chat is None:
        raw = {"topicBlocks": fallback_topic_blocks_by_text_shift(transcript_lines)}
        return normalize_report(raw, session, transcript_lines, ai_events)

    ai_events_text = "\n".join([
        f"[{format_sec(e['asked_at_sec'])}] Q: {e['question']}\nA: {e['answer']}"
        for e in ai_events
    ]) or "(AI 사용 기록 없음)"

    transcript_prompt = transcript_to_prompt_lines(transcript_lines)

    system_prompt = """
너는 회의 STT를 읽고 회의 주제 흐름을 분석하는 전문 회의록 작성 AI다.

반드시 JSON 하나만 출력한다.
markdown fence, 설명문, 주석은 절대 출력하지 마라.

가장 중요한 규칙:
1. topic은 절대 키워드 나열이 아니다.
2. topic은 반드시 사람이 읽을 수 있는 '한 문장형 주제명'이어야 한다.
3. 나쁜 topic 예시: "3d로 / 자동 / 했던", "지금 · 이거 · 아까", "리포트웨어"
4. 좋은 topic 예시:
   - "3D 자동 변환 모델의 평가 방법 논의"
   - "데이터 편향성과 외부 검증 필요성 논의"
   - "LLM 관련 최신 연구 인용 방향 논의"
   - "랜덤포레스트 선택 근거와 해석 가능성 보완"
5. topic은 12~35자 정도의 한국어 명사구/문장으로 작성한다.
6. startSec/endSec는 STT timestamp를 기준으로 의미가 바뀌는 지점에서 자른다.
7. 절대 고정 2분 단위로 자르지 마라.
8. 의미가 이어지는 논의는 한 블록으로 묶어라.
9. 너무 잘게 자르지 말고 전체 회의에서 5~12개 정도의 큰 주제로 나눠라.
10. STT가 일부 깨져도 문맥을 추론해서 자연스러운 주제명으로 정리하라.
""".strip()

    user_prompt = f"""
다음 STT를 읽고 회의 주제별 progress bar에 들어갈 topicBlocks를 만들어라.

출력 JSON schema:
{{
  "topicBlocks": [
    {{
      "id": "topic_1",
      "topic": "한 문장형 주제명",
      "startSec": 0,
      "endSec": 120,
      "keywords": ["핵심 키워드1", "핵심 키워드2"],
      "summary": "이 구간에서 실제로 논의된 내용을 2~3문장으로 요약",
      "text": "해당 구간 핵심 원문 또는 상세 요약"
    }}
  ],
  "minutesMarkdown": "# 회의록 정리 ...",
  "mindmapText": "[00:00~02:00] 한 문장형 주제명 - [02:00~05:00] 한 문장형 주제명",
  "webContext": "웹검색 참고 요약",
  "analysisModel": "{REALTIME_SLM_MODEL}",
  "analysisMode": "SLM_TOPIC_SENTENCE"
}}

[웹검색 참고정보]
{web_context or "(웹검색 결과 없음)"}

[AI 사용 시점]
{ai_events_text}

[STT Transcript]
{transcript_prompt[:26000]}
""".strip()

    try:
        slm_text = call_ollama_chat(REALTIME_SLM_MODEL, system_prompt, user_prompt)
        raw = extract_json_object(slm_text)
    except Exception:
        raw = {"topicBlocks": fallback_topic_blocks_by_text_shift(transcript_lines)}

    raw["webContext"] = web_context
    raw["analysisModel"] = REALTIME_SLM_MODEL
    raw["analysisMode"] = "SLM_TOPIC_SENTENCE"

    return normalize_report(raw, session, transcript_lines, ai_events)


def cache_report(session_id: str, report: dict):
    ensure_report_tables()
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
        INSERT INTO meeting_report_cache
        (session_id, report_json, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            report_json = excluded.report_json,
            updated_at = excluded.updated_at
    """, (session_id, json.dumps(report, ensure_ascii=False), now, now))
    conn.commit()
    conn.close()


def read_cached_report(session_id: str):
    ensure_report_tables()
    conn = get_conn()
    row = conn.execute(
        "SELECT report_json FROM meeting_report_cache WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["report_json"])
    except Exception:
        return None


@router.post("/upload-audio")
async def upload_audio_for_report(
    file: UploadFile = File(...),
    stt_model: str = Form("medium"),
    language: str = Form("ko"),
):
    ensure_report_tables()

    allowed = {".wav", ".mp3", ".m4a", ".webm", ".mp4", ".aac", ".ogg", ".flac"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="음성/영상 파일만 업로드할 수 있습니다.")

    if stt_model not in ALLOWED_STT_MODELS:
        stt_model = "medium"

    session_id = save_session(f"{Path(file.filename).stem} ({stt_model})", "uploaded_audio")
    upload_dir = DATA_DIR / "uploaded_audio" / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dst = upload_dir / file.filename

    with open(dst, "wb") as f:
        f.write(await file.read())

    try:
        transcript = transcribe_audio_with_selected_model(str(dst), stt_model, language or "ko")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STT 변환 실패: {str(e)}")

    save_library_item(
        session_id=session_id,
        bucket="post_meeting_recordings",
        kind=f"uploaded_audio_transcript_{stt_model}",
        name=file.filename,
        file_path=str(dst),
        text_content=transcript,
    )

    session = read_session(session_id)
    transcript_lines = extract_transcript_lines(transcript)
    ai_events = read_ai_events(session_id)

    report = generate_slm_report(session, transcript, transcript_lines, ai_events)
    report["sttModel"] = stt_model
    report["language"] = language or "ko"
    cache_report(session_id, report)

    return {
        "sessionId": session_id,
        "filename": file.filename,
        "sttModel": stt_model,
        "language": language or "ko",
        "transcriptPreview": transcript[:800],
        "report": report,
    }


@router.post("/{session_id}/ai-event")
def create_ai_event(session_id: str, payload: AIEventCreate):
    ensure_report_tables()
    if not read_session(session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    conn = get_conn()
    event_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO meeting_ai_events
        (id, session_id, question, answer, asked_at_sec, before_context, after_context, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id, session_id, payload.question, payload.answer,
        payload.askedAtSec, payload.beforeContext, payload.afterContext,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()
    return {"id": event_id, "sessionId": session_id, "askedAtSec": payload.askedAtSec}


@router.get("/{session_id}/items")
def get_session_items(session_id: str):
    ensure_report_tables()
    if not read_session(session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return {"items": read_library_items_for_session(session_id)}


@router.get("/{session_id}/transcript")
def get_session_transcript(session_id: str):
    ensure_report_tables()
    if not read_session(session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    text = read_transcript_text(session_id)
    return {
        "sessionId": session_id,
        "transcriptText": text,
        "transcriptLines": extract_transcript_lines(text),
        "diarizationStatus": "not_applied",
        "diarizationNote": "현재는 STT segment 기준 익명1만 저장합니다. 익명1/익명2 분리는 pyannote diarization 연결 후 가능합니다.",
    }


@router.post("/{session_id}/regenerate")
def regenerate_meeting_report(session_id: str):
    ensure_report_tables()
    session = read_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    transcript = read_transcript_text(session_id)
    lines = extract_transcript_lines(transcript)
    ai_events = read_ai_events(session_id)
    report = generate_slm_report(session, transcript, lines, ai_events)
    cache_report(session_id, report)
    return report


@router.get("/{session_id}")
def get_meeting_report(session_id: str):
    ensure_report_tables()
    session = read_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    cached = read_cached_report(session_id)
    if cached:
        return cached
    transcript = read_transcript_text(session_id)
    lines = extract_transcript_lines(transcript)
    ai_events = read_ai_events(session_id)
    report = generate_slm_report(session, transcript, lines, ai_events)
    cache_report(session_id, report)
    return report
