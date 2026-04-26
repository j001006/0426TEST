# 고정 실행 설정
# 공개 GitHub에 올릴 거면 SERPAPI_API_KEY는 실제 키 대신 빈 문자열로 두는 것을 권장.

OLLAMA_BASE_URL = "http://127.0.0.1:11434"

GENERAL_SLM_MODEL = "qwen2.5:3b"
REALTIME_SLM_MODEL = "qwen2.5:3b"

WHISPER_REALTIME_MODEL_NAME = "base"
WHISPER_UPLOAD_MODEL_NAME = "medium"
WHISPER_LANGUAGE = "ko"

WEB_SEARCH_PROVIDER = "serpapi"
SERPAPI_API_KEY = "f6d83ec294da6f12cb2370349fdf0ceaeb0982249a6ac7d59fec139329c16ffa"
SERPAPI_ENGINE = "google"
SERPAPI_GL = "kr"
SERPAPI_HL = "ko"
SERPAPI_LOCATION = "South Korea"

DATABASE_FILE = "stt.sqlite3"
MEETING_APP_DB_FILE = "meeting_app.sqlite3"

CORS_ALLOW_ALL = True
