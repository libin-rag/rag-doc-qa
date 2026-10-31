"""FastAPI 后端入口。启动：uvicorn backend.main:app --reload；文档：/docs"""
from __future__ import annotations

import json
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfg
from . import rag
from .schemas import AskRequest, AskResponse, DocumentInfo, HealthResponse

app = FastAPI(
    title="RAG 知识库问答 API",
    description="本地嵌入（BGE）+ Chroma 检索 + 可选生成后端（DashScope / Ollama）",
    version="1.0.0",
)

# 跨域：前端 Streamlit 直连
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# 前端页面目录（frontend/index.html + app.js + styles.css）
WEB_DIR = Path(__file__).resolve().parent.parent / "frontend"
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# 系统
@app.get("/", include_in_schema=False)
def index():
    """首页：有前端就发页面，没有就返回服务信息。"""
    page = WEB_DIR / "index.html"
    if page.is_file():
        return FileResponse(page)
    return {"service": "rag-api", "docs": "/docs", "health": "/api/v1/health"}


@app.get("/api/v1/ping", tags=["系统"], summary="服务探针")
def ping():
    """不依赖向量库与模型的最轻量探针，用于存活检查。"""
    return {"service": "rag-api", "docs": "/docs", "health": "/api/v1/health"}


@app.get("/api/v1/health", response_model=HealthResponse, tags=["系统"], summary="健康检查")
def health():
    """服务状态与当前生效的检索参数。"""
    return HealthResponse(
        status="ok",
        embed_model=cfg.EMBED_MODEL,
        chunk_size=cfg.CHUNK_SIZE,
        chunk_overlap=cfg.CHUNK_OVERLAP,
        top_k=cfg.TOP_K,
        chunk_count=rag.chunk_count(),
        cloud_ready=rag.get_api_key() is not None,
    )


# 知识库管理
@app.get("/api/v1/documents", response_model=list[DocumentInfo], tags=["知识库"], summary="列出已入库文档")
def documents():
    """每份文档及其切片数；重复上传按 source 覆盖旧切片。"""
    return rag.list_documents()


@app.post(
    "/api/v1/documents",
    response_model=DocumentInfo,
    tags=["知识库"],
    summary="上传并入库文档",
    responses={
        400: {"description": "文件是空的，或扩展名/编码不受支持"},
        422: {"description": "文档解析成功，但没切出任何文本"},
        500: {"description": "文档解析过程中抛出异常"},
    },
)
async def upload_document(
    file: UploadFile = File(..., description="支持 .pdf / .txt / .docx，表单字段名固定为 file"),
):
    """上传文档：切块 → 本地 BGE 向量化 → 写入 Chroma，返回本次写入的切片数。"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    try:
        chunks = rag.ingest_bytes(file.filename or "unknown.txt", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"解析失败：{exc}") from exc

    if chunks == 0:
        raise HTTPException(status_code=422, detail="没有从文件里解析出任何文本")
    return DocumentInfo(source=file.filename or "unknown", chunks=chunks)


@app.delete("/api/v1/documents", tags=["知识库"], summary="清空知识库")
def clear_documents():
    """清空向量库里的全部切片，不动磁盘上的原文件。"""
    rag.clear_knowledge_base()
    return {"ok": True, "message": "知识库已清空"}


# 问答
@app.post(
    "/api/v1/test",
    tags=["问答"],
    summary="测试生成后端连通性",
    responses={503: {"description": "模型不可用：key 缺失 / Ollama 未启动 / 网络不通"}},
)
def test_backend(
    backend: str = Query(cfg.BACKEND_CLOUD, description="生成后端：cloud（DashScope）或 local（本地 Ollama）"),
    model: str | None = Query(None, description="模型名；留空使用该后端的默认模型"),
):
    """用一句最短提示词测生成链路，不经过检索。"""
    try:
        llm = rag.build_llm(backend, rag.resolve_model(backend, model), rag.get_api_key())
        started = time.perf_counter()
        reply = llm.invoke("回复两个字：正常")
        return {
            "ok": True,
            "reply": (getattr(reply, "content", "") or "").strip(),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"后端不可用：{exc}") from exc


@app.post(
    "/api/v1/ask",
    response_model=AskResponse,
    tags=["问答"],
    summary="同步问答（一次性返回完整答案）",
    responses={
        400: {"description": "参数不合法，例如选了 cloud 后端但没配置 DASHSCOPE_API_KEY"},
        500: {"description": "生成过程中抛出异常"},
    },
)
def ask(req: AskRequest):
    """检索 Top-K 片段，拼进 QA_PROMPT 后一次性返回答案与来源。"""
    try:
        result = rag.answer(req.question.strip(), req.backend, req.model)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生成失败：{exc}") from exc
    return AskResponse(**result)


@app.post("/api/v1/ask/stream", tags=["问答"], summary="流式问答（SSE 边检索边吐字）")
def ask_stream(req: AskRequest):
    """SSE 流式返回：sources → 若干 token → done，出错则以 error 结束。"""

    def event_stream():
        try:
            for kind, payload in rag.stream_answer(req.question.strip(), req.backend, req.model):
                yield f"data: {json.dumps({'type': kind, 'data': payload}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'data': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)