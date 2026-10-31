"""API 的数据契约（Pydantic 模型）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    backend: Literal["cloud", "local"] = Field("cloud", description="生成后端")#literal 约束性最强的类型注解
    model: str | None = Field(None, description="模型名；云端默认 qwen-plus，本地默认 cfg.OLLAMA_MODEL")


class SourceChunk(BaseModel):
    source: str = Field(..., description="来源文件名")
    page: int | None = Field(None, description="PDF 页码（从 1 开始）；非 PDF 为 null")
    content: str = Field(..., description="命中的原文片段")


class AskResponse(BaseModel):
    answer: str
    refused: bool = Field(..., description="是否触发了固定拒答话术")
    sources: list[SourceChunk] = Field(default_factory=list)
    elapsed_ms: int = Field(..., description="检索 + 生成总耗时（毫秒）")
    backend: str
    model: str


class DocumentInfo(BaseModel):
    source: str
    chunks: int


class HealthResponse(BaseModel):
    status: str
    embed_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    chunk_count: int
    cloud_ready: bool = Field(..., description="是否检测到 DASHSCOPE_API_KEY")
