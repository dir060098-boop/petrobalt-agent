import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import mk as mk_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

app = FastAPI(
    title="Petrobalt Agent API",
    description="AI-агент расчёта материалов и поиска поставщиков",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ───────────────────────────────────────────────────────────────────────
# Разрешённые origins: локальная разработка + продакшн (Railway/Vercel/кастомный)
_default_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]
_extra = os.getenv("ALLOWED_ORIGINS", "")  # через запятую: https://my.app.com,...
_extra_origins = [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роутеры
app.include_router(mk_router.router)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": "0.1.0"}
