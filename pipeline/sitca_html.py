"""Parse the data table out of a SITCA IN2105 export page (stdlib only).

The export is an ASP.NET page; the data lives in <table id="ctl00_ContentPlaceHolder1_Table1"> (標準)
or ..._Table2 (費率、銀行與規定).
Cells may contain <br>; we join the text pieces without separators (header cells such as
"基金<br />成立日" become "基金成立日"), and collapse whitespace.
"""
from html.parser import HTMLParser
import re

TABLE_ID_RE = re.compile(r"^ctl00_ContentPlaceHolder1_Table\d$")  # Table1 (標準) / Table2 (費率、銀行與規定)


class _TableParser(HTMLParser):
    def __init__(self, table_id):
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.depth = 0          # nesting depth inside the target table (0 = outside)
        self.rows = []          # list of (is_header_row, [(text, rowspan, colspan), ...])
        self.row = None
        self.cell = None
        self.row_is_header = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            if self.depth == 0 and self.table_id.match(a.get("id") or ""):
                self.depth = 1
            elif self.depth:
                self.depth += 1
            return
        if self.depth != 1:
            return
        if tag == "tr":
            self.row = []
            self.row_is_header = "DTHeader" in (a.get("class") or "")
        elif tag in ("td", "th") and self.row is not None:
            rs = int(a.get("rowspan") or 1)
            cs = int(a.get("colspan") or a.get("ColSpan") or 1)
            self.cell = [[], rs, cs]

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            return
        if self.depth != 1:
            return
        if tag in ("td", "th") and self.cell is not None:
            raw = "".join(self.cell[0])
            # header cells: drop all whitespace ("基金<br />成立日" -> "基金成立日");
            # data cells: collapse runs of whitespace to one space.
            text = re.sub(r"\s+", "", raw) if self.row_is_header else re.sub(r"\s+", " ", raw).strip()
            self.row.append((text, self.cell[1], self.cell[2]))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append((self.row_is_header, self.row))
            self.row = None

    def handle_data(self, data):
        if self.depth == 1 and self.cell is not None:
            self.cell[0].append(data)


def parse_export(html_text):
    """Return (columns, records, meta) where records are dicts keyed by flattened header names."""
    p = _TableParser(TABLE_ID_RE)
    p.feed(html_text)
    p.close()
    header_rows = [r for h, r in p.rows if h]
    data_rows = [r for h, r in p.rows if not h]
    if not header_rows:
        raise ValueError("找不到 SITCA 資料表表頭（網頁格式可能已改變）")
    # Build a grid for header rows honouring rowspan/colspan.
    n_hdr = len(header_rows)
    grid = [[None] * 200 for _ in range(n_hdr)]
    for ri, row in enumerate(header_rows):
        ci = 0
        for text, rs, cs in row:
            while grid[ri][ci] is not None:
                ci += 1
            for dr in range(rs):
                for dc in range(cs):
                    if ri + dr < n_hdr:
                        grid[ri + dr][ci + dc] = (text, dr == 0 and dc == 0)
            ci += cs
    width = max(i + 1 for r in grid for i, c in enumerate(r) if c is not None)
    cols = []
    for ci in range(width):
        parts = []
        for ri in range(n_hdr):
            t = grid[ri][ci][0] if grid[ri][ci] else ""
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        cols.append("_".join(parts))
    records, odd = [], 0
    for row in data_rows:
        vals = [t for t, _, _ in row]
        if len(vals) != width:
            odd += 1
            continue
        records.append(dict(zip(cols, vals)))
    return cols, records, {"header_rows": n_hdr, "data_rows": len(data_rows), "skipped_rows": odd}


def selected_month(html_text):
    """Month selected in the 資料年月 dropdown of the returned page (e.g. '202608')."""
    m = re.search(r'name="ctl00\$ContentPlaceHolder1\$ddlQ_YYYYMM".*?</select>', html_text, re.S)
    if not m:
        return None
    s = re.search(r'<option[^>]*selected="selected"[^>]*value="(\d{6})"', m.group(0)) or \
        re.search(r'<option[^>]*value="(\d{6})"[^>]*selected', m.group(0))
    return s.group(1) if s else None
