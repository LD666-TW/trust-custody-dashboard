#!/usr/bin/env python3
"""每月保管市場看板｜資料處理程式（只用 Python 標準函式庫＋curl）

流程（對應簡報 Demo 1）：
  1. 下載公會開放資料 #43476（境內基金基本資料，級別層級）與 #46443（各項費用，基金層級）
  2. 下載 SITCA〈基金基本資料表〉「標準」與「費率、銀行與規定」（同一資料年月）
  3. 以「基金統編」合併兩份 SITCA 報表（核對配對率）；同一基金不同級別（統編前 8 碼）算 1 檔
  4. 成立日用「標準」報表的基金層級成立日（不用級別成立日）
  5. 計算：保管行三口徑市占與排名、投信客戶數、逐年新基金、主動式 ETF、產品類型歸併、基金明細
  6. 自動檢查；全部通過才寫入 public/data/<年月>.json 並更新 public/data/index.json

用法：
  python3 pipeline/build_data.py --mode auto            # 每日排程：有新月份才重算
  python3 pipeline/build_data.py --month 202608         # 指定月份（需公會開放資料仍是該月，或已有原始檔快取）
  python3 pipeline/build_data.py --month 202608 --offline   # 只用 data/raw/<年月>/ 的快取重算
結束代碼：0＝成功或沒有新月份；1＝下載、格式或檢查失敗（不會覆蓋既有資料）。
"""
import argparse
import calendar
import collections
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch  # noqa: E402
import sitca_html  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
OUT_DIR = os.path.join(ROOT, "public", "data")
CONFIG = os.path.join(ROOT, "config.json")
TZ = dt.timezone(dt.timedelta(hours=8))

RAW_FILES = {
    "funds": "opendata-43476-funds.csv",
    "fees": "opendata-46443-fees.csv",
    "std": "sitca-in2105-standard.html",
    "bank": "sitca-in2105-fee-bank.html",
}


def log(*a):
    print(*a, flush=True)


def now_tw():
    return dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def load_config():
    cfg = {"highlight_bank": "永豐", "pinned_month": "202608", "newfund_window_start": "2025-01-01",
           "max_monthly_change_pct": 10, "stale_after_days": 50}
    if os.path.exists(CONFIG):
        cfg.update(json.load(open(CONFIG, encoding="utf-8")))
    return cfg


# ───────────────────────────── reading raw files ─────────────────────────────

def read_text(path):
    raw = open(path, "rb").read()
    if path.endswith(".gz"):
        raw = gzip.decompress(raw)
    for enc in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv(path):
    return list(csv.DictReader(io.StringIO(read_text(path))))


def csv_month(path):
    rows = read_csv(path)
    months = {r.get("年月", "").strip() for r in rows}
    return rows, months


# ───────────────────────────── naming rules (same as Demo 1) ─────────────────────────────

def short_bank(b):
    b = (b or "").strip()
    return (b.replace("商業銀行股份有限公司", "").replace("國際", "").replace("股份有限公司", "")
             .replace("商業儲蓄銀行", "").replace("臺灣中小企業銀行", "臺企銀")
             .replace("臺灣土地銀行", "土銀").replace("臺灣銀行", "臺銀"))


def norm_bank_full(b):
    """For comparing the open-data bank name (…股份有限公司) with the SITCA report (…商業銀行)."""
    return (b or "").replace("股份有限公司", "").replace(" ", "").strip()


def company(name):
    return (name or "").replace("匯豐", "滙豐").strip()


def type_code(s):
    s = (s or "").strip()
    if s.startswith("("):
        return s[1:].split(")")[0].strip()
    return s.split(" ")[0]


CATEGORY = {"AA": "股票型", "AB": "平衡型", "AC": "固定收益型", "AD": "貨幣市場型", "AE": "組合型",
            "AF": "保本型", "AG": "不動產證券化型", "AH": "ETF", "AI": "指數型", "AJ": "多重資產型",
            "AK": "ETF 連結型", "AL": "主動式 ETF"}

TYPE_GROUPS = [  # 產品類型歸併（與 Demo 1 newfunds-2025-26-by-type 相同）
    ("主動式 ETF", "AL*"), ("被動股票 ETF", "AH11、AH21"), ("債券 ETF", "AH22"),
    ("多重資產／平衡／組合", "AJ*、AE*、AH26"), ("指數基金／ETF 連結", "AI*、AK*"), ("其他", "其餘類型"),
]


def type_group(t):
    t = str(t)
    if t.startswith("AL"):
        return "主動式 ETF"
    if t in ("AH11", "AH21"):
        return "被動股票 ETF"
    if t == "AH22":
        return "債券 ETF"
    if t.startswith("AJ") or t.startswith("AE") or t == "AH26":
        return "多重資產／平衡／組合"
    if t.startswith("AI") or t.startswith("AK"):
        return "指數基金／ETF 連結"
    return "其他"


def is_etf(t):
    return str(t).startswith("AH") or str(t).startswith("AL")


def comp_rank(values):
    """Competition ranking (ties share the same rank): {key: rank}."""
    return {k: 1 + sum(1 for w in values.values() if w > v) for k, v in values.items()}


def pct(a, b, nd=1):
    return round(a / b * 100, nd) if b else 0.0


def ymd(s):
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


# ───────────────────────────── core computation ─────────────────────────────

def compute(month, raw, cfg, sources):
    checks = []

    def check(name, ok, detail, level="fail"):
        checks.append({"name": name, "status": "pass" if ok else level, "detail": detail})
        return ok

    HL = cfg["highlight_bank"]
    funds_rows, funds_months = csv_month(raw["funds"])
    fee_rows, fee_months = csv_month(raw["fees"])
    std_cols, std, std_meta = sitca_html.parse_export(read_text(raw["std"]))
    bank_cols, bnk, bank_meta = sitca_html.parse_export(read_text(raw["bank"]))
    std_month = sitca_html.selected_month(read_text(raw["std"]))
    bank_month = sitca_html.selected_month(read_text(raw["bank"]))
    y, m = int(month[:4]), int(month[4:])
    month_end = f"{y:04d}{m:02d}{calendar.monthrange(y, m)[1]:02d}"

    # 1. 資料年月一致
    check("四份資料的資料年月一致",
          funds_months == {month} and fee_months == {month} and std_month == month and bank_month == month,
          f"開放資料 #43476：{'、'.join(sorted(funds_months))}；#46443：{'、'.join(sorted(fee_months))}；"
          f"SITCA 標準：{std_month}；費率銀行：{bank_month}（目標 {month}）")
    size_dates = collections.Counter(r.get("基金規模日期", "") for r in funds_rows)
    check("基金規模基準日為月底", set(size_dates) == {month_end},
          f"基金規模日期：{'、'.join(f'{k}（{v} 列）' for k, v in size_dates.most_common(3))}")

    # 2. 欄位存在
    need_f = ["統編", "公司名稱", "基金名稱", "基金/級別成立日期", "基金規模(依基金別)_金額", "基金類型別", "保管銀行(國內)"]
    need_s = ["基金統編", "基金成立日", "類型代號"]
    need_b = ["基金統編", "保管銀行(國內)"]
    need_fee = ["基金統編", "月保管費"]
    miss = ([c for c in need_f if c not in (funds_rows[0] if funds_rows else {})] +
            [c for c in need_s if c not in std_cols] + [c for c in need_b if c not in bank_cols] +
            [c for c in need_fee if c not in (fee_rows[0] if fee_rows else {})])
    if not check("必要欄位都在", not miss, "缺少欄位：" + "、".join(miss) if miss else "全部找到"):
        return None, checks

    # 3. 兩份 SITCA 報表以基金統編合併
    std_ids = [r["基金統編"].strip() for r in std]
    bank_ids = [r["基金統編"].strip() for r in bnk]
    s_set, b_set = set(std_ids), set(bank_ids)
    matched = len(s_set & b_set)
    dup = (len(std_ids) - len(s_set)) + (len(bank_ids) - len(b_set))
    check("兩份 SITCA 報表以基金統編合併：全數配對、無重複",
          dup == 0 and matched == len(s_set) == len(b_set) and len(s_set) > 1000,
          f"標準 {len(std_ids):,} 列、費率銀行 {len(bank_ids):,} 列，配對 {matched:,} 列，重複統編 {dup} 個")

    # 4. 統編保留前導零
    lead0 = sum(1 for i in std_ids if i.startswith("0"))
    short_ids = [i for i in std_ids + [r["統編"] for r in funds_rows] if len(i.strip()) < 8]
    check("統編當文字處理，保留前導零", lead0 > 0 and not short_ids,
          f"以 0 開頭的統編 {lead0} 個；長度不足 8 碼的統編 {len(short_ids)} 個")

    # 5. 開放資料與 SITCA 報表涵蓋同一批級別、保管行一致
    od_ids = {r["統編"].strip() for r in funds_rows}
    only_od, only_std = od_ids - s_set, s_set - od_ids
    check("開放資料與 SITCA 報表的級別清單一致", len(only_od) + len(only_std) <= max(5, len(s_set) // 200),
          f"開放資料 {len(od_ids):,} 列；只在開放資料 {len(only_od)} 列、只在 SITCA 報表 {len(only_std)} 列")
    bank_by_id = {r["基金統編"].strip(): norm_bank_full(r["保管銀行(國內)"]) for r in bnk}
    diffs = [r["統編"] for r in funds_rows
             if r["統編"].strip() in bank_by_id and bank_by_id[r["統編"].strip()] != norm_bank_full(r["保管銀行(國內)"])]
    check("保管行欄位：開放資料 vs SITCA 費率銀行報表逐列比對", len(diffs) <= len(od_ids) // 200,
          f"{len(od_ids & set(bank_by_id)):,} 列中 {len(diffs)} 列不同" + (f"（例：{'、'.join(diffs[:5])}）" if diffs else ""))

    # ── 基金層級資料 ──
    est = {}
    for r in std:
        k, d = r["基金統編"].strip()[:8], r["基金成立日"].strip()
        if d.isdigit() and len(d) == 8:
            est[k] = min(est.get(k, "99999999"), d)
    fees = collections.defaultdict(float)
    for r in fee_rows:
        try:
            fees[r["基金統編"].strip()[:8]] += float((r["月保管費"] or "0").replace(",", ""))
        except ValueError:
            pass
    funds = {}
    classes = collections.Counter()
    for r in funds_rows:
        fid = r["統編"].strip()[:8]
        classes[fid] += 1
        if fid in funds:
            continue
        code = type_code(r["基金類型別"])
        funds[fid] = {
            "id": fid, "co": company(r["公司名稱"]), "name": r["基金名稱"].strip(), "code": code,
            "group": type_group(code), "cat": CATEGORY.get(code[:2], "其他"),
            "bank": short_bank(r["保管銀行(國內)"]),
            "aum": float((r["基金規模(依基金別)_金額"] or "0").replace(",", "")),
            "fee": fees.get(fid, 0.0), "est": est.get(fid, ""),
        }
    F = list(funds.values())
    no_est = [f["id"] for f in F if not f["est"]]
    check("每檔基金都有基金層級成立日（取自「標準」報表）", not no_est,
          f"{len(F):,} 檔中缺成立日 {len(no_est)} 檔" + (f"（{'、'.join(no_est[:5])}）" if no_est else ""))
    no_fee = [f["id"] for f in F if f["id"] not in fees]
    check("費用資料涵蓋所有基金", len(no_fee) <= len(F) // 100,
          f"{len(F):,} 檔中 {len(no_fee)} 檔在費用資料找不到", level="warn" if len(no_fee) <= len(F) // 20 else "fail")
    no_bank = [f["id"] for f in F if not f["bank"]]
    check("每檔基金都有國內保管行", not no_bank, f"缺保管行 {len(no_bank)} 檔")

    # ── 保管行三口徑 ──
    tot_n, tot_a, tot_fee = len(F), sum(f["aum"] for f in F), sum(f["fee"] for f in F)
    bk = collections.defaultdict(lambda: {"n": 0, "a": 0.0, "fee": 0.0, "cos": set()})
    for f in F:
        b = bk[f["bank"]]
        b["n"] += 1; b["a"] += f["aum"]; b["fee"] += f["fee"]; b["cos"].add(f["co"])
    rn = comp_rank({k: v["n"] for k, v in bk.items()})
    ra = comp_rank({k: v["a"] for k, v in bk.items()})
    rf = comp_rank({k: v["fee"] for k, v in bk.items()})
    rc = comp_rank({k: len(v["cos"]) for k, v in bk.items()})
    banks = []
    for k, v in sorted(bk.items(), key=lambda x: (-x[1]["n"], -x[1]["a"])):
        banks.append({"bank": k, "n": v["n"], "n_share": pct(v["n"], tot_n), "n_rank": rn[k],
                      "aum": round(v["a"] / 1e8, 2), "aum_share": pct(v["a"], tot_a), "aum_rank": ra[k],
                      "fee": round(v["fee"]), "fee_share": pct(v["fee"], tot_fee), "fee_rank": rf[k],
                      "clients": len(v["cos"]), "clients_rank": rc[k]})
    check(f"重點保管行「{HL}」在資料中", HL in bk, f"保管行共 {len(bk)} 家")

    # ── 逐年新基金（基金層級成立日；只含仍存續基金）──
    years = []
    for yr in (y - 2, y - 1, y):
        YF = [f for f in F if f["est"][:4] == str(yr)]
        yb = collections.defaultdict(lambda: {"n": 0, "a": 0.0, "etf": 0, "active": 0})
        for f in YF:
            b = yb[f["bank"]]
            b["n"] += 1; b["a"] += f["aum"]; b["etf"] += is_etf(f["code"]); b["active"] += f["code"].startswith("AL")
        yn = comp_rank({k: v["n"] for k, v in yb.items()})
        ya = comp_rank({k: v["a"] for k, v in yb.items()})
        ytot_a = sum(f["aum"] for f in YF)
        rows = []
        for k, v in sorted(yb.items(), key=lambda x: (-x[1]["n"], -x[1]["a"])):
            rows.append({"bank": k, "n": v["n"], "share": pct(v["n"], len(YF)), "rank": yn[k],
                         "tied": sum(1 for w in yb.values() if w["n"] == v["n"]) > 1,
                         "aum": round(v["a"] / 1e8, 1), "aum_share": pct(v["a"], ytot_a), "aum_rank": ya[k],
                         "aum_tied": sum(1 for w in yb.values() if round(w["a"]) == round(v["a"])) > 1,
                         "etf": v["etf"], "active": v["active"]})
        years.append({"year": yr, "partial": yr == y and m < 12, "through": f"{yr}-{m:02d}" if yr == y else f"{yr}-12",
                      "total": len(YF), "total_aum": round(ytot_a / 1e8, 1), "banks": rows})

    # ── 主動式 ETF（歷年、仍存續）──
    AL = [f for f in F if f["code"].startswith("AL")]
    al_by = collections.Counter(f["bank"] for f in AL)
    active_etf = {"total": len(AL), "by_bank": [{"bank": k, "n": v} for k, v in al_by.most_common()]}

    # ── 新案期間：產品類型歸併 ──
    w0 = cfg["newfund_window_start"].replace("-", "")
    win = [f for f in F if w0 <= f["est"] <= month_end]
    types = []
    for g, codes in TYPE_GROUPS:
        G = [f for f in win if f["group"] == g]
        if not G:
            continue
        c = collections.Counter(f["bank"] for f in G)
        types.append({"group": g, "codes": codes, "n": len(G), "aum": round(sum(f["aum"] for f in G) / 1e8, 1),
                      "hl": c.get(HL, 0), "top": [{"bank": k, "n": v} for k, v in
                                                   sorted(c.items(), key=lambda x: (-x[1], x[0]))[:3]]})
    types.sort(key=lambda t: -t["n"])

    out = {
        "meta": {
            "month": month, "month_label": f"{y}/{m:02d}", "aum_date": ymd(month_end),
            "generated_at": now_tw(), "highlight": HL,
            "window": {"start": ymd(w0), "end": ymd(month_end), "label": f"{w0[:4]}-{w0[4:6]}～{y}-{m:02d}"},
            "sources": sources,
        },
        "totals": {"funds": tot_n, "classes": sum(classes.values()), "aum": round(tot_a / 1e8, 1),
                   "fee": round(tot_fee), "banks": len(bk), "companies": len({f["co"] for f in F}),
                   "newfunds_window": len(win)},
        "quality": {"std_rows": len(std_ids), "bank_rows": len(bank_ids), "matched": matched,
                    "opendata_rows": len(funds_rows), "fee_rows": len(fee_rows), "bank_diffs": len(diffs)},
        "banks": banks, "years": years, "active_etf": active_etf, "newfund_types": types,
        "funds": sorted(
            ({"id": f["id"], "co": f["co"], "name": f["name"], "code": f["code"], "group": f["group"],
              "cat": f["cat"], "bank": f["bank"], "est": ymd(f["est"]), "aum": round(f["aum"] / 1e8, 2),
              "fee": round(f["fee"])} for f in F),
            key=lambda f: f["est"], reverse=True),
        "checks": checks,
    }
    return out, checks


def compare_previous(out, cfg):
    """Month-over-month sanity check against the previous stored month (if any)."""
    checks = []
    idx = load_index()
    prev = [mm for mm in idx.get("months", []) if mm < out["meta"]["month"]]
    if not prev:
        checks.append({"name": "與上個月比較（檔數、總規模變動）", "status": "pass",
                       "detail": "尚無上個月資料可比較（第一個月）"})
        return checks
    p = json.load(open(os.path.join(OUT_DIR, f"{max(prev)}.json"), encoding="utf-8"))
    lim = cfg["max_monthly_change_pct"]
    dn = pct(out["totals"]["funds"] - p["totals"]["funds"], p["totals"]["funds"])
    da = pct(out["totals"]["aum"] - p["totals"]["aum"], p["totals"]["aum"])
    checks.append({"name": "與上個月比較（檔數、總規模變動）", "status": "pass" if abs(dn) <= lim and abs(da) <= lim else "fail",
                   "detail": f"與 {max(prev)} 相比：檔數 {dn:+.1f}%、總規模 {da:+.1f}%（門檻 ±{lim}%）"})
    new_banks = sorted({b["bank"] for b in out["banks"]} - {b["bank"] for b in p["banks"]})
    checks.append({"name": "保管行名稱沒有出現新寫法", "status": "fail" if new_banks else "pass",
                   "detail": ("新出現：" + "、".join(new_banks) + "（請人工確認是新保管行或名稱改寫）") if new_banks else "與上月相同"})
    return checks


# ───────────────────────────── index / io ─────────────────────────────

def load_index():
    p = os.path.join(OUT_DIR, "index.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"months": []}


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def update_index(month, cfg):
    idx = load_index()
    months = sorted(set(idx.get("months", [])) | {month})
    # 「固定顯示月份」只存在 public/data/index.json 的 pinned 欄位；更新資料時保留原值。
    # 只有第一次建立 index.json 時才用預設值 202608；之後改成 "" 就代表「顯示最新月份」。
    pinned = idx.get("pinned", "") if "updated_at" in idx else cfg.get("pinned_month", "")
    idx = {"months": months, "latest": months[-1], "pinned": pinned or "", "updated_at": now_tw()}
    write_json_atomic(os.path.join(OUT_DIR, "index.json"), idx)
    return idx


def cache_raw(month, files):
    d = os.path.join(RAW_DIR, month)
    os.makedirs(d, exist_ok=True)
    for key, src in files.items():
        dst = os.path.join(d, RAW_FILES[key] + ".gz")
        if src.endswith(".gz"):
            if os.path.abspath(src) != os.path.abspath(dst):
                shutil.copyfile(src, dst)
        else:
            with open(src, "rb") as fi, gzip.GzipFile(dst, "wb", mtime=0) as fo:
                shutil.copyfileobj(fi, fo)


def cached_raw(month):
    d = os.path.join(RAW_DIR, month)
    files = {k: os.path.join(d, v + ".gz") for k, v in RAW_FILES.items()}
    return files if all(os.path.exists(p) for p in files.values()) else None


def unchanged_open_data(idx, work, log):
    """Skip full CSV downloads when neither source changed since the latest saved month."""
    latest = idx.get("latest")
    if not latest:
        return False
    meta_path = os.path.join(RAW_DIR, latest, "sources.json")
    if not os.path.exists(meta_path):
        return False
    saved = {s.get("key"): s for s in json.load(open(meta_path, encoding="utf-8"))}
    probes = {key: fetch.probe_open_data(dataset_id, work, log=log)
              for key, dataset_id in (("funds", "43476"), ("fees", "46443"))}
    return all(probes[key]["last_modified"] and
               probes[key]["last_modified"] == saved.get(key, {}).get("last_modified") and
               probes[key]["url"] == saved.get(key, {}).get("url")
               for key in probes)


def stale_message(idx, cfg):
    """If the newest stored month is overdue, return a message (used to fail the daily job loudly)."""
    have = idx.get("months", [])
    if not have:
        return None
    y, m = int(max(have)[:4]), int(max(have)[4:])
    month_end = dt.date(y, m, calendar.monthrange(y, m)[1])
    if (dt.datetime.now(TZ).date() - month_end).days > cfg["stale_after_days"]:
        return (f"看板最新資料仍是 {max(have)}，下個月的資料理應已公布（已超過月底後 {cfg['stale_after_days']} 天）："
                "請確認公會網站或資料格式是否改變。")
    return None


def set_output(**kw):
    """Expose results to GitHub Actions (no-op locally)."""
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            for k, v in kw.items():
                f.write(f"{k}={v}\n")


# ───────────────────────────── main ─────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["auto", "build"], default="build",
                    help="auto：只有兩份開放資料都出現比現有更新的月份才重算；build：照 --month 重算")
    ap.add_argument("--month", help="資料年月 YYYYMM（build 模式；省略＝開放資料目前的月份）")
    ap.add_argument("--offline", action="store_true", help="只用 data/raw/<年月>/ 的快取，不連網")
    ap.add_argument("--force", action="store_true", help="auto 模式下即使月份沒變也重算")
    args = ap.parse_args()
    if args.month and not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", args.month):
        raise SystemExit(f"--month 格式應為 YYYYMM，例如 202608（收到：{args.month}）")
    cfg = load_config()
    idx = load_index()
    work = tempfile.mkdtemp(prefix="trustdash-")
    sources = []
    try:
        files = None
        if args.offline:
            if not args.month:
                raise SystemExit("--offline 需要搭配 --month")
            files = cached_raw(args.month)
            if not files:
                raise fetch.FetchError(f"找不到 {args.month} 的原始檔快取（data/raw/{args.month}/）")
            month = args.month
            meta_p = os.path.join(RAW_DIR, month, "sources.json")
            sources = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else []
            log(f"使用快取的原始檔重算 {month}")
        else:
            if args.mode == "auto" and not args.force and unchanged_open_data(idx, work, log):
                log("兩份公會檔案的更新時間都未變；不下載完整檔案，也不更新看板。")
                set_output(updated="false")
                msg = stale_message(idx, cfg)
                if msg:
                    log("✗ " + msg)
                    return 1
                return 0
            log("① 下載公會開放資料（#43476、#46443）…")
            fp, fe = os.path.join(work, RAW_FILES["funds"]), os.path.join(work, RAW_FILES["fees"])
            i1 = fetch.fetch_open_data("43476", fp, log=log)
            i2 = fetch.fetch_open_data("46443", fe, log=log)
            _, m1 = csv_month(fp)
            _, m2 = csv_month(fe)
            log(f"  開放資料月份：#43476＝{'、'.join(sorted(m1))}；#46443＝{'、'.join(sorted(m2))}")
            od_month = next(iter(m1)) if len(m1) == 1 and m1 == m2 else None
            if args.mode == "auto":
                have = idx.get("months", [])
                if not od_month or (have and od_month <= max(have) and not args.force):
                    if not od_month:
                        log("兩份開放資料月份還不一致（公會分批上架），今天不更新。")
                    else:
                        log(f"沒有新月份（開放資料 {od_month}，看板已有 {max(have)}），今天不更新。")
                    set_output(updated="false")
                    msg = stale_message(idx, cfg)
                    if msg:
                        log("✗ " + msg)
                        return 1
                    return 0
                month = od_month
            else:
                month = args.month or od_month
                if not month:
                    raise fetch.FetchError("兩份開放資料月份不一致，請用 --month 指定或稍後再試")
                if od_month != month:
                    files = cached_raw(month)
                    if not files:
                        raise fetch.FetchError(
                            f"開放資料目前是 {od_month}，不是 {month}；開放資料只保留最新一個月，"
                            f"且沒有 {month} 的原始檔快取，無法重算規模與保管費。")
                    log(f"開放資料已是 {od_month}；改用 {month} 的原始檔快取重算。")
                    meta_p = os.path.join(RAW_DIR, month, "sources.json")
                    sources = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else []
            if files is None:
                log(f"② 下載 SITCA〈基金基本資料表〉{month}（標準、費率銀行；每份約 30～90 秒）…")
                fs, fb = os.path.join(work, RAW_FILES["std"]), os.path.join(work, RAW_FILES["bank"])
                i3 = fetch.fetch_in2105(month, "1", fs, work, log=log)
                i4 = fetch.fetch_in2105(month, "2", fb, work, log=log)
                files = {"funds": fp, "fees": fe, "std": fs, "bank": fb}
                sources = [
                    {"key": "funds", "name": "投信投顧公會境內基金基本資料", "dataset": "data.gov.tw #43476",
                     "url": i1["url"], "page": "https://data.gov.tw/dataset/43476", "last_modified": i1["last_modified"]},
                    {"key": "fees", "name": "投信投顧公會境內基金各項費用資料", "dataset": "data.gov.tw #46443",
                     "url": i2["url"], "page": "https://data.gov.tw/dataset/46443", "last_modified": i2["last_modified"]},
                    {"key": "std", "name": "SITCA 基金基本資料表（標準）", "dataset": "SITCA IN2105",
                     "url": fetch.IN2105_URL, "page": fetch.IN2105_URL, "last_modified": None},
                    {"key": "bank", "name": "SITCA 基金基本資料表（費率、銀行與規定）", "dataset": "SITCA IN2105",
                     "url": fetch.IN2105_URL, "page": fetch.IN2105_URL, "last_modified": None},
                ]
                for s in sources:
                    if s["last_modified"]:
                        t = dt.datetime.strptime(s["last_modified"], "%a, %d %b %Y %H:%M:%S GMT")
                        s["last_modified_tw"] = t.replace(tzinfo=dt.timezone.utc).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
                    s["fetched_at"] = now_tw()

        log(f"③ 合併、計算、檢查 {month} …")
        out, checks = compute(month, files, cfg, sources)
        if out is not None:
            out["checks"] += compare_previous(out, cfg)
            checks = out["checks"]
        for c in checks:
            mark = {"pass": "✓", "warn": "！", "fail": "✗"}[c["status"]]
            log(f"  {mark} {c['name']}：{c['detail']}")
        failed = [c for c in checks if c["status"] == "fail"]
        if failed:
            log(f"✗ 有 {len(failed)} 項檢查沒通過：不更新看板，維持上一版資料。")
            os.makedirs(os.path.join(ROOT, "data", "reports"), exist_ok=True)
            write_json_atomic(os.path.join(ROOT, "data", "reports", f"{month}-failed.json"),
                              {"month": month, "at": now_tw(), "checks": checks})
            set_output(updated="false", failed="true")
            return 1

        cache_raw(month, files)
        write_json_atomic(os.path.join(RAW_DIR, month, "sources.json"), sources)
        write_json_atomic(os.path.join(OUT_DIR, f"{month}.json"), out)
        new_idx = update_index(month, cfg)
        rep = os.path.join(ROOT, "data", "reports", f"{month}-failed.json")
        if os.path.exists(rep):
            os.remove(rep)
        hl = next((b for b in out["banks"] if b["bank"] == cfg["highlight_bank"]), None)
        if hl:
            log(f"✓ 完成 {month}：{hl['bank']} 檔數 {hl['n_share']}%（第 {hl['n_rank']}）、規模 {hl['aum_share']}%（第 {hl['aum_rank']}）、"
                f"保管費 {hl['fee_share']}%（第 {hl['fee_rank']}）；看板月份清單：{'、'.join(new_idx['months'])}")
        set_output(updated="true", month=month)
        return 0
    except fetch.NotReady as e:
        log(f"尚未就緒：{e}；開放資料已更新但 SITCA 報表尚未上架，明天再試。")
        set_output(updated="false")
        msg = stale_message(idx, cfg)
        if msg:
            log("✗ " + msg)
            return 1
        return 0 if args.mode == "auto" else 1
    except (fetch.FetchError, ValueError, KeyError) as e:
        log(f"✗ 失敗：{e}")
        log("  不更新看板，維持上一版資料。")
        set_output(updated="false", failed="true")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
