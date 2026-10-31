"""智能知识助理（按教程模板复刻）：左头像 + 气泡对话，答案逐字流式输出。

启动（两个终端）：
    1) .\\.venv\\Scripts\\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000
    2) .\\.venv\\Scripts\\streamlit.exe run 前端页面\\app_chat.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 180
CLOUD, LOCAL = "cloud", "local"
CN = {CLOUD: "云端 DashScope", LOCAL: "本地 Ollama"}

ASSETS = Path(__file__).resolve().parent / "assets"
AVATAR_U = str(ASSETS / "avatar_u.png")
AVATAR_A = str(ASSETS / "avatar_a.png")

EXAMPLES = [
    "公司有多少人啊，一般几点上班下班？",
    "出差住宿费能报多少？",
    "产品保修多久，哪些情况不保修？",
]

st.set_page_config(
    page_title="智能知识助理", page_icon="🤖", layout="centered", initial_sidebar_state="expanded"
)

# ---------------- 样式：对齐视频模板 ----------------
st.markdown(
    """
    <style>
      /* 版心收窄，像聊天窗口 */
      .block-container {max-width: 760px; padding-top: 1.2rem; padding-bottom: 5.5rem;}

      /* 顶部标题 */
      .app-head {display:flex; align-items:center; gap:10px; margin-bottom:2px;}
      .app-head .ic {font-size: 26px; line-height: 1;}
      .app-head .tt {font-size: 22px; font-weight: 700; color:#1B1F24; letter-spacing:.3px;}
      .app-sub {font-size: 13px; color:#8A94A0; margin: 2px 0 12px 36px;}
      .hr {height:1px; background:#EDEFF2; margin: 0 0 18px; border:0;}

      /* 对话行 */
      [data-testid="stChatMessage"] {
          background: transparent; padding: 0; margin-bottom: 14px;
          gap: 12px; align-items: flex-start;
      }
      [data-testid="stChatMessage"] img {
          width: 34px !important; height: 34px !important; border-radius: 50%;
      }
      /* 用户气泡：浅蓝、贴合内容宽度 */
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
          flex-direction: row; background: transparent;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
          [data-testid="stChatMessageContent"] {
          background: #EAF2FD; border-radius: 10px; padding: 12px 16px;
          width: fit-content; max-width: 78%; color:#16202B;
      }
      /* 助手卡片：浅灰、整块圆角 */
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
          [data-testid="stChatMessageContent"] {
          background: #F7F8FA; border-radius: 10px; padding: 16px 18px;
          width: 100%; max-width: 100%; color:#1F2937; font-size: 15px; line-height: 1.75;
      }
      [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] p {margin: 0 0 10px;}
      [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] ul {margin: 4px 0 10px;}
      /* 蓝色强调：加粗文字统一变蓝，对应视频里的“关于XX：”与关键数字 */
      [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] strong {
          color: #1A73E8; font-weight: 600;
      }

      /* 底部输入框 */
      [data-testid="stChatInput"] {
          border: 1px solid #7BA7F0; border-radius: 10px; background: #fff;
          box-shadow: none;
      }
      [data-testid="stChatInput"] textarea {font-size: 14.5px;}
      [data-testid="stChatInputSubmitButton"] {
          background: #6FBF73 !important; color: #fff !important; border-radius: 8px !important;
      }
      [data-testid="stChatInputSubmitButton"]:hover {background: #5EAF62 !important;}

      /* 侧边栏淡一点 */
      [data-testid="stSidebar"] {background: #FAFBFC; border-right: 1px solid #EEF1F4;}
      .empty {font-size: 13px; color:#8A94A0; margin: 4px 0 16px 46px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------- 接口 ----------------
def api(method: str, path: str, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        resp = requests.request(method, f"{API_URL}{path}", **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(f"连不上后端 {API_URL}，请先启动：")
        st.code(
            r".\.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000",
            language="powershell",
        )
        st.stop()
    except requests.exceptions.Timeout:
        st.error("后端超时（本地模型冷启动较慢），请重试。")
        st.stop()
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        st.error(f"后端返回 {resp.status_code}：{detail}")
        st.stop()
    return resp.json()


def stream_answer(question: str, backend: str, model: str | None, box: dict):
    payload = {"question": question, "backend": backend, "model": model}
    with requests.post(f"{API_URL}/api/v1/ask/stream", json=payload, stream=True, timeout=TIMEOUT) as resp:
        if resp.status_code >= 400:
            box["error"] = f"后端返回 {resp.status_code}"
            return
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            try:
                evt = json.loads(raw[6:])
            except json.JSONDecodeError:
                continue
            if evt["type"] == "sources":
                box["sources"] = evt["data"]
            elif evt["type"] == "token":
                yield evt["data"]
            elif evt["type"] == "done":
                box["done"] = evt["data"]
            elif evt["type"] == "error":
                box["error"] = evt["data"]
                return


# ---------------- 侧边栏：知识库与设置 ----------------
with st.sidebar:
    st.markdown("#### 📚 知识库")
    files = st.file_uploader("上传文档（pdf / txt / docx）", type=["pdf", "txt", "docx"],
                             accept_multiple_files=True)
    if files:
        for f in files:
            with st.spinner(f"解析 {f.name}…"):
                info = api("POST", "/api/v1/documents", files={"file": (f.name, f.getvalue())})
            st.caption(f"✅ {info['source']} · {info['chunks']} 块")

    docs = api("GET", "/api/v1/documents")
    if docs:
        for d in docs:
            st.caption(f"📄 {d['source']} · {d['chunks']} 块")
    else:
        st.caption("_还没有文档，先上传一份_")

    col_a, col_b = st.columns(2)
    if col_a.button("清空库", width="stretch"):
        api("DELETE", "/api/v1/documents")
        st.rerun()
    if col_b.button("清空对话", width="stretch"):
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.markdown("#### ⚙️ 推理设置")
    backend_cn = st.radio("生成后端", [CN[CLOUD], CN[LOCAL]], index=0)
    backend = CLOUD if backend_cn == CN[CLOUD] else LOCAL
    model: str | None = None
    if backend == CLOUD:
        model = st.selectbox("云端模型", ["qwen-turbo", "qwen-plus", "qwen-max"], index=1)
    else:
        model = st.text_input("Ollama 模型", value="qwen2.5:7b-instruct-q4_K_M")

    health = api("GET", "/api/v1/health")
    st.caption(
        f"块长 {health['chunk_size']} · 重叠 {health['chunk_overlap']} · Top-K {health['top_k']}\n\n"
        f"向量库 {health['chunk_count']} 块 · {health['embed_model']}"
    )
    if not health["cloud_ready"]:
        st.warning("后端没有 DASHSCOPE_API_KEY，云端模式会失败", icon="⚠️")


# ---------------- 顶部标题 ----------------
health = api("GET", "/api/v1/health")
st.markdown('<div class="app-head"><span class="ic">🤖</span><span class="tt">智能知识助理</span></div>',
            unsafe_allow_html=True)
st.markdown(
    f'<div class="app-sub">基于你的文档库（{len(docs)} 份 · {health["chunk_count"]} 个文本块）的 RAG 问答系统</div>'
    '<hr class="hr">',
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = []


# ---------------- 历史对话 ----------------
if not st.session_state.messages:
    st.markdown('<div class="empty">从下面输入你的问题开始，例如：' + EXAMPLES[0] + '</div>',
                unsafe_allow_html=True)

for msg in st.session_state.messages:
    avatar = AVATAR_U if msg["role"] == "user" else AVATAR_A
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander(f"参考片段 {len(msg['sources'])} 条"):
                for i, s in enumerate(msg["sources"], 1):
                    page = f" · 第 {s['page']} 页" if s.get("page") else ""
                    st.markdown(f"**片段 {i} · {s['source']}{page}**")
                    st.caption(s["content"])
        if msg.get("meta"):
            st.caption(msg["meta"])


# ---------------- 提问 ----------------
question = st.chat_input(f"输入您的问题，例如：{EXAMPLES[1]}") or st.session_state.pop("pending", None)
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=AVATAR_U):
        st.markdown(question)

    with st.chat_message("assistant", avatar=AVATAR_A):
        box: dict = {}
        try:
            answer = st.write_stream(stream_answer(question, backend, model, box))
        except requests.exceptions.ConnectionError:
            st.error(f"连不上后端 {API_URL}")
            st.stop()

        if box.get("error"):
            st.error(f"生成失败：{box['error']}")
            st.session_state.messages.append(
                {"role": "assistant", "content": f"生成失败：{box['error']}"}
            )
        else:
            done = box.get("done", {})
            sources = box.get("sources", [])
            refused = done.get("refused", False)
            if refused:
                st.caption("知识库中没有相关信息，已按固定话术拒答")
            if sources:
                with st.expander(f"参考片段 {len(sources)} 条"):
                    for i, s in enumerate(sources, 1):
                        page = f" · 第 {s['page']} 页" if s.get("page") else ""
                        st.markdown(f"**片段 {i} · {s['source']}{page}**")
                        st.caption(s["content"])
            meta = (
                f"{backend_cn} · {done.get('model', model)} · "
                f"{done.get('elapsed_ms', 0) / 1000:.1f} s"
            )
            st.caption(meta)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer or "",
                    "sources": sources,
                    "refused": refused,
                    "meta": meta,
                }
            )
