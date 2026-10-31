/**
 * 智能知识助理 · 前端逻辑（无框架、无构建步骤）
 * 与 FastAPI 后端通过 /api/v1/* 的 REST + SSE 接口通信。
 */

/* ---------------------------------------------------------------- 基础 */

// 直接用 file:// 打开本文件时，退回到本地默认地址；由后端托管时用同源相对路径。
const API = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const els = {
  sidebar: $("#sidebar"),
  toggleSidebar: $("#toggle-sidebar"),
  fileInput: $("#file-input"),
  drop: $("#drop"),
  docList: $("#doc-list"),
  clearDocs: $("#clear-docs"),
  backend: $("#backend"),
  modelCloud: $("#model-cloud"),
  modelLocal: $("#model-local"),
  testBackend: $("#test-backend"),
  health: {
    chunks: $("#m-chunks"),
    embed: $("#m-embed"),
    chunk: $("#m-chunk"),
    topk: $("#m-topk"),
    key: $("#m-key"),
    url: $("#m-url"),
  },
  subtitle: $("#subtitle"),
  newChat: $("#new-chat"),
  chat: $("#chat"),
  msgs: $("#msgs"),
  empty: $("#empty"),
  chips: $("#chips"),
  composer: $("#composer"),
  input: $("#input"),
  send: $("#send"),
  toasts: $("#toasts"),
};

const SUGGESTIONS = [
  "公司有多少人？一般几点上下班？",
  "试用期多久，工资怎么算？",
  "出差住酒店的标准是多少？",
  "产品整机保修多久？",
];

const state = {
  docs: [],
  busy: false,
  messages: [], // { role: 'user' | 'assistant', text, sources?, refused?, meta?, error? }
};

/* ---------------------------------------------------------------- 工具 */

function toast(message, kind = "info", timeout = 3600) {
  const node = document.createElement("div");
  node.className = `toast toast--${kind}`;
  node.textContent = message;
  els.toasts.append(node);
  setTimeout(() => node.remove(), timeout);
}

const escapeHtml = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

/** 极简 Markdown → HTML：够用即可，且先转义再套标签，避免注入。 */
function mdToHtml(src) {
  const inline = (text) =>
    escapeHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,，。；;]|$)/g, "$1<em>$2</em>");

  const lines = String(src ?? "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let list = null; // 'ul' | 'ol'
  let para = [];
  let fence = null; // 代码块内容

  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${inline(para.join(" "))}</p>`);
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      out.push(`</${list}>`);
      list = null;
    }
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");

    if (fence !== null) {
      if (/^\s*```/.test(line)) {
        out.push(`<pre><code>${escapeHtml(fence.join("\n"))}</code></pre>`);
        fence = null;
      } else {
        fence.push(raw);
      }
      continue;
    }
    if (/^\s*```/.test(line)) {
      flushPara();
      flushList();
      fence = [];
      continue;
    }
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushPara();
      flushList();
      const level = Math.min(4, heading[1].length + 2);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bullet) {
      flushPara();
      if (list !== "ul") {
        flushList();
        out.push("<ul>");
        list = "ul";
      }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }

    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (numbered) {
      flushPara();
      if (list !== "ol") {
        flushList();
        out.push("<ol>");
        list = "ol";
      }
      out.push(`<li>${inline(numbered[1])}</li>`);
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      flushPara();
      flushList();
      out.push(`<blockquote>${inline(line.replace(/^\s*>\s?/, ""))}</blockquote>`);
      continue;
    }

    flushList();
    para.push(line.trim());
  }

  if (fence !== null) out.push(`<pre><code>${escapeHtml(fence.join("\n"))}</code></pre>`);
  flushPara();
  flushList();
  return out.join("\n");
}

const fmtSeconds = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);

/* ---------------------------------------------------------------- API */

async function api(path, { method = "GET", body, form, timeout = 60000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const init = { method, signal: controller.signal, headers: {} };
    if (form) {
      init.body = form;
    } else if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(API + path, init);
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) {
      const detail = data && typeof data === "object" ? data.detail : data;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

/* ---------------------------------------------------------------- 侧边栏 */

function currentModel() {
  return els.backend.value === "local" ? els.modelLocal.value.trim() : els.modelCloud.value;
}

function syncBackendFields() {
  const local = els.backend.value === "local";
  els.modelCloud.classList.toggle("hidden", local);
  els.modelLocal.classList.toggle("hidden", !local);
}

function renderDocs() {
  els.docList.innerHTML = "";
  if (!state.docs.length) {
    const li = document.createElement("li");
    li.className = "empty-line";
    li.textContent = "还没有文档";
    els.docList.append(li);
    return;
  }
  for (const doc of state.docs) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "doc-name";
    name.textContent = doc.source;
    name.title = doc.source;
    const chunks = document.createElement("span");
    chunks.className = "doc-chunks";
    chunks.textContent = `${doc.chunks} 块`;
    li.append(name, chunks);
    els.docList.append(li);
  }
}

function renderHealth(h) {
  els.health.chunks.textContent = `${h.chunk_count} 块`;
  els.health.embed.textContent = h.embed_model;
  els.health.chunk.textContent = `${h.chunk_size} / ${h.chunk_overlap}`;
  els.health.topk.textContent = String(h.top_k);
  els.health.key.innerHTML = h.cloud_ready
    ? '<span class="dot-ok">已配置</span>'
    : '<span class="dot-bad">未配置</span>';
  els.health.url.textContent = API || location.origin;
  els.subtitle.textContent = `基于你的文档库（${state.docs.length} 份 · ${h.chunk_count} 个文本块）的 RAG 问答系统`;
}

async function refreshHealth() {
  try {
    const health = await api("/api/v1/health");
    renderHealth(health);
  } catch (err) {
    els.subtitle.textContent = "后端未连接 —— 请先启动 uvicorn";
    toast(`连不上后端：${err.message}`, "error", 6000);
  }
}

async function refreshDocs() {
  try {
    state.docs = await api("/api/v1/documents");
    renderDocs();
  } catch {
    /* 状态条已经提示过 */
  }
}

async function uploadFiles(files) {
  const list = Array.from(files || []);
  if (!list.length) return;
  for (const file of list) {
    const form = new FormData();
    form.append("file", file, file.name);
    const node = toast(`上传 ${file.name} …`, "info", 60000);
    try {
      const res = await api("/api/v1/documents", { method: "POST", form, timeout: 180000 });
      node.textContent = `${file.name}：${res.chunks} 个文本块`;
      node.className = "toast toast--ok";
      setTimeout(() => node.remove(), 2500);
    } catch (err) {
      node.textContent = `${file.name} 上传失败：${err.message}`;
      node.className = "toast toast--error";
      setTimeout(() => node.remove(), 6000);
    }
  }
  await refreshDocs();
  await refreshHealth();
}

async function clearDocs() {
  if (!state.docs.length) return;
  if (!confirm(`确定清空知识库？当前 ${state.docs.length} 份文档会被全部删除。`)) return;
  try {
    await api("/api/v1/documents", { method: "DELETE" });
    toast("知识库已清空", "ok");
    await refreshDocs();
    await refreshHealth();
  } catch (err) {
    toast(`清空失败：${err.message}`, "error");
  }
}

async function testBackend() {
  const model = currentModel();
  const btn = els.testBackend;
  btn.disabled = true;
  btn.textContent = "测试中…";
  try {
    const res = await api(
      `/api/v1/test?backend=${encodeURIComponent(els.backend.value)}&model=${encodeURIComponent(model)}`,
      { method: "POST", timeout: 120000 }
    );
    toast(`连通正常（${res.backend} / ${res.model}）：${res.reply}`, "ok", 5000);
  } catch (err) {
    toast(`连通失败：${err.message}`, "error", 6000);
  } finally {
    btn.disabled = false;
    btn.textContent = "测试连通性";
  }
}

/* ---------------------------------------------------------------- 消息渲染 */

function messageNode(msg) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg--${msg.role === "user" ? "user" : "assistant"}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar avatar--${msg.role === "user" ? "u" : "a"}`;
  avatar.textContent = msg.role === "user" ? "U" : "A";

  if (msg.role === "user") {
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = msg.text;
    wrap.append(avatar, bubble);
    return wrap;
  }

  const card = document.createElement("div");
  card.className = `card${msg.error ? " is-error" : ""}`;

  const body = document.createElement("div");
  body.className = "md";
  if (msg.pending) {
    body.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  } else {
    body.innerHTML = mdToHtml(msg.text);
  }
  card.append(body);

  if (msg.sources && msg.sources.length) {
    const details = document.createElement("details");
    details.className = "sources";
    const summary = document.createElement("summary");
    summary.textContent = `参考片段 ${msg.sources.length} 条`;
    details.append(summary);
    for (const s of msg.sources) {
      const item = document.createElement("div");
      item.className = "source-item";
      const head = document.createElement("b");
      head.textContent = s.page ? `${s.source} · 第 ${s.page} 页` : s.source;
      const quote = document.createElement("div");
      quote.className = "quote";
      quote.textContent = s.content;
      item.append(head, quote);
      details.append(item);
    }
    card.append(details);
  }

  if (msg.meta) {
    const meta = document.createElement("div");
    meta.className = "meta-line";
    if (msg.refused) {
      const tag = document.createElement("span");
      tag.className = "refused-tag";
      tag.textContent = "已拒答";
      meta.append(tag);
    }
    meta.append(msg.meta);
    card.append(meta);
  }

  wrap.append(avatar, card);
  return wrap;
}

function renderMessages() {
  els.msgs.innerHTML = "";
  els.empty.classList.toggle("hidden", state.messages.length > 0);
  for (const msg of state.messages) els.msgs.append(messageNode(msg));
  scrollToBottom();
}

function scrollToBottom() {
  els.chat.scrollTop = els.chat.scrollHeight;
}

function persist() {
  try {
    sessionStorage.setItem("rag-chat", JSON.stringify(state.messages));
  } catch {
    /* 隐私模式下忽略 */
  }
}

function restore() {
  try {
    const raw = sessionStorage.getItem("rag-chat");
    if (raw) state.messages = JSON.parse(raw);
  } catch {
    state.messages = [];
  }
}

/* ---------------------------------------------------------------- 提问 */

function setBusy(busy) {
  state.busy = busy;
  els.send.disabled = busy;
  els.send.textContent = busy ? "生成中…" : "发送";
}

async function ask(question) {
  if (state.busy) return;
  const text = question.trim();
  if (!text) return;

  state.messages.push({ role: "user", text });
  const reply = { role: "assistant", text: "", pending: true };
  state.messages.push(reply);
  renderMessages();
  persist();

  setBusy(true);
  els.input.value = "";
  autoGrow();

  const model = currentModel();
  const startedAt = performance.now();
  let sources = [];
  let bodyEl = null; // 流式追加时只更新这一个 <div class="md">，避免整块重排

  try {
    const res = await fetch(`${API}/api/v1/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text, backend: els.backend.value, model }),
    });
    if (!res.ok || !res.body) {
      const detail = await res.text().catch(() => "");
      throw new Error(detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");

        let event = "message";
        const dataLines = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;

        let payload;
        try {
          payload = JSON.parse(dataLines.join("\n"));
        } catch {
          payload = { type: "token", data: dataLines.join("\n") };
        }
        const type = payload.type || event;

        if (type === "sources") {
          sources = payload.data || [];
          reply.sources = sources;
          if (!bodyEl) renderMessages();
        } else if (type === "token") {
          if (reply.pending) {
            reply.pending = false;
            reply.text = "";
            renderMessages();
            bodyEl = els.msgs.lastElementChild?.querySelector(".md") || null;
          }
          reply.text += payload.data ?? "";
          if (bodyEl) {
            bodyEl.innerHTML = mdToHtml(reply.text);
            scrollToBottom();
          } else {
            renderMessages();
          }
        } else if (type === "done") {
          reply.pending = false;
          reply.refused = Boolean(payload.data && payload.data.refused);
          const elapsed =
            (payload.data && payload.data.elapsed_ms) || performance.now() - startedAt;
          reply.meta = `${els.backend.value === "local" ? "本地 Ollama" : "云端 DashScope"} · ${model} · ${fmtSeconds(elapsed)}`;
          renderMessages();
          persist();
        } else if (type === "error") {
          throw new Error(payload.data || "生成失败");
        }
      }
    }

    if (reply.pending) {
      reply.pending = false;
      reply.text = reply.text || "（没有收到内容）";
      reply.meta = `${model} · ${fmtSeconds(performance.now() - startedAt)}`;
    }
  } catch (err) {
    reply.pending = false;
    reply.error = true;
    reply.text = `请求失败：${err.message}\n\n请确认后端已启动（\`uvicorn backend.main:app --port 8000\`），以及所选模型可用。`;
  } finally {
    setBusy(false);
    renderMessages();
    persist();
    els.input.focus();
  }
}

/* ---------------------------------------------------------------- 输入框 */

function autoGrow() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 180)}px`;
}

/* ---------------------------------------------------------------- 事件绑定 */

function bind() {
  els.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    ask(els.input.value);
  });

  els.input.addEventListener("input", autoGrow);
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      ask(els.input.value);
    }
  });

  els.fileInput.addEventListener("change", async (e) => {
    await uploadFiles(e.target.files);
    e.target.value = "";
  });

  for (const type of ["dragenter", "dragover"]) {
    els.drop.addEventListener(type, (e) => {
      e.preventDefault();
      els.drop.classList.add("is-over");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    els.drop.addEventListener(type, (e) => {
      e.preventDefault();
      els.drop.classList.remove("is-over");
    });
  }
  els.drop.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

  els.clearDocs.addEventListener("click", clearDocs);
  els.testBackend.addEventListener("click", testBackend);
  els.backend.addEventListener("change", syncBackendFields);

  els.newChat.addEventListener("click", () => {
    if (state.busy) return;
    state.messages = [];
    renderMessages();
    persist();
    els.input.focus();
  });

  els.toggleSidebar.addEventListener("click", () => els.sidebar.classList.toggle("is-open"));

  els.chips.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) ask(chip.dataset.q);
  });
}

/* ---------------------------------------------------------------- 启动 */

async function main() {
  els.chips.innerHTML = SUGGESTIONS.map(
    (q) => `<button class="chip" type="button" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`
  ).join("");

  restore();
  renderDocs();
  renderMessages();
  bind();
  syncBackendFields();

  await Promise.all([refreshHealth(), refreshDocs().then(refreshHealth)]);
  els.input.focus();
}

main();
