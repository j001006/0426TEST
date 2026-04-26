from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from faster_whisper import WhisperModel
from pyannote.audio import Pipeline
from pathlib import Path
import tempfile
import os
import sqlite3
import subprocess
import wave
import contextlib
import webrtcvad
from datetime import datetime
import torch

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "stt.sqlite3"
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

HF_TOKEN = os.environ.get("HF_TOKEN")

MODEL_CACHE = {}

ALLOWED_REALTIME_MODELS = {
    "tiny", "base", "small", "distil-small.en", "large-v3-turbo"
}

ALLOWED_FINAL_MODELS = {
    "small", "medium", "large-v3", "large-v3-turbo"
}

DEFAULT_REALTIME_MODEL = "base"
DEFAULT_FINAL_MODEL = "medium"


def get_whisper_model(model_name: str):   ##GPU --> CPU 로 실행하게 임시 변경
    if model_name in MODEL_CACHE:
        return MODEL_CACHE[model_name]

    # GPU 아예 안 쓰고 CPU로 고정
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8"
    )

    MODEL_CACHE[model_name] = model
    return model
    
    
    # if model_name in MODEL_CACHE:
    #     return MODEL_CACHE[model_name]

    # try:
    #     model = WhisperModel(model_name, device="cuda", compute_type="float16")
    # except Exception:
    #     model = WhisperModel(model_name, device="cpu", compute_type="int8")

    # MODEL_CACHE[model_name] = model
    # return model


diarization_pipeline = None
if HF_TOKEN:
    try:
        diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=HF_TOKEN
        )
        if torch.cuda.is_available():
            diarization_pipeline.to(torch.device("cuda"))
    except Exception as e:
        print(f"[WARN] diarization pipeline load failed: {e}")
        diarization_pipeline = None


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transcript_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'upload',
        channel_name TEXT,
        status TEXT NOT NULL DEFAULT 'completed',
        realtime_model_name TEXT,
        final_model_name TEXT,
        language TEXT,
        full_text TEXT,
        pretty_text TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        ended_at TEXT,
        total_duration REAL DEFAULT 0,
        total_silence REAL DEFAULT 0,
        silence_events INTEGER DEFAULT 0,
        current_silence_run REAL DEFAULT 0,
        meeting_state TEXT DEFAULT 'idle'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transcript_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        speaker TEXT NOT NULL DEFAULT '익명1',
        start_sec REAL NOT NULL,
        end_sec REAL NOT NULL,
        text TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'speech',
        FOREIGN KEY(session_id) REFERENCES transcript_sessions(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vad_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        start_sec REAL NOT NULL,
        end_sec REAL NOT NULL,
        duration_sec REAL NOT NULL,
        state TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES transcript_sessions(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS realtime_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        offset_sec REAL NOT NULL,
        original_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES transcript_sessions(id)
    )
    """)

    conn.commit()
    conn.close()


@router.on_event("startup")
def startup():
    init_db()


def session_dir(session_id: int) -> Path:
    d = STORAGE_DIR / f"session_{session_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ffmpeg_to_wav_16k_mono(src_path: str, dst_path: str):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", src_path,
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        dst_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def concat_webm_files(file_paths, output_path):
    list_file = output_path.parent / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in file_paths:
            f.write(f"file '{str(Path(p).resolve())}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    list_file.unlink(missing_ok=True)


def format_state(silence_duration: float) -> str:
    if silence_duration < 0.7:
        return "micro_pause"
    elif silence_duration < 3.0:
        return "short_pause"
    elif silence_duration < 8.0:
        return "extended_pause"
    else:
        return "stagnation"


def format_mmss(sec: float) -> str:
    total = max(0, int(sec))
    mm = str(total // 60).zfill(2)
    ss = str(total % 60).zfill(2)
    return f"{mm}:{ss}"


def run_vad_and_collect_silence(wav_path: str):
    vad = webrtcvad.Vad(2)

    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()

        if channels != 1 or sample_width != 2 or sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError("VAD용 WAV는 mono PCM16 이어야 합니다.")

        total_duration = n_frames / float(sample_rate)
        frame_ms = 30
        frame_bytes = int(sample_rate * (frame_ms / 1000.0) * sample_width)

        audio = wf.readframes(n_frames)

    silence_events = []
    in_silence = False
    silence_start = 0.0
    offset = 0.0

    cursor = 0
    while cursor + frame_bytes <= len(audio):
        frame = audio[cursor:cursor + frame_bytes]
        is_speech = vad.is_speech(frame, sample_rate)

        if not is_speech and not in_silence:
            in_silence = True
            silence_start = offset

        if is_speech and in_silence:
            silence_end = offset
            duration = silence_end - silence_start
            if duration > 0.3:
                silence_events.append({
                    "start_sec": round(silence_start, 2),
                    "end_sec": round(silence_end, 2),
                    "duration_sec": round(duration, 2),
                    "state": format_state(duration)
                })
            in_silence = False

        offset += frame_ms / 1000.0
        cursor += frame_bytes

    if in_silence:
        silence_end = total_duration
        duration = silence_end - silence_start
        if duration > 0.3:
            silence_events.append({
                "start_sec": round(silence_start, 2),
                "end_sec": round(silence_end, 2),
                "duration_sec": round(duration, 2),
                "state": format_state(duration)
            })

    total_silence = round(sum(e["duration_sec"] for e in silence_events), 2)

    return {
        "total_duration": round(total_duration, 2),
        "total_silence": total_silence,
        "silence_events": silence_events
    }


def run_diarization(wav_path: str):
    if diarization_pipeline is None:
        return []

    diarization = diarization_pipeline(wav_path)
    exclusive = getattr(diarization, "exclusive_speaker_diarization", None)
    diar_source = exclusive if exclusive is not None else diarization

    turns = []
    speaker_map = {}
    speaker_count = 0

    for turn, _, speaker in diar_source.itertracks(yield_label=True):
        if speaker not in speaker_map:
            speaker_count += 1
            speaker_map[speaker] = f"익명{speaker_count}"

        turns.append({
            "start_sec": round(float(turn.start), 2),
            "end_sec": round(float(turn.end), 2),
            "speaker": speaker_map[speaker]
        })

    return turns


def overlap(a_start, a_end, b_start, b_end):
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speaker_to_segments(asr_segments, diar_turns):
    if not diar_turns:
        for seg in asr_segments:
            seg["speaker"] = "익명1"
        return asr_segments

    for seg in asr_segments:
        best_speaker = "익명1"
        best_overlap = 0.0

        for turn in diar_turns:
            ov = overlap(seg["start_sec"], seg["end_sec"], turn["start_sec"], turn["end_sec"])
            if ov > best_overlap:
                best_overlap = ov
                best_speaker = turn["speaker"]

        seg["speaker"] = best_speaker

    return asr_segments


def build_merged_timeline(segments, vad_events):
    speech_items = [
        {
            "kind": "speech",
            "start_sec": seg["start_sec"],
            "end_sec": seg["end_sec"],
            "speaker": seg["speaker"],
            "text": seg["text"]
        }
        for seg in segments
    ]

    silence_items = [
        {
            "kind": "silence",
            "start_sec": ev["start_sec"],
            "end_sec": ev["end_sec"],
            "speaker": None,
            "text": "발화 X",
            "state": ev["state"]
        }
        for ev in vad_events
    ]

    merged = speech_items + silence_items
    merged.sort(key=lambda x: (x["start_sec"], x["end_sec"]))
    return merged


def build_pretty_text(merged_timeline):
    lines = []
    for item in merged_timeline:
        start_str = format_mmss(item["start_sec"])
        end_str = format_mmss(item["end_sec"])

        if item["kind"] == "speech":
            lines.append(f"[{start_str}~{end_str}] {item['speaker']}: {item['text']}")
        else:
            lines.append(f"[{start_str}~{end_str}] 발화 X")
    return "\n".join(lines)


def clear_session_outputs(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM transcript_segments WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM vad_events WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def write_session_outputs(session_id: int, segments, vad_events):
    conn = get_conn()
    cur = conn.cursor()

    for seg in segments:
        cur.execute("""
            INSERT INTO transcript_segments (session_id, speaker, start_sec, end_sec, text, kind)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            seg["speaker"],
            seg["start_sec"],
            seg["end_sec"],
            seg["text"],
            "speech"
        ))

    for ev in vad_events:
        cur.execute("""
            INSERT INTO vad_events (session_id, start_sec, end_sec, duration_sec, state)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session_id,
            ev["start_sec"],
            ev["end_sec"],
            ev["duration_sec"],
            ev["state"]
        ))

    conn.commit()
    conn.close()


def update_session_summary(
    session_id: int,
    language,
    full_text,
    pretty_text,
    total_duration,
    total_silence,
    silence_events,
    status="completed",
    current_silence_run=0,
    meeting_state="idle"
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE transcript_sessions
        SET language = ?, full_text = ?, pretty_text = ?, total_duration = ?, total_silence = ?,
            silence_events = ?, status = ?, current_silence_run = ?, meeting_state = ?, ended_at = ?
        WHERE id = ?
    """, (
        language,
        full_text,
        pretty_text,
        total_duration,
        total_silence,
        silence_events,
        status,
        current_silence_run,
        meeting_state,
        datetime.now().isoformat() if status == "completed" else None,
        session_id
    ))
    conn.commit()
    conn.close()


def get_session_row(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM transcript_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return row


def transcribe_with_model(model, wav_path: str):
    segments_gen, info = model.transcribe(wav_path, vad_filter=False)

    asr_segments = []
    full_text_parts = []

    for seg in segments_gen:
        text = seg.text.strip()
        if not text:
            continue

        item = {
            "speaker": "익명1",
            "start_sec": round(seg.start, 2),
            "end_sec": round(seg.end, 2),
            "text": text
        }
        asr_segments.append(item)
        full_text_parts.append(text)

    full_text = " ".join(full_text_parts).strip()
    return asr_segments, getattr(info, "language", None), full_text


@router.get("/stt/health")
def stt_health():
    return {"message": "stt backend is running"}


@router.post("/stt/upload")
async def upload_and_transcribe(
    file: UploadFile = File(...),
    final_model_name: str = Form(DEFAULT_FINAL_MODEL),
):
    if final_model_name not in ALLOWED_FINAL_MODELS:
        raise HTTPException(status_code=400, detail="허용되지 않은 최종본 모델입니다.")

    suffix = os.path.splitext(file.filename)[1] or ".wav"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_input:
        tmp_input.write(await file.read())
        input_path = tmp_input.name

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
        wav_path = tmp_wav.name

    try:
        ffmpeg_to_wav_16k_mono(input_path, wav_path)

        final_model = get_whisper_model(final_model_name)
        asr_segments, language, full_text = transcribe_with_model(final_model, wav_path)
        diar_turns = run_diarization(wav_path)
        diarized_segments = assign_speaker_to_segments(asr_segments, diar_turns)

        vad_result = run_vad_and_collect_silence(wav_path)
        merged_timeline = build_merged_timeline(diarized_segments, vad_result["silence_events"])
        pretty_text = build_pretty_text(merged_timeline)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transcript_sessions
            (filename, source_type, channel_name, status, realtime_model_name, final_model_name,
             language, full_text, pretty_text, created_at, started_at, ended_at,
             total_duration, total_silence, silence_events, current_silence_run, meeting_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file.filename,
            "upload",
            None,
            "completed",
            None,
            final_model_name,
            language,
            full_text,
            pretty_text,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
            datetime.now().isoformat(),
            vad_result["total_duration"],
            vad_result["total_silence"],
            len(vad_result["silence_events"]),
            0,
            "idle"
        ))
        session_id = cur.lastrowid
        conn.commit()
        conn.close()

        write_session_outputs(session_id, diarized_segments, vad_result["silence_events"])

        return {
            "session_id": session_id,
            "filename": file.filename,
            "language": language,
            "text": full_text,
            "pretty_text": pretty_text,
            "segments": diarized_segments,
            "merged_timeline": merged_timeline,
            "vad_summary": {
                "total_duration": vad_result["total_duration"],
                "total_silence": vad_result["total_silence"],
                "silence_events": len(vad_result["silence_events"])
            },
            "final_model_name": final_model_name,
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"ffmpeg 변환 실패: {e.stderr.decode(errors='ignore')}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(wav_path):
            os.remove(wav_path)


@router.post("/stt/realtime/start")
def start_realtime_meeting(
    channel_name: str = Form(...),
    realtime_model_name: str = Form(DEFAULT_REALTIME_MODEL),
    final_model_name: str = Form(DEFAULT_FINAL_MODEL),
):
    if realtime_model_name not in ALLOWED_REALTIME_MODELS:
        raise HTTPException(status_code=400, detail="허용되지 않은 실시간 모델입니다.")
    if final_model_name not in ALLOWED_FINAL_MODELS:
        raise HTTPException(status_code=400, detail="허용되지 않은 최종본 모델입니다.")

    now = datetime.now().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transcript_sessions
        (filename, source_type, channel_name, status, realtime_model_name, final_model_name,
         language, full_text, pretty_text, created_at, started_at,
         total_duration, total_silence, silence_events, current_silence_run, meeting_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"{channel_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.webm",
        "realtime",
        channel_name,
        "recording",
        realtime_model_name,
        final_model_name,
        None,
        "",
        "",
        now,
        now,
        0,
        0,
        0,
        0,
        "idle"
    ))
    session_id = cur.lastrowid
    conn.commit()
    conn.close()

    session_dir(session_id)
    return {
        "session_id": session_id,
        "realtime_model_name": realtime_model_name,
        "final_model_name": final_model_name,
    }


@router.post("/stt/realtime/chunk")
async def upload_realtime_chunk(
    session_id: int = Form(...),
    offset_sec: float = Form(...),
    file: UploadFile = File(...)
):
    session = get_session_row(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    if session["status"] != "recording":
        raise HTTPException(status_code=400, detail="이미 종료된 세션입니다.")

    sdir = session_dir(session_id)

    conn = get_conn()
    cur = conn.cursor()
    chunk_count = cur.execute(
        "SELECT COUNT(*) AS cnt FROM realtime_chunks WHERE session_id = ?",
        (session_id,)
    ).fetchone()["cnt"]
    chunk_index = chunk_count + 1

    original_path = sdir / f"chunk_{chunk_index:05d}.webm"
    with open(original_path, "wb") as f:
        f.write(await file.read())

    cur.execute("""
        INSERT INTO realtime_chunks (session_id, chunk_index, offset_sec, original_path, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session_id,
        chunk_index,
        offset_sec,
        str(original_path),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

    wav_path = sdir / f"chunk_{chunk_index:05d}.wav"

    try:
        ffmpeg_to_wav_16k_mono(str(original_path), str(wav_path))
        vad_result = run_vad_and_collect_silence(str(wav_path))

        realtime_model_name = session["realtime_model_name"] or DEFAULT_REALTIME_MODEL
        realtime_model = get_whisper_model(realtime_model_name)
        asr_segments, language, chunk_text = transcribe_with_model(realtime_model, str(wav_path))

        global_segments = []
        for seg in asr_segments:
            global_segments.append({
                "speaker": "익명1",
                "start_sec": round(offset_sec + seg["start_sec"], 2),
                "end_sec": round(offset_sec + seg["end_sec"], 2),
                "text": seg["text"]
            })

        global_vad_events = []
        for ev in vad_result["silence_events"]:
            global_vad_events.append({
                "start_sec": round(offset_sec + ev["start_sec"], 2),
                "end_sec": round(offset_sec + ev["end_sec"], 2),
                "duration_sec": ev["duration_sec"],
                "state": ev["state"]
            })

        if global_segments:
            write_session_outputs(session_id, global_segments, [])
            current_silence_run = 0
            meeting_state = "speech"
        else:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT current_silence_run FROM transcript_sessions WHERE id = ?", (session_id,))
            prev_run = cur.fetchone()["current_silence_run"] or 0
            conn.close()

            added_silence = vad_result["total_duration"]
            current_silence_run = round(prev_run + added_silence, 2) if added_silence > 0 else prev_run
            meeting_state = format_state(current_silence_run)

        if global_vad_events:
            write_session_outputs(session_id, [], global_vad_events)

        conn = get_conn()
        cur = conn.cursor()

        prev_total = cur.execute(
            "SELECT total_duration, total_silence, silence_events, full_text FROM transcript_sessions WHERE id = ?",
            (session_id,)
        ).fetchone()

        new_total_duration = round((prev_total["total_duration"] or 0) + vad_result["total_duration"], 2)
        new_total_silence = round((prev_total["total_silence"] or 0) + vad_result["total_silence"], 2)
        new_silence_events = (prev_total["silence_events"] or 0) + len(global_vad_events)

        appended_text = prev_total["full_text"] or ""
        if chunk_text:
            appended_text = (appended_text + " " + chunk_text).strip()

        cur.execute("""
            UPDATE transcript_sessions
            SET language = COALESCE(language, ?),
                full_text = ?,
                total_duration = ?,
                total_silence = ?,
                silence_events = ?,
                current_silence_run = ?,
                meeting_state = ?
            WHERE id = ?
        """, (
            language,
            appended_text,
            new_total_duration,
            new_total_silence,
            new_silence_events,
            current_silence_run,
            meeting_state,
            session_id
        ))
        conn.commit()
        conn.close()

        return {
            "session_id": session_id,
            "chunk_index": chunk_index,
            "chunk_text": chunk_text,
            "meeting_state": meeting_state,
            "current_silence_run": current_silence_run,
            "total_duration": new_total_duration,
            "realtime_model_name": realtime_model_name,
            "final_model_name": session["final_model_name"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)


@router.post("/stt/realtime/stop")
def stop_realtime_meeting(session_id: int = Form(...)):
    session = get_session_row(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    conn = get_conn()
    cur = conn.cursor()
    chunks = cur.execute("""
        SELECT original_path FROM realtime_chunks
        WHERE session_id = ?
        ORDER BY chunk_index ASC
    """, (session_id,)).fetchall()
    conn.close()

    if not chunks:
        raise HTTPException(status_code=400, detail="저장된 chunk가 없습니다.")

    sdir = session_dir(session_id)
    merged_webm = sdir / "merged.webm"
    merged_wav = sdir / "merged.wav"

    try:
        concat_webm_files([row["original_path"] for row in chunks], merged_webm)
        ffmpeg_to_wav_16k_mono(str(merged_webm), str(merged_wav))

        final_model_name = session["final_model_name"] or DEFAULT_FINAL_MODEL
        final_model = get_whisper_model(final_model_name)

        asr_segments, language, full_text = transcribe_with_model(final_model, str(merged_wav))
        diar_turns = run_diarization(str(merged_wav))
        diarized_segments = assign_speaker_to_segments(asr_segments, diar_turns)

        vad_result = run_vad_and_collect_silence(str(merged_wav))
        merged_timeline = build_merged_timeline(diarized_segments, vad_result["silence_events"])
        pretty_text = build_pretty_text(merged_timeline)

        clear_session_outputs(session_id)
        write_session_outputs(session_id, diarized_segments, vad_result["silence_events"])
        update_session_summary(
            session_id=session_id,
            language=language,
            full_text=full_text,
            pretty_text=pretty_text,
            total_duration=vad_result["total_duration"],
            total_silence=vad_result["total_silence"],
            silence_events=len(vad_result["silence_events"]),
            status="completed",
            current_silence_run=0,
            meeting_state="idle"
        )

        return {
            "session_id": session_id,
            "status": "completed",
            "pretty_text": pretty_text,
            "merged_timeline": merged_timeline,
            "final_model_name": final_model_name,
            "realtime_model_name": session["realtime_model_name"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stt/sessions")
def get_sessions():
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, filename, source_type, channel_name, status, realtime_model_name, final_model_name,
               language, full_text, pretty_text, created_at, total_duration, total_silence, silence_events
        FROM transcript_sessions
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    data = []
    for row in rows:
        preview = (row["pretty_text"] or row["full_text"] or "")[:140]
        data.append({
            "id": row["id"],
            "filename": row["filename"],
            "source_type": row["source_type"],
            "channel_name": row["channel_name"],
            "status": row["status"],
            "realtime_model_name": row["realtime_model_name"],
            "final_model_name": row["final_model_name"],
            "language": row["language"],
            "created_at": row["created_at"],
            "preview": preview,
            "total_duration": row["total_duration"],
            "total_silence": row["total_silence"],
            "silence_events": row["silence_events"]
        })

    return data


@router.get("/stt/sessions/{session_id}")
def get_session_detail(session_id: int):
    conn = get_conn()
    cur = conn.cursor()

    session = cur.execute("""
        SELECT id, filename, source_type, channel_name, status, realtime_model_name, final_model_name,
               language, full_text, pretty_text, created_at,
               started_at, ended_at, total_duration, total_silence, silence_events, current_silence_run, meeting_state
        FROM transcript_sessions
        WHERE id = ?
    """, (session_id,)).fetchone()

    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    segments = cur.execute("""
        SELECT id, speaker, start_sec, end_sec, text, kind
        FROM transcript_segments
        WHERE session_id = ?
        ORDER BY start_sec ASC
    """, (session_id,)).fetchall()

    vad_events = cur.execute("""
        SELECT id, start_sec, end_sec, duration_sec, state
        FROM vad_events
        WHERE session_id = ?
        ORDER BY start_sec ASC
    """, (session_id,)).fetchall()

    conn.close()

    segment_list = [
        {
            "id": s["id"],
            "speaker": s["speaker"],
            "start_sec": s["start_sec"],
            "end_sec": s["end_sec"],
            "text": s["text"],
            "kind": s["kind"]
        }
        for s in segments
    ]

    vad_list = [
        {
            "id": v["id"],
            "start_sec": v["start_sec"],
            "end_sec": v["end_sec"],
            "duration_sec": v["duration_sec"],
            "state": v["state"]
        }
        for v in vad_events
    ]

    merged_timeline = build_merged_timeline(segment_list, vad_list)

    return {
        "id": session["id"],
        "filename": session["filename"],
        "source_type": session["source_type"],
        "channel_name": session["channel_name"],
        "status": session["status"],
        "realtime_model_name": session["realtime_model_name"],
        "final_model_name": session["final_model_name"],
        "language": session["language"],
        "full_text": session["full_text"],
        "pretty_text": session["pretty_text"],
        "created_at": session["created_at"],
        "started_at": session["started_at"],
        "ended_at": session["ended_at"],
        "total_duration": session["total_duration"],
        "total_silence": session["total_silence"],
        "silence_events": session["silence_events"],
        "current_silence_run": session["current_silence_run"],
        "meeting_state": session["meeting_state"],
        "segments": segment_list,
        "vad_events": vad_list,
        "merged_timeline": merged_timeline
    }