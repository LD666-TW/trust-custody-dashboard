#!/usr/bin/env python3
"""驗收測試：2026/08 的計算結果必須等於簡報 Demo 1（第 14～16 頁）的數字。

用法：python3 tests/acceptance_202608.py   （先跑過 pipeline/build_data.py --month 202608）
不符合的項目會逐條列出，不會為了通過而調整數字。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "public", "data", "202608.json"), encoding="utf-8"))
B = {b["bank"]: b for b in d["banks"]}
Y = {y["year"]: {b["bank"]: b for b in y["banks"]} | {"_": y} for y in d["years"]}
sp = B["永豐"]
rows = []


def eq(label, got, want, source):
    rows.append((label, got, want, got == want, source))


eq("基金檔數（歸戶後）", d["totals"]["funds"], 1097, "第 13 頁")
eq("級別列數", d["totals"]["classes"], 4427, "第 13 頁")
eq("標準×費率銀行 以統編配對列數", d["quality"]["matched"], 4427, "第 13、17 頁")
eq("開放資料 vs 費率銀行 保管行差異列數", d["quality"]["bank_diffs"], 0, "第 14 頁來源註")
eq("永豐 檔數", sp["n"], 90, "第 14 頁")
eq("永豐 檔數市占 %", sp["n_share"], 8.2, "第 14 頁")
eq("永豐 檔數排名", sp["n_rank"], 4, "第 14 頁")
eq("永豐 規模市占 %", sp["aum_share"], 6.7, "第 14 頁")
eq("永豐 規模排名", sp["aum_rank"], 6, "第 14 頁")
eq("永豐 規模（兆，四捨五入至 0.01）", round(sp["aum"] / 1e4, 2), 1.10, "第 14 頁：1.10 兆")
eq("全市場 規模（兆）", round(d["totals"]["aum"] / 1e4, 2), 16.45, "第 14 頁：16.45 兆")
eq("永豐 8 月保管費市占 %", sp["fee_share"], 8.4, "第 14 頁")
eq("永豐 保管費排名", sp["fee_rank"], 6, "第 14 頁")
eq("永豐 8 月保管費（萬，四捨五入至 10 萬）", round(sp["fee"] / 1e5) * 10, 9070, "第 14 頁：9,070 萬")
eq("全市場 8 月保管費（億）", round(d["totals"]["fee"] / 1e8, 2), 10.79, "第 14 頁：10.79 億")
eq("永豐 投信客戶數", sp["clients"], 19, "demo-prompts ①")
eq("中信／第一／彰化 投信客戶數", [B[k]["clients"] for k in ("中國信託", "第一", "彰化")], [26, 26, 26], "demo-prompts ①")
eq("檔數前 7 名", [b["bank"] for b in sorted(d["banks"], key=lambda b: b["n_rank"])[:7]],
   ["中國信託", "第一", "彰化", "永豐", "玉山", "華南", "兆豐"], "第 14 頁長條圖")
eq("2024 永豐 新案檔數市占 %／名次／並列", (Y[2024]["永豐"]["share"], Y[2024]["永豐"]["rank"], Y[2024]["永豐"]["tied"]), (9.4, 3, True), "第 15 頁")
eq("2025 永豐 新案檔數市占 %／名次／並列", (Y[2025]["永豐"]["share"], Y[2025]["永豐"]["rank"], Y[2025]["永豐"]["tied"]), (4.2, 8, True), "第 15 頁")
eq("2026 永豐 新案檔數市占 %／名次／並列", (Y[2026]["永豐"]["share"], Y[2026]["永豐"]["rank"], Y[2026]["永豐"]["tied"]), (14.5, 2, True), "第 15 頁")
eq("2026 新基金總數／永豐檔數", (Y[2026]["_"]["total"], Y[2026]["永豐"]["n"]), (62, 9), "第 15 頁：9/62")
eq("2026 永豐 以現規模計（億／%／名次）", (round(Y[2026]["永豐"]["aum"]), Y[2026]["永豐"]["aum_share"], Y[2026]["永豐"]["aum_rank"]), (355, 4.7, 6), "第 15 頁")
eq("2026 新基金現規模合計（億）", round(Y[2026]["_"]["total_aum"]), 7514, "demo-prompts ②")
eq("2026 第一：總檔數／ETF 類／主動式 ETF", (Y[2026]["第一"]["n"], Y[2026]["第一"]["etf"], Y[2026]["第一"]["active"]), (11, 8, 4), "第 15 頁")
eq("2026 彰化：總檔數／ETF 類／主動式 ETF", (Y[2026]["彰化"]["n"], Y[2026]["彰化"]["etf"], Y[2026]["彰化"]["active"]), (9, 7, 3), "第 15 頁")
eq("2026 永豐：總檔數／ETF 類／主動式 ETF", (Y[2026]["永豐"]["n"], Y[2026]["永豐"]["etf"], Y[2026]["永豐"]["active"]), (9, 5, 1), "第 15 頁")
eq("2026 以現規模計：彰化／兆豐／第一（億）", tuple(round(Y[2026][k]["aum"]) for k in ("彰化", "兆豐", "第一")), (2256, 1895, 796), "第 15 頁")
al = {x["bank"]: x["n"] for x in d["active_etf"]["by_bank"]}
eq("主動式 ETF 歷年總數／永豐", (d["active_etf"]["total"], al.get("永豐", 0)), (40, 2), "第 15、16 頁：2/40")
eq("新案期間（2025-01～2026-08）新基金數", d["totals"]["newfunds_window"], 133, "research/newfunds-2025-26-by-type.csv")
gp = next(f for f in d["funds"] if f["id"] == "25602535")
eq("群益東方盛世基金 成立日（基金層級，非級別）", gp["est"], "2009-07-29", "第 17 頁「口徑」")

w = max(len(r[0]) for r in rows)
bad = 0
for label, got, want, ok, src in rows:
    bad += not ok
    print(f"{'✓' if ok else '✗'} {label}：看板 {got}｜Demo 1 {want}｜{src}")
print(f"\n{len(rows) - bad}/{len(rows)} 項相符" + ("" if not bad else f"；{bad} 項不符（請檢查，勿強行調整）"))
sys.exit(1 if bad else 0)
