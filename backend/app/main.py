"""FastAPI 应用入口"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, interview, resume, users
from app.config import settings
from app.database import init_db
from app.rag.indexing import ensure_question_index, seed_question_bank

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # RAG：预置题库 + 建立向量索引（各自优雅降级，失败不影响启动）
    await seed_question_bank()
    await ensure_question_index()
    yield


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(resume.router)
app.include_router(interview.router)
app.include_router(users.router)
app.include_router(users.admin_router)


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health")
async def health():
    return {"status": "ok"}
