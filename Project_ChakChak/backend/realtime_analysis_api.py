# backend/realtime_analysis_api.py
from fastapi import APIRouter
import sqlite3
import torch
from SLM_Loader import load_slm

router = APIRouter()

def get_recent_text(seconds=180):
    """최근 N초간의 대화를 DB에서 가져옴"""
    try:
        conn = sqlite3.connect("stt.sqlite3")
        cursor = conn.cursor()
        # 가장 마지막 end_sec 기준으로 최근 seconds만큼 추출
        query = """
            SELECT speaker, text FROM transcript_segments 
            WHERE end_sec > (SELECT MAX(end_sec) FROM transcript_segments) - ?
            ORDER BY start_sec ASC
        """
        cursor.execute(query, (seconds,))
        rows = cursor.fetchall()
        conn.close()
        return " ".join([f"{r[0]}: {r[1]}" for r in rows])
    except:
        return ""

@router.get("/api/realtime-topic")
async def get_realtime_topic():
    recent_context = get_recent_text(180) # 최근 3분
    if not recent_context:
        return {"topic": "대화 분석 중..."}

    model, tokenizer = load_slm()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # ChatML 포맷으로 모델이 딴소리 못하게 방어
    prompt = (
        f"<|im_start|>system\n너는 대화 요약기다. 현재 대화의 핵심 주제 반드시 한글만을 사용하여 5자 이내의 단어로만 말하라.<|im_end|>\n"
        f"<|im_start|>user\n내용: {recent_context[-2000:]}\n현재 주제는?<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs, 
            max_new_tokens=15, 
            temperature=0.1, 
            do_sample=False,
            repetition_penalty=1.2
        )
    
    topic = tokenizer.decode(output_ids[0], skip_special_tokens=True).split("assistant\n")[-1].strip()
    return {"topic": topic}