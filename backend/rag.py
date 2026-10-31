"""RAG 核心能力，与界面无关，可被 FastAPI / CLI / 测试直接调用。"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from . import config as cfg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 让 prompts.py 可被导入
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.prompts import QA_PROMPT, REFUSAL, is_refusal  # noqa: E402,F401

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader  # noqa: E402
from langchain_community.vectorstores import Chroma  # noqa: E402
from langchain_classic.chains import RetrievalQA  # noqa: E402
from langchain_huggingface import HuggingFaceEmbeddings  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

DB_PATH = str((PROJECT_ROOT / cfg.CHROMA_DB_PATH).resolve())
_COLLECTION_NAME = "langchain"  # langchain_chroma 默认集合名


# 资源（进程内单例）
@lru_cache(maxsize=1)
def get_embedding() -> HuggingFaceEmbeddings:
    """加载本地中文嵌入模型。首次会下载约 100 MB 到 HF 缓存。"""
    return HuggingFaceEmbeddings(
        model_name=cfg.EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

#初始化向量库
@lru_cache(maxsize=1)
def get_vector_db() -> Chroma:
    return Chroma(persist_directory=DB_PATH, embedding_function=get_embedding())


def clear_knowledge_base() -> None:
    """清空知识库（删集合 + 让缓存失效）。"""
    db = get_vector_db()
    try:
        db.delete_collection()
    except Exception:  # 集合不存在时忽略
        pass
    get_vector_db.cache_clear()

def get_api_key() -> str | None:
    value = os.getenv(cfg.API_KEY_ENV)
    return value.strip() if value else None

# 大模型
@lru_cache(maxsize=8)
def build_llm(backend: str, model: str, api_key: str | None):
    """按后端构建 LLM。参数相同则复用实例。"""
    if backend == cfg.BACKEND_LOCAL:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=cfg.OLLAMA_URL,
            temperature=0.0,
            num_ctx=8192,
            timeout=cfg.REQUEST_TIMEOUT * 3,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        base_url=cfg.DASHSCOPE_BASE_URL,
        api_key=api_key,
        temperature=0.0,
        timeout=cfg.REQUEST_TIMEOUT,
        max_tokens=cfg.MAX_TOKENS,
    )

def resolve_model(backend: str, model: str | None) -> str:
    """请求没带模型名时给个默认值。"""
    if model:
        return model
    return cfg.DEFAULT_CLOUD_MODEL if backend == cfg.BACKEND_CLOUD else cfg.OLLAMA_MODEL

def get_qa_chain(llm) -> RetrievalQA:
    retriever = get_vector_db().as_retriever(search_kwargs={"k": cfg.TOP_K})
    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": QA_PROMPT},
    )

# 文档入库
def load_document(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".txt":
        loader = TextLoader(file_path, encoding="utf-8")
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    else:
        raise ValueError(f"不支持的文件格式：{ext}（仅支持 pdf / txt / docx）")
    return loader.load()


def _delete_source(filename: str) -> None:
    """删掉同名文档的旧切块，重复上传按「替换」处理。"""
    try:
        get_vector_db()._collection.delete(where={"source": filename})
    except Exception:  # 集合为空/不存在时忽略
        pass


def ingest_bytes(filename: str, data: bytes) -> int:
    """把一份文件内容切分后写入向量库，返回写入的块数。"""
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in cfg.SUPPORTED_EXTS:
        raise ValueError(f"不支持的文件格式：{suffix}（仅支持 pdf / txt / docx）")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        documents = load_document(tmp_path)
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=cfg.CHUNK_SIZE,
            chunk_overlap=cfg.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", "，", "；", " ", ""],
            length_function=len,
        )
        chunks = splitter.split_documents(documents)
        if not chunks:
            return 0
        for chunk in chunks:          # 来源文件名
            chunk.metadata["source"] = filename
        _delete_source(filename)     # 同名文档先清旧块
        get_vector_db().add_documents(chunks)
        return len(chunks)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

def _metadata_collection():
    """只读元数据用的通道：直接开 Chroma 集合，不加载嵌入模型（否则要等 BGE 冷启动）。"""
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(DB_PATH))
        return client.get_collection(_COLLECTION_NAME)
    except Exception:
        return None


def list_documents() -> list[dict]:
    """列出知识库里已有的文档，以及各自被切成了几块。"""
    collection = _metadata_collection()
    try:
        if collection is not None:
            data = collection.get(include=["metadatas"])
        else:
            data = get_vector_db().get(include=["metadatas"])
    except Exception:
        return []
    counter: dict[str, int] = {}
    for meta in data.get("metadatas") or []:
        name = (meta or {}).get("source", "未知来源")
        counter[name] = counter.get(name, 0) + 1
    return [{"source": k, "chunks": v} for k, v in sorted(counter.items())]


def chunk_count() -> int:
    """向量库里一共有多少块；走元数据通道，几百毫秒内返回。"""
    collection = _metadata_collection()
    if collection is not None:
        try:
            return collection.count()
        except Exception:
            pass
    try:
        return len(get_vector_db().get(include=[])["ids"])
    except Exception:
        return 0


# 问答
def _to_sources(docs) -> list[dict]:
    out = []
    for doc in docs or []:
        page = doc.metadata.get("page")
        out.append(
            {
                "source": doc.metadata.get("source", "未知来源"),
                "page": page + 1 if isinstance(page, int) else None,
                "content": doc.page_content.strip(),
            }
        )
    return out


def answer(question: str, backend: str, model: str | None = None) -> dict:
    """同步问答：一次返回完整答案 + 来源片段 + 耗时。"""
    api_key = get_api_key()
    if backend == cfg.BACKEND_CLOUD and not api_key:
        raise RuntimeError(f"未设置环境变量 {cfg.API_KEY_ENV}，云端后端不可用")

    model = resolve_model(backend, model)
    chain = get_qa_chain(build_llm(backend, model, api_key))

    started = time.perf_counter()
    result = chain.invoke({"query": question})
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    text = result.get("result") or ""
    return {
        "answer": text,
        "refused": is_refusal(text),
        "sources": _to_sources(result.get("source_documents")),
        "elapsed_ms": elapsed_ms,
        "backend": backend,
        "model": model,
    }


def stream_answer(question: str, backend: str, model: str | None = None):
    """流式问答：先 yield ("sources", [...])，再逐 token yield ("token", "…")，
    最后 yield ("done", {...})。供 SSE 接口使用。"""
    api_key = get_api_key()
    if backend == cfg.BACKEND_CLOUD and not api_key:
        raise RuntimeError(f"未设置环境变量 {cfg.API_KEY_ENV}，云端后端不可用")

    model = resolve_model(backend, model)
    llm = build_llm(backend, model, api_key)

    retriever = get_vector_db().as_retriever(search_kwargs={"k": cfg.TOP_K})
    docs = retriever.invoke(question)
    yield "sources", _to_sources(docs)

    context = "\n\n".join(
        f"[片段 {i}]（{d.metadata.get('source', '未知')}）\n{d.page_content}"
        for i, d in enumerate(docs, start=1)
    )
    prompt_value = QA_PROMPT.format(context=context, question=question)

    started = time.perf_counter()
    parts: list[str] = []
    for chunk in llm.stream(prompt_value):
        piece = getattr(chunk, "content", "") or ""
        if piece:
            parts.append(piece)
            yield "token", piece

    text = "".join(parts)
    yield "done", {
        "answer": text,
        "refused": is_refusal(text),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "backend": backend,
        "model": model,
    }
