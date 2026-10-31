# -*- coding: utf-8 -*-
"""批量跑评测：把 docs 目录里的文档灌进一个临时 Chroma，逐题问 RAG 链路，导出结果表。

用法（在 eval 目录下）：
    python run_eval.py                                   # 用默认参数跑全部题目
    python run_eval.py --limit 3                         # 先跑 3 题冒烟
    python run_eval.py --model qwen2.5:7b --k 3

输出 eval_results.csv：题目 + 参考答案要点 + 模型回答 + 是否拒答 + 检索命中 + 用时 + 空白的「人工判定」列。
人工判定填：正确 / 部分正确 / 错误 / 编造 / 误拒答
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import shutil
import sys
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 国内下载 BGE 走镜像

import pandas as pd
from langchain_classic.chains import RetrievalQA
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from langchain_text_splitters import RecursiveCharacterTextSplitter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from backend.prompts import QA_PROMPT, REFUSAL, is_refusal  # noqa: E402  复用项目里的同一份 Prompt

CHUNK_SIZE, CHUNK_OVERLAP = 800, 150
EMBED_MODEL = "BAAI/bge-small-zh"
OLLAMA_URL = "http://127.0.0.1:11434"


def load_docs(folder: str):
    docs = []
    for path in sorted(glob.glob(os.path.join(folder, "*"))):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            parts = PyPDFLoader(path).load()
        elif ext == ".txt":
            parts = TextLoader(path, encoding="utf-8").load()
        elif ext == ".docx":
            parts = Docx2txtLoader(path).load()
        else:
            continue
        for d in parts:
            d.metadata["source"] = os.path.basename(path)
        docs.extend(parts)
    if not docs:
        raise SystemExit("docs 目录里没有可读文档（支持 pdf / txt / docx）")
    return docs


def build_store(docs, persist_dir: str) -> Chroma:
    if os.path.isdir(persist_dir):
        shutil.rmtree(persist_dir)
    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "，", "；", " ", ""],
        length_function=len,
    )
    return Chroma.from_documents(
        splitter.split_documents(docs), emb, persist_directory=persist_dir
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default=os.path.join(HERE, "docs"))
    ap.add_argument("--questions", default=os.path.join(HERE, "questions.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "eval_results.csv"))
    ap.add_argument("--persist", default=os.path.join(HERE, "chroma_eval"))
    ap.add_argument("--model", default="qwen2.5:7b-instruct-q4_K_M")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print("[1/3] 载入文档并建索引 …")
    docs = load_docs(args.docs)
    store = build_store(docs, args.persist)
    chunks = store._collection.count()
    print("      文档 %d 个，切块 %d 个" % (len({d.metadata['source'] for d in docs}), chunks))

    llm = ChatOllama(model=args.model, base_url=OLLAMA_URL, temperature=0.0,
                     num_ctx=8192, timeout=180)
    qa = RetrievalQA.from_chain_type(
        llm=llm, chain_type="stuff",
        retriever=store.as_retriever(search_kwargs={"k": args.k}),
        return_source_documents=True,
        chain_type_kwargs={"prompt": QA_PROMPT},
    )

    qs = pd.read_csv(args.questions, dtype=str).fillna("")
    if args.limit:
        qs = qs.head(args.limit)

    print("[2/3] 逐题提问（共 %d 题）…" % len(qs))
    rows = []
    for i, r in enumerate(qs.itertuples(index=False), 1):
        t0 = time.time()
        try:
            res = qa.invoke({"query": r.问题})
            answer = (res.get("result") or "").strip()
            srcs = res.get("source_documents") or []
        except Exception as exc:  # 单题失败不中断整批
            answer, srcs = "[调用失败] %s" % exc, []
        cost = time.time() - t0

        hit_files = []
        for d in srcs:
            name = os.path.basename(str(d.metadata.get("source", "")))
            if name not in hit_files:
                hit_files.append(name)
        expect = r.应命中文件.strip()
        # 只比文件名主干，避免题库写 .txt 而语料是 .docx 时误判为未命中
        expect_stem = os.path.splitext(expect)[0]
        hit = "" if not expect else (
            "是" if any(os.path.splitext(f)[0] == expect_stem for f in hit_files) else "否"
        )

        rows.append({
            "序号": r.序号, "类型": r.类型, "问题": r.问题,
            "参考答案要点": r.参考答案要点,
            "模型回答": answer.replace("\n", " ")[:600],
            "是否拒答": "是" if is_refusal(answer) else "否",
            "检索来源": " / ".join(hit_files),
            "检索命中": hit,
            "用时秒": round(cost, 2),
            "人工判定": "",
        })
        print("      %2s. %-6s %-28s %5.2fs %s" % (
            r.序号, r.类型, r.问题[:28], cost, "拒答" if is_refusal(answer) else "作答"))

    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print("[3/3] 已写出 %s" % args.out)
    print("      拒答 %d 次；平均用时 %.2fs" % (
        (df["是否拒答"] == "是").sum(), df["用时秒"].mean()))
    print("      下一步：打开该 CSV，按「参考答案要点」逐条填「人工判定」，再跑 score.py")


if __name__ == "__main__":
    main()
