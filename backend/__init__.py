"""RAG 后端包：嵌入、向量库、切分、检索、生成，不依赖 Streamlit。"""

from .config import (  # noqa: F401
    BACKEND_CLOUD,
    BACKEND_LOCAL,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DEFAULT_CLOUD_MODEL,
    EMBED_MODEL,
    TOP_K,
)
