from query_test_api import router as  query_test_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mindmap_api import router as mindmap_router
from stt_api import router as stt_router

# --- [종범추가] DB 설정과 새 라우터 불러오기 ---
from database import engine
import models
from document_api import router as document_router
from realtime_analysis_api import router as realtime_router
# ---------------------------------------------

# --- [종범추가] 서버 실행 시 DB 테이블 자동 생성 ---
models.Base.metadata.create_all(bind=engine)
# ---------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mindmap_router)
app.include_router(stt_router)
app.include_router(query_test_router)

# --- [종범추가] 문서 추출 API 라우터 등록 ---
# prefix를 붙여서 주소를 깔끔하게 그룹화합니다.
app.include_router(document_router, prefix="/api/document", tags=["Document"])

app.include_router(realtime_router)

app.include_router(document_router, prefix="/api/document", tags=["Document"])
# -------------------------------------------