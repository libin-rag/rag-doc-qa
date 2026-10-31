"""前端页面：RAG 能力全部通过 HTTP 调用后端。"""
from __future__ import annotations

import os
import sys

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 180

BACKEND_CLOUD = "cloud"
BACKEND_LOCAL = "local"
CN = {BACKEND_CLOUD: "云端 DashScope", BACKEND_LOCAL: "本地 Ollama"}

st.set_page_config(page_title="RAG 知识库问答系统", layout="wide")


# 后端调用封装
def api(method: str, path: str, **kwargs):
    """统一请求封装，顺带给出可读的错误提示。"""
    url = f"{API_URL}{path}"
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        resp = requests.request(method, url, **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(f"连不上后端 {API_URL} —— 请先在另一个终端启动：")
        st.code(
            r".\.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000",
            language="powershell",
        )
        st.stop()
    except requests.exceptions.Timeout:
        st.error(f"后端 {TIMEOUT} 秒内没有响应，可能是本地模型冷启动，稍后重试或调大 TIMEOUT")
        st.stop()

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        st.error(f"后端返回 {resp.status_code}：{detail}")
        st.stop()
    return resp.json()

# 顶部
st.title("🔍 基于 RAG 的知识库问答系统")
st.caption("分层架构：Streamlit（页面）→ FastAPI（后端）→ 本地嵌入 BGE + Chroma + LLM")

health = api("GET", "/api/v1/health")

# 侧边栏
with st.sidebar:
    st.header("⚙️ 推理后端")
    backend_cn = st.radio(
        "生成模型来源",
        [CN[BACKEND_CLOUD], CN[BACKEND_LOCAL]],
        index=0,
        help="嵌入始终在本地计算；只有「生成」这一步会发往所选后端。",
    )
    backend = BACKEND_CLOUD if backend_cn == CN[BACKEND_CLOUD] else BACKEND_LOCAL

    model: str | None = None
    if backend == BACKEND_CLOUD:
        model = st.selectbox("云端模型", ["qwen-turbo", "qwen-plus", "qwen-max"], index=1)
        if health["cloud_ready"]:
            st.success("后端已检测到 DASHSCOPE_API_KEY")
        else:
            st.error("后端未检测到 DASHSCOPE_API_KEY，云端模式不可用")
            st.code(
                '$env:DASHSCOPE_API_KEY="sk-xxxx"   # 在**后端**那个终端里设置',
                language="powershell",
            )
    else:
        model = st.text_input("Ollama 模型名", value="qwen2.5:7b-instruct-q4_K_M")
        st.caption("需先在系统里跑 `ollama serve`")

    if st.button("🔌 测试后端连通性", use_container_width=True):
        with st.spinner("正在请求模型…"):
            info = api("POST", "/api/v1/test", params={"backend": backend, "model": model})
        st.success(f"连通正常：{info['reply']}（{info['elapsed_ms']} ms）")

    st.divider()
    st.header("📁 知识库管理")
    uploaded_files = st.file_uploader(
        "上传文档（pdf / txt / docx）",
        accept_multiple_files=True,
        type=["pdf", "txt", "docx"],
    )
    if uploaded_files:
        for file in uploaded_files:
            try:
                with st.spinner(f"正在导入 {file.name}…"):
                    info = api(
                        "POST",
                        "/api/v1/documents",
                        files={"file": (file.name, file.getvalue())},
                    )
                st.success(f"✅ {info['source']} 已入库：{info['chunks']} 个文本块")
            except SystemExit:
                raise
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ {file.name} 处理失败：{exc}")

    docs = api("GET", "/api/v1/documents")
    if docs:
        with st.expander(f"📚 已入库 {len(docs)} 个文档", expanded=False):
            for d in docs:
                st.text(f"{d['source']}　—　{d['chunks']} 块")
    else:
        st.caption("知识库还是空的")

    if st.button("🗑️ 清空全部知识库"):
        api("DELETE", "/api/v1/documents")
        st.warning("知识库已清空")

    st.divider()
    st.caption(
        f"参数（后端配置）：块长 {health['chunk_size']} / 重叠 {health['chunk_overlap']} / "
        f"Top-K {health['top_k']}\n\n"
        f"当前块数：{health['chunk_count']}　嵌入：{health['embed_model']}\n\n"
        "答案只依赖检索到的片段，片段里没有就拒答。"
    )
    st.divider()
    st.caption(
        f"本会话：{st.session_state.get('ask_count', 0)} 次提问，"
        f"{st.session_state.get('refuse_count', 0)} 次拒答"
    )
    st.caption(f"后端地址：{API_URL}")
    st.caption(f"前端运行环境：Python {sys.version.split()[0]}")

# 问答
question = st.text_input("💬 请输入你的问题：", placeholder="例如：这件事的处理结果是什么？")
col_ask, col_tip = st.columns([1, 4])
with col_ask:
    ask = st.button("开始提问", type="primary", use_container_width=True)
with col_tip:
    st.caption(f"当前后端：{backend_cn} / {model}")

if ask and question.strip():
    if backend == BACKEND_CLOUD and not health["cloud_ready"]:
        st.error("后端没有 DASHSCOPE_API_KEY，无法使用云端模式")
        st.stop()

    with st.spinner("正在检索知识库并生成答案…"):
        result = api(
            "POST",
            "/api/v1/ask",
            json={"question": question.strip(), "backend": backend, "model": model},
        )

    st.session_state["ask_count"] = st.session_state.get("ask_count", 0) + 1
    if result["refused"]:
        st.session_state["refuse_count"] = st.session_state.get("refuse_count", 0) + 1

    st.markdown("### 📝 回答结果")
    if result["refused"]:
        st.warning("本次判定为「知识库中无相关信息」，已按固定话术拒答（未编造答案）。")
    st.write(result["answer"])
    st.caption(
        f"后端：{backend_cn} / {result['model']}　|　耗时 {result['elapsed_ms'] / 1000:.1f} s　|　"
        f"检索片段 {len(result['sources'])} 条　|　本轮：{'拒答' if result['refused'] else '正常作答'}　|　"
        f"累计 {st.session_state['ask_count']} 问 / {st.session_state.get('refuse_count', 0)} 次拒答"
    )

    with st.expander("📎 参考来源片段", expanded=True):
        if not result["sources"]:
            st.caption("本次没有检索到片段（知识库可能为空，或问题与文档无关）。")
        for idx, src in enumerate(result["sources"], start=1):
            title = f"片段 {idx}　—　{src['source']}"
            if src["page"]:
                title += f"　第 {src['page']} 页"
            st.markdown(f"**{title}**")
            st.text(src["content"])
