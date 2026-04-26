import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app_config

# 코드 고정 설정 → 기존 모듈들이 os.environ을 보더라도 동작하게 주입
os.environ["OLLAMA_BASE_URL"] = app_config.OLLAMA_BASE_URL
os.environ["GENERAL_SLM_MODEL"] = app_config.GENERAL_SLM_MODEL
os.environ["REALTIME_SLM_MODEL"] = app_config.REALTIME_SLM_MODEL
os.environ["WHISPER_REALTIME_MODEL_NAME"] = app_config.WHISPER_REALTIME_MODEL_NAME
os.environ["WHISPER_UPLOAD_MODEL_NAME"] = app_config.WHISPER_UPLOAD_MODEL_NAME
os.environ["WEB_SEARCH_PROVIDER"] = app_config.WEB_SEARCH_PROVIDER
os.environ["SERPAPI_API_KEY"] = app_config.SERPAPI_API_KEY
os.environ["SERPAPI_ENGINE"] = app_config.SERPAPI_ENGINE
os.environ["SERPAPI_GL"] = app_config.SERPAPI_GL
os.environ["SERPAPI_HL"] = app_config.SERPAPI_HL
os.environ["SERPAPI_LOCATION"] = app_config.SERPAPI_LOCATION

try:
    from database import engine
    import models
    models.Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[WARN] DB init skipped: {e}")

try:
    from mindmap_api import router as mindmap_router
except Exception as e:
    mindmap_router = None
    print(f"[WARN] mindmap_api import failed: {e}")

try:
    from stt_api import router as stt_router
except Exception as e:
    stt_router = None
    print(f"[WARN] stt_api import failed: {e}")

try:
    from query_test_api import router as query_test_router
except Exception as e:
    query_test_router = None
    print(f"[WARN] query_test_api import failed: {e}")

try:
    from document_api import router as document_router
except Exception as e:
    document_router = None
    print(f"[WARN] document_api import failed: {e}")

try:
    from realtime_analysis_api import router as realtime_router
except Exception as e:
    realtime_router = None
    print(f"[WARN] realtime_analysis_api import failed: {e}")

try:
    from meeting_report_api import router as meeting_report_router
except Exception as e:
    meeting_report_router = None
    print(f"[WARN] meeting_report_api import failed: {e}")

try:
    from chak_runtime_api import app as chak_runtime_app
except Exception as e:
    chak_runtime_app = None
    print(f"[WARN] chak_runtime_api import failed: {e}")

from runtime_routes import router as runtime_router

try:
    from room_api import router as room_router
except Exception as e:
    room_router = None
    print(f"[WARN] room_api import failed: {e}")

try:
    from calendar_api import router as calendar_router
except Exception as e:
    calendar_router = None
    print(f"[WARN] calendar_api import failed: {e}")

app = FastAPI(title="ChakChak 0424test + Sinwoo merged backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if app_config.CORS_ALLOW_ALL else [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "message": "ChakChak merged backend running",
        "general_slm_model": app_config.GENERAL_SLM_MODEL,
        "realtime_slm_model": app_config.REALTIME_SLM_MODEL,
        "whisper_realtime_model": app_config.WHISPER_REALTIME_MODEL_NAME,
        "whisper_upload_model": app_config.WHISPER_UPLOAD_MODEL_NAME,
        "web_search_provider": app_config.WEB_SEARCH_PROVIDER,
        "has_serpapi_key": bool(app_config.SERPAPI_API_KEY and "여기에" not in app_config.SERPAPI_API_KEY),
    }

@app.get("/base-health")
def base_health():
    return {
        "message": "0424test UI/DB base + Sinwoo STT/report merged",
        "realtime_topic": realtime_router is not None,
        "meeting_report": meeting_report_router is not None,
        "chak_runtime": chak_runtime_app is not None,
        "document": document_router is not None,
        "stt": stt_router is not None,
        "mindmap": mindmap_router is not None,
    }

if mindmap_router is not None:
    app.include_router(mindmap_router)

if stt_router is not None:
    app.include_router(stt_router)

if query_test_router is not None:
    app.include_router(query_test_router)

if document_router is not None:
    app.include_router(document_router, prefix="/api/document", tags=["Document"])

if realtime_router is not None:
    app.include_router(realtime_router)

if meeting_report_router is not None:
    app.include_router(meeting_report_router)

# chak_runtime_app의 meeting/session, library/global 라우트 병합
if chak_runtime_app is not None:
    for route in chak_runtime_app.router.routes:
        exists = any(
            getattr(r, "path", None) == getattr(route, "path", None)
            and getattr(r, "methods", None) == getattr(route, "methods", None)
            for r in app.router.routes
        )
        if not exists:
            app.router.routes.append(route)


app.include_router(runtime_router)

if room_router is not None:
    app.include_router(room_router)

if calendar_router is not None:
    app.include_router(calendar_router)