"""集中配置，改参数只改这一处。"""
from __future__ import annotations

import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 检索参数
CHUNK_SIZE = 800          # 文本块大小
CHUNK_OVERLAP = 150       # 块间重叠
TOP_K = 3                 # 检索返回片段数
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "chroma_db")   # 向量库目录
EMBED_MODEL = "BAAI/bge-small-zh"                            # 本地中文嵌入（CPU 可跑）

# 生成后端
BACKEND_LOCAL = "local"
BACKEND_CLOUD = "cloud"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CLOUD_MODELS = ["qwen-turbo", "qwen-plus", "qwen-max"]
DEFAULT_CLOUD_MODEL = "qwen-plus"
API_KEY_ENV = "DASHSCOPE_API_KEY"

REQUEST_TIMEOUT = 60      # 秒
MAX_TOKENS = 2048         # 单次生成上限

SUPPORTED_EXTS = {".pdf", ".txt", ".docx"}
