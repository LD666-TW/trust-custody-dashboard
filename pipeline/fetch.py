"""Download SITCA public data with curl (stdlib + curl only).

Why curl: SITCA's TLS certificate lacks a Subject Key Identifier, which Python 3.13's
default *strict* X.509 verification rejects. curl (OpenSSL with the system CA bundle)
verifies the same chain normally, so we keep full certificate verification by delegating
HTTPS to curl instead of weakening Python's SSL settings.
"""
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse

UA = "Mozilla/5.0 (trust-dashboard monthly update; public open data)"

OPEN_DATA = {
    # data.gov.tw dataset id -> (title, SITCA download URL as listed on data.gov.tw)
    "43476": ("投信投顧公會境內基金基本資料",
              "https://www.sitca.org.tw/MemberK0000/F/03/43476投信投顧公會境內基金基本資料.csv"),
    "46443": ("投信投顧公會境內基金各項費用資料",
              "https://www.sitca.org.tw/MemberK0000/F/03/46443投信投顧公會境內基金各項費用資料.csv"),
}
DATAGOV_API = "https://data.gov.tw/api/v2/rest/dataset/{id}"
IN2105_URL = "https://www.sitca.org.tw/ROC/Industry/IN2105.aspx?pid=IN2212_02"
IN2105_COLUMNS = {"1": "標準", "2": "費率、銀行與規定"}


class FetchError(RuntimeError):
    pass


class NotReady(FetchError):
    """The requested month is not published on the SITCA page yet."""


def _quote_url(url):
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path)))


def curl(url, out_path, *, timeout=240, retries=3, data_file=None, cookie_jar=None, log=print):
    """Fetch url into out_path. Returns dict(status, last_modified, bytes, seconds)."""
    url = _quote_url(url)
    last_err = None
    for attempt in range(1, retries + 1):
        hdr = out_path + ".hdr"
        cmd = ["curl", "-sS", "--fail", "-L", "-A", UA, "-m", str(timeout), "--connect-timeout", "30",
               "-D", hdr, "-o", out_path, "-w", "%{http_code} %{size_download} %{time_total}"]
        if cookie_jar:
            cmd += ["-b", cookie_jar, "-c", cookie_jar]
        if data_file:
            cmd += ["--data-binary", "@" + data_file, "-H", "Content-Type: application/x-www-form-urlencoded"]
        cmd.append(url)
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            code, size, secs = r.stdout.split()
            lm = None
            try:
                for line in open(hdr, encoding="latin-1"):
                    if line.lower().startswith("last-modified:"):
                        lm = line.split(":", 1)[1].strip()
            finally:
                if os.path.exists(hdr):
                    os.remove(hdr)
            log(f"  下載完成 {url[:80]}… HTTP {code}，{int(float(size)):,} bytes，{float(secs):.0f} 秒")
            return {"status": int(code), "last_modified": lm, "bytes": int(float(size)), "seconds": round(float(secs), 1)}
        last_err = (r.stderr or r.stdout).strip()
        log(f"  第 {attempt} 次下載失敗（{time.time() - t0:.0f} 秒）：{last_err}")
        if os.path.exists(hdr):
            os.remove(hdr)
        time.sleep(10 * attempt)
    raise FetchError(f"下載失敗：{url}：{last_err}")


def open_data_url(dataset_id, log=print):
    """Current download URL; asks data.gov.tw in case the listed URL ever changes."""
    default = OPEN_DATA[dataset_id][1]
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name
        curl(DATAGOV_API.format(id=dataset_id), tmp, timeout=60, retries=2, log=lambda *_: None)
        meta = json.load(open(tmp, encoding="utf-8"))
        os.remove(tmp)
        for d in meta.get("result", {}).get("distribution", []):
            u = d.get("resourceDownloadUrl")
            if u and u.lower().endswith(".csv"):
                if u != default:
                    log(f"  注意：data.gov.tw 上 #{dataset_id} 的下載網址已改為 {u}")
                return u
    except Exception as e:  # metadata lookup is only a convenience
        log(f"  （data.gov.tw 資料集說明查詢失敗，改用既有網址：{e}）")
    return default


def fetch_open_data(dataset_id, out_path, log=print):
    url = open_data_url(dataset_id, log=log)
    info = curl(url, out_path, timeout=300, log=log)
    info["url"] = url
    return info


def probe_open_data(dataset_id, workdir, log=print):
    """Read one byte plus response headers to detect a changed public CSV."""
    url = open_data_url(dataset_id, log=log)
    hdr = os.path.join(workdir, f"probe-{dataset_id}.hdr")
    body = os.path.join(workdir, f"probe-{dataset_id}.body")
    cmd = ["curl", "-sS", "--fail", "-L", "-A", UA, "-m", "60",
           "--connect-timeout", "30", "--range", "0-0", "-D", hdr,
           "-o", body, "-w", "%{http_code} %{size_download}", _quote_url(url)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise FetchError(f"檢查 #{dataset_id} 更新時間失敗：{r.stderr.strip()}")
    try:
        status, size = r.stdout.split()
        modified = None
        for line in open(hdr, encoding="latin-1"):
            if line.lower().startswith("last-modified:"):
                modified = line.split(":", 1)[1].strip()
        # Only a 206 response with a usable timestamp is a reliable shortcut.
        # If the server ignores Range or omits Last-Modified, caller downloads normally.
        usable = status == "206" and int(float(size)) <= 1 and bool(modified)
        log(f"  #{dataset_id} 輕量檢查：{'可比較更新時間' if usable else '需下載確認'}")
        return {"url": url, "last_modified": modified if usable else None}
    finally:
        for path in (hdr, body):
            if os.path.exists(path):
                os.remove(path)


def _hidden(html, name):
    m = re.search(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html)
    if not m:
        raise FetchError(f"SITCA 網頁找不到欄位 {name}（網頁格式可能已改變）")
    return m.group(1)


def fetch_in2105(month, column, out_path, workdir, log=print):
    """Export the SITCA 基金基本資料表 for `month` (YYYYMM or None=latest), column '1' or '2'."""
    jar = os.path.join(workdir, f"in2105_{column}.cookies")
    page = os.path.join(workdir, f"in2105_{column}_form.html")
    curl(IN2105_URL, page, timeout=180, cookie_jar=jar, log=log)
    html = open(page, encoding="utf-8", errors="replace").read()
    months = re.findall(r'<option[^>]*value="(\d{6})"', html)
    if not months:
        raise FetchError("SITCA 網頁找不到「資料年月」選單（網頁格式可能已改變）")
    month = month or max(months)
    if month not in months:
        raise NotReady(f"SITCA 網頁尚無 {month} 的資料（目前最新 {max(months)}）")
    P = "ctl00$ContentPlaceHolder1$"
    form = {
        "__VIEWSTATE": _hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _hidden(html, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _hidden(html, "__EVENTVALIDATION"),
        P + "ddlQ_YYYYMM": month, P + "ddlQ_Column": column, P + "ddlQ_Comid": "",
        P + "ddlQ_FundNo": "", P + "txtQ_KeyWord": "", P + "BtnExport": "匯出",
        P + "sLSTMENDDATE": _hidden(html, P + "sLSTMENDDATE"),
        P + "sLST2MENDDATE": _hidden(html, P + "sLST2MENDDATE"),
    }
    form_file = os.path.join(workdir, f"in2105_{column}.form")
    open(form_file, "w").write(urllib.parse.urlencode(form))
    info = curl(IN2105_URL, out_path, timeout=420, data_file=form_file, cookie_jar=jar, log=log)
    info.update(url=IN2105_URL, month=month, column=IN2105_COLUMNS[column], latest_available=max(months))
    return info
