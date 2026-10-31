# RAG 私有文档知识库问答系统

> 面向「私有文档 + 数据不出网」场景的检索增强问答系统。文档在本地解析、本地嵌入、落在本地向量库，生成可选纯本地模型；每个答案带原文出处，片段对不上就拒答。

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.157-009688?logo=fastapi&logoColor=white">
  <img alt="LangChain" src="https://img.shields.io/badge/LangChain-1.6-1C3C3C">
  <img alt="Chroma" src="https://img.shields.io/badge/Chroma-1.5.9-FF6B6B">
</p>

---

## 这个项目解决什么问题

企业或学校里的制度文档（员工手册、差旅报销办法、售后政策）通常是 PDF / DOCX，查一句话要翻十几页；直接把整篇丢给大模型，既会编造，又违反「数据不出网」。两难之下，需要同时满足三件事：

| 约束 | 由此产生的设计 |
|---|---|
| **数据不出网** | 嵌入模型用本地 `BAAI/bge-small-zh`（CPU 可跑），向量库落本地 Chroma；生成可选纯本地 Ollama |
| **答案要能核对** | 每个结论后用 `［片段 N］` 标注出处，前端可展开「参考片段」看原文 |
| **不能编造** | 提示词 9 条硬约束 + `temperature=0`；片段无关时输出**固定拒答话术**，可被程序识别与统计 |

---

## 功能

- **一条龙入库**：上传 PDF / DOCX / TXT → 解析 → 按中文标点优先级切块 → 本地嵌入 → 写入 Chroma，同名文件按 `source` **先删后写**，重复上传不产生重复切片
- **带出处的回答**：Top-3 余弦检索，答案里每个结论标注片段编号，前端把片段原文并排展示
- **越界拒答**：拒答使用固定话术而非自由发挥，因此 `refused` 可程序判定，越界问题不进入生成环节
- **双生成后端**：同一接口按 `backend=local|cloud` 在 Ollama（qwen2.5:7b，零调用成本）与 DashScope（qwen-plus）之间切换，密钥只从环境变量读
- **SSE 流式**：按 `sources → token × N → done/error` 四类事件推送，检索完成即先推 `sources`，**首屏反馈不等全文生成**
- **两种前端**：原生 HTML/CSS/JS 单页（FastAPI 直接托管，无构建、无 CDN）+ 早期 Streamlit 版本，都调同一套 HTTP 接口
- **可复现的评测**：30 题基础集 + 10 题困难集 + 一键跑批脚本，指标定义写在代码里而非口头

---

## 架构

```
                  ┌──────────────────────────────────────────┐
   浏览器          │  frontend/   index.html + app.js + css   │
   :8000/   ←──────┤  原生 ES Module，无构建、无 CDN           │
                  └────────────────┬─────────────────────────┘
                                   │ fetch / SSE
                  ┌────────────────▼─────────────────────────┐
                  │  FastAPI   backend/main.py                │
                  │  8 条 /api/v1/* 路由 + 静态托管 + CORS     │
                  └───────┬──────────────────────┬───────────┘
                          │                      │
              ┌───────────▼─────────┐   ┌────────▼─────────────┐
              │ rag.py 检索 + 生成   │   │ schemas.py Pydantic  │
              │  · Chroma Top-3     │   │  入参/出参校验        │
              │  · RetrievalQA      │   └──────────────────────┘
              └──┬───────────────┬──┘
                 │               │
    ┌────────────▼──────┐   ┌────▼──────────────────────────┐
    │ BGE 本地嵌入       │   │ 生成：ChatOllama / ChatOpenAI  │
    │ sentence-         │   │  （DashScope OpenAI 兼容模式）  │
    │ transformers      │   └───────────────────────────────┘
    └────────────┬──────┘
          ┌──────▼────────┐
          │   chroma_db/  │  持久化向量 + metadata(source, page)
          └───────────────┘
```

一句话数据流：**文件 → 解析 → 切块 → 本地嵌入 → 存向量 → 问题嵌入 → Top-3 检索 → 拼 Prompt → 生成 → 带出处返回**。

---

## 快速开始

**环境**：Python 3.11+（开发用 3.14）。嵌入模型首次运行会从 HF 镜像下载约 100 MB。

```bash
git clone https://github.com/libin-rag/rag-doc-qa.git
cd rag-doc-qa
pip install -r requirements.txt
```

```bash
# 可选：本地生成后端（不装则只能走云端）
ollama serve
ollama pull qwen2.5:7b-instruct-q4_K_M

# 可选：云端生成后端
export DASHSCOPE_API_KEY="sk-..."        # Windows PowerShell: $env:DASHSCOPE_API_KEY="sk-..."

# 启动
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

| 打开 | 用途 |
|---|---|
| <http://127.0.0.1:8000/> | Web 前端（上传、提问、切换后端、看状态） |
| <http://127.0.0.1:8000/docs> | Swagger 在线调试，每条路由有中文说明与示例响应 |

`requirements.txt` 里 `torch` 体积较大；只做接口调试、不跑嵌入时可先跳过，但入库功能会不可用。

---

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/ping` | 最轻量存活探针，不碰模型（7 ms 级） |
| GET | `/api/v1/health` | 模型名、块长/重叠、Top-K、当前块数、云端 Key 是否就绪 |
| GET | `/api/v1/documents` | 已入库文档及各自块数 |
| POST | `/api/v1/documents` | 上传入库（`multipart`，字段 `file`），同名先删后写 |
| DELETE | `/api/v1/documents` | 清空知识库 |
| POST | `/api/v1/test?backend=cloud` | 探活一次模型调用 |
| POST | `/api/v1/ask` | 同步问答，返回答案 + `refused` + `sources` + 耗时 |
| POST | `/api/v1/ask/stream` | SSE 流式，`sources → token... → done` |

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"试用期多久？","backend":"local"}'
```

```jsonc
{
  "answer": "试用期为 6 个月，试用期工资为转正工资的 80%［片段 1］",
  "refused": false,
  "sources": [{ "source": "员工手册.docx", "page": null, "content": "……" }],
  "elapsed_ms": 953, "backend": "local", "model": "qwen2.5:7b-instruct-q4_K_M"
}
```

**错误约定**：参数不合法 400、格式不支持 400、解析失败 500、切出 0 块 422、模型不可用 503。

---

## 评测

题库在 `eval/`：30 题基础集（20 题可答 + 10 题越界）+ 10 题困难集（跨条款组合、需要算术）。语料是 3 份示例制度文档（`eval/docs/`）。

| 组别 | 指标 | 结果 |
|---|---|---|
| 基础集 · 20 题可答 | 检索命中 / 可采纳 / 完全正确 | 20/20 · 20/20 · 20/20 |
| 基础集 · 10 题越界 | 越界拒答正确率 | 10/10 |
| 困难集 · 10 题 | 可采纳 / 完全正确 | 10/10 · **9/10** |
| 延迟（30 题，本地 7B q4） | 平均 / P95 | 1.33 s · 3.02 s |

困难集里唯一失分的是 H8：模型答对了规则，但**多补了一句原文没有的处理方式**。基础集 100% 只说明语料干净、答案集中在单一条款内；困难集才是暴露问题的地方——这也是保留「可采纳率」与「完全正确率」两个指标的原因，后者更严格，能把「答了一半」和「答对了」区分开。

> ⚠️ 上述数字在**自建的 3 份示例文档**上得到，换成真实企业文档（附件、表格、跨文档引用）一定会下降，不能直接外推。

复现：

```bash
python eval/run_eval.py --limit 3      # 冒烟 3 题
python eval/run_eval.py                # 全量，写 eval/eval_results.csv
# 打开 CSV 按「参考答案要点」逐题填「人工判定」列
python eval/score.py                   # 输出指标；--json 可存 json
```

`eval/results_baseline.csv` 是已判分的历史结果，可直接 `python eval/score.py --csv eval/results_baseline.csv` 复算指标。

---

## 关键设计决策

| 决策 | 理由 | 代价 |
|---|---|---|
| 嵌入必须本地 | 文档不出网是硬约束；CPU 单条约 30–80 ms | 中文语义精度不如云端大模型嵌入 |
| 双生成后端共用一个接口 | 离线演示用 Ollama，追求质量用 qwen-plus，切换只改一个字段 | 两套模型要照顾同一份 Prompt |
| `chain_type="stuff"` | 3 个片段一次进上下文，一次调用，最快最省 | 片段多了会超上下文 |
| `temperature=0` | 制度问答要照抄原文，不要创意 | 答案偏机械 |
| 拒答用固定话术 | 可机读、可统计越界拒答率 | 说法不如自然语言友好 |
| Chroma 而非 FAISS | 需要持久化 + metadata 溯源 + 能按 `source` 删单文档 | 生态比 FAISS 轻，但够用 |
| 同名文件先删后写 | 修掉「重复上传块数翻倍、Top-K 名额被旧片段占满」 | 每次上传多一次删除 |
| 块 800 / 重叠 150 / Top-3 | 中文制度文档实测：再小会切断条款，再大召回不准 | 参数偏经验值，尚未系统调参 |
| 健康检查走 Chroma 元数据通道 | 原实现要加载 BGE，冷启动 20 s+，页面像卡死；现在 7 ms | 多一条代码路径 |

可调参数集中在 `backend/config.py`，支持环境变量覆盖（`CHROMA_DB_PATH` / `OLLAMA_URL` / `OLLAMA_MODEL` 等）。

---

## 项目结构

```
.
├── backend/                 后端包（入口 backend.main:app）
│   ├── config.py            全部可调参数 + HF 镜像（必须在 import 前设）
│   ├── prompts.py           9 条硬约束 Prompt + 固定拒答话术 + is_refusal()
│   ├── rag.py               切块、嵌入、入库、检索、生成、流式
│   ├── schemas.py           AskRequest / AskResponse / DocumentInfo / HealthResponse
│   └── main.py              8 条路由 + 静态托管 + CORS
├── frontend/                原生 HTML/CSS/JS 前端（无构建、无 CDN）
├── streamlit_frontend/      早期 Streamlit 版本（表单式 / 对话式），保留对比
├── eval/                    评测：题库、语料、跑批与判分脚本、基线结果
├── tests/                   Prompt 自检（拒答 / 带出处），需 Ollama 在线
├── requirements.txt
└── README.md
```

三个前端调的是**同一套** `/api/v1/*`，换前端不动后端一行代码。

---

## 已知限制与路线图

| 类别 | 现状 | 下一步 |
|---|---|---|
| 检索 | 纯向量 Top-3，对编号、专有名词、跨条款召回弱 | BM25 + 向量混合检索，再用 `bge-reranker` 精排 |
| 链式 API | 仍在用 `langchain_classic` 的 `RetrievalQA` | 迁到 LCEL（`prompt \| llm \| parser`） |
| 多轮对话 | 每问独立，无历史 | 加 `session_id` + 最近 N 轮拼接，控制 token 预算 |
| 鉴权 | 无；CORS 为 `*` | 内网够用，对外需 API Key 并把 CORS 收紧 |
| 文件类型 | 无 OCR、无表格解析 | 扫描件接 PaddleOCR，表格用 `pdfplumber` / `unstructured` |
| 部署 | 单机单进程 | Docker + uvicorn workers，前端交给 Nginx |
| 评测 | 示例语料 + 人工填判定 | 真实文档、扩到百题量级、LLM-as-judge + 人工抽检 |

---

## 说明

个人学习与求职项目，代码为独立完成。语料与题库均为自建示例数据，不含任何真实企业文档。欢迎提 issue 交流。
