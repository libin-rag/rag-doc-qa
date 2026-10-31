"""Prompt 自检：无依据时拒答、有依据时带出处作答。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_ollama import ChatOllama  # noqa: E402

from backend.prompts import QA_PROMPT, REFUSAL, is_refusal  # noqa: E402

MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

CASES = [
    {
        "name": "片段与问题无关 → 应拒答",
        "context": "［片段 1］今天食堂的糖醋里脊有点甜。",
        "question": "火星上有几只猫？",
        "expect_refusal": True,
    },
    {
        "name": "片段含答案 → 应作答且带出处",
        "context": "［片段 1］2023-01-10，股票强大科技A股今日开盘价100人民币，收盘价102人民币，成交量520000。",
        "question": "强大科技A股在 2023-01-10 的收盘价是多少？",
        "expect_refusal": False,
        "must_contain": "102",
    },
    {
        "name": "片段只覆盖一半 → 只答被覆盖部分",
        "context": "［片段 1］比赛于2025年5月10日举行，参赛队伍共八支。",
        "question": "冠军是哪支队伍？比赛共几支队伍？",
        "expect_refusal": False,
        "must_contain": "八",
    },
]


def main() -> int:
    llm = ChatOllama(model=MODEL, base_url=URL, temperature=0.0, num_ctx=8192, timeout=240)
    failed = 0
    for case in CASES:
        prompt = QA_PROMPT.format(context=case["context"], question=case["question"])
        answer = llm.invoke(prompt).content.strip()
        refused = is_refusal(answer)
        ok = refused == case["expect_refusal"]
        if case.get("must_contain"):
            ok = ok and case["must_contain"] in answer
        if case["expect_refusal"]:
            ok = ok and REFUSAL in answer or not case["expect_refusal"]
        print(f"[{'OK  ' if ok else 'FAIL'}] {case['name']}")
        print(f"       输出：{answer[:160].replace(chr(10), ' ')}")
        failed += 0 if ok else 1
    print()
    print(f"{len(CASES) - failed}/{len(CASES)} 通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
