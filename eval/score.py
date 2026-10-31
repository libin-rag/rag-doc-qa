# -*- coding: utf-8 -*-
"""把 run_eval.py 的结果表算成指标。

第 1 步：跑 run_eval.py 得到 eval_results.csv
第 2 步：打开 CSV，按「参考答案要点」逐条填「人工判定」列，取值只允许：
        正确 / 部分正确 / 错误 / 编造 / 误拒答 / 正确拒答
    正确      —— 关键事实全部答对，没有编造
    部分正确  —— 答对一部分，或漏了关键限定条件（如只说 500 元没说一线城市）
    错误      —— 答了但与文档不符
    编造      —— 文档里没有的信息，模型自己给了数字/流程（越界题最严重）
    误拒答    —— 可答题却拒答了
    正确拒答  —— 越界题按要求拒答
第 3 步：python score.py

输出：可采纳率 / 完全正确率 / 误拒答率 / 检索命中率 / 越界拒答正确率 / 幻觉率 / 平均与 P95 延时，
      并生成可直接粘进简历的一句话。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

ANSW = ["正确", "部分正确", "错误", "编造", "误拒答", "正确拒答"]
ALIAS = {"拒答正确": "正确拒答", "对": "正确", "错": "错误", "部分对": "部分正确"}


def norm(v) -> str:
    s = str(v or "").strip()
    return ALIAS.get(s, s)


def pct(a, b) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(HERE, "eval_results.csv"))
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        sys.exit("找不到 %s，先跑 run_eval.py" % args.csv)

    df = pd.read_csv(args.csv, dtype=str).fillna("")
    df["判定"] = df["人工判定"].map(norm)

    bad = sorted({v for v in df["判定"] if v and v not in ANSW})
    if bad:
        sys.exit("「人工判定」列有无法识别的取值：%s\n只允许：%s" % (bad, " / ".join(ANSW)))
    blank = df[df["判定"] == ""]
    if len(blank):
        print("⚠ 还有 %d 题没填「人工判定」，未填的题不计入指标：%s\n"
              % (len(blank), ", ".join(blank["序号"].tolist())))
    df = df[df["判定"] != ""]
    if df.empty:
        sys.exit("没有任何已判定的题目，无法计算指标。")

    ans = df[df["类型"] == "可答"]
    out = df[df["类型"] != "可答"]
    n_a, n_o = len(ans), len(out)

    m = {}
    m["题目总数"] = len(df)
    if n_a:
        m["可答题数"] = n_a
        m["可采纳率"] = pct(((ans["判定"] == "正确") | (ans["判定"] == "部分正确")).sum(), n_a)
        m["完全正确率"] = pct((ans["判定"] == "正确").sum(), n_a)
        m["误拒答率"] = pct((ans["判定"] == "误拒答").sum(), n_a)
        m["错误率"] = pct((ans["判定"] == "错误").sum(), n_a)
        m["检索命中率"] = pct((ans["检索命中"] == "是").sum(), n_a)
    if n_o:
        m["越界题数"] = n_o
        m["越界拒答正确率"] = pct((out["判定"] == "正确拒答").sum(), n_o)
        m["幻觉率"] = pct((out["判定"] == "编造").sum(), n_o)
    lat = pd.to_numeric(df["用时秒"], errors="coerce").dropna()
    if len(lat):
        m["平均用时秒"] = round(float(lat.mean()), 2)
        if len(lat) >= 2:
            m["P95用时秒"] = round(float(lat.quantile(0.95, interpolation="higher")), 2)

    print("=" * 56)
    print("评测结果")
    print("=" * 56)
    for k, v in m.items():
        print("%-14s %s%s" % (k, v, "%" if isinstance(v, float) and k not in ("平均用时秒", "P95用时秒") else ""))

    if "可采纳率" in m or "越界拒答正确率" in m:
        print("-" * 56)
        print("写进简历的一句话（把 xx 换成下面的数字）：")
        parts = []
        if n_a:
            parts.append("可采纳率 %s%%" % m["可采纳率"])
        if n_o:
            parts.append("越界问题拒答正确率 %s%%" % m["越界拒答正确率"])
        print("  自建 %d 题评测集（%d 道可答 + %d 道越界），%s。"
              % (len(df), n_a, n_o, "、".join(parts)))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        print("\n指标已写到 %s" % args.json)


if __name__ == "__main__":
    main()
