# 前端说明（HTML 版）

不用 Streamlit 的版本：纯 HTML + CSS + 原生 JavaScript（ES Module），由 FastAPI 直接托管，
**没有 Node、没有构建步骤、没有 CDN 依赖**，克隆下来就能跑。

## 目录

```
frontend/
├── index.html   页面骨架（侧边栏 / 顶栏 / 消息区 / 输入框 / Toast）
├── styles.css   设计令牌 + 布局 + 深浅色主题（prefers-color-scheme 自动切换）
└── app.js       接口调用、SSE 流式解析、极简 Markdown 渲染、状态管理
```

后端在 `backend/main.py` 里挂载：

```python
WEB_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")
```

## 启动

```powershell
cd C:\Users\李斌\PycharmProjects\PythonProject2
.\.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开 <http://127.0.0.1:8000/>。接口文档仍在 <http://127.0.0.1:8000/docs>。

## 页面用到的接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 返回 `index.html` |
| GET | `/static/*` | JS / CSS |
| GET | `/api/v1/health` | 嵌入模型、块参数、Top-K、云 Key 是否就绪、块数 |
| GET | `/api/v1/documents` | 文档列表（文件名 + 切片数） |
| POST | `/api/v1/documents` | 上传（multipart，字段名 `file`），返回 `{source, chunks}` |
| DELETE | `/api/v1/documents` | 清空知识库 |
| POST | `/api/v1/test?backend=&model=` | 探活一次模型调用 |
| POST | `/api/v1/ask` | 同步问答，返回 `{answer, refused, sources[], elapsed_ms}` |
| POST | `/api/v1/ask/stream` | SSE：`sources` → `token`×N → `done`（`refused` / `elapsed_ms` / `backend` / `model`） |
| GET | `/api/v1/ping` | 最轻量存活探针 |

## 前端实现要点

- **SSE 用 fetch 读流**，不是 `EventSource`：因为要 POST JSON。按 `\n\n` 切帧、解析 `data:` 行，
  依次处理 `sources / token / done / error` 四种事件。
- **流式渲染只更新当前气泡的 `.md` 节点**，不重建整个列表（否则长回答会 O(n²) 重排）。
- **Markdown 渲染是手写的极小实现**：先 `escapeHtml` 再套 `<strong>/<code>/<ul>/<pre>`，
  因此模型输出里的 `<script>` 之类一定是纯文本，不存在 XSS。
- **会话存在 `sessionStorage`**，刷新不丢；「新建对话」清空。
- **拖拽上传**、上传进度 Toast、失败提示、后端未启动时的错误气泡。
- 快捷键：`Enter` 发送，`Shift+Enter` 换行；输入框随内容高度自适应。
- 响应式：≤940px 时侧边栏收成抽屉（左上角 ☰）。

## 自测过的内容

| 检查 | 结果 |
|---|---|
| `TestClient` 取 `/` | 200，`text/html`，含「智能知识助理」，引用 `/static/app.js`、`/static/styles.css` |
| `/static/app.js`、`/static/styles.css` | 200，`text/javascript` / `text/css` |
| `node --check app.js` | 语法 OK |
| Markdown 渲染单测（8 个用例） | 加粗/列表/标题/代码/引用正常；`<script>`、`<img onerror>` 均被转义 |
| SSE 帧格式 | `data: {"type":"sources"|"token"|"done","data":…}`，前端拼接后答案与 `refused`、`elapsed_ms` 一致 |
| 真实链路（本地 Ollama） | `/ask` 200「试用期 6 个月，工资为转正的 80%［片段 1］」；流式 20 个 token、1.0 s；越界题正确拒答 |

## 与 Streamlit 版的关系

`前端页面/app.py`（表单版）和 `前端页面/app_chat.py`（对话版）都保留着，可以同时跑对比。
HTML 版只是换了展示层，`backend/` 一行没动逻辑。
