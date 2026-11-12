"""raw/ 의 HWP/HWPX/ZIP 파일을 읽어 site/data/ 에 검색용 JSON을 만든다.

    pip install pyhwp six lxml pypdf pdfplumber
    python scripts/build.py
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lxml import etree, html as lhtml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "site", "data")

ART_RE = re.compile(r"^\s*(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*(\(([^)]*)\))?")
CHAP_RE = re.compile(r"^\s*제\s*\d+\s*(장|절|관)(\s|$)")
ADDENDA_RE = re.compile(r"^\s*부\s*칙")
ANNEX_RE = re.compile(r"^\s*[\[〔【]?\s*(별\s*표|별\s*지|별\s*첨|붙\s*임)([^\]〕】\[]{0,25})[\]〕】]\s*(.*)$")


def annex_title(rest):
    """'[별표 3] 채용시험 가점대상자 및 가점(제13조제5항 관련)' 의 뒷부분에서 제목만"""
    t = re.sub(r"<[^>]*>", "", rest)
    t = re.sub(r"\(\s*제\s*\d+[^)]*관련\s*\)", "", t)
    return t.strip()
WS = re.compile(r"[ \t 　]+")


def clean(s):
    s = s.replace("\r", "").replace("​", "")
    lines = [WS.sub(" ", ln).strip() for ln in s.split("\n")]
    lines = [ln.replace(" ", "") if SPACED.match(ln) else ln for ln in lines]
    return "\n".join(ln for ln in lines if ln)


# "재 직 증 명 서", "본    적" 처럼 글자 사이를 띄워 쓴 줄 → 붙여서 (검색도 되게)
SPACED = re.compile(r"^[가-힣]( [가-힣])+$")


# ---------- HWP (v5) via pyhwp ----------

def hwp_blocks(path):
    tmp = tempfile.mkdtemp()
    try:
        out = os.path.join(tmp, "o.html")
        exe = shutil.which("hwp5html") or os.path.join(os.path.dirname(sys.executable), "hwp5html")
        subprocess.run([exe, "--html", "--output", out, path], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with open(out, "rb") as f:
            doc = lhtml.fromstring(f.read())
        css = ""
        try:
            cssf = os.path.join(tmp, "o.css")
            subprocess.run([exe, "--css", "--output", cssf, path], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            with open(cssf, encoding="utf-8", errors="ignore") as f:
                css = f.read()
        except Exception:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    global HWP_STYLE
    HWP_STYLE = parse_hwp_css(css)
    HWP_FULLTEXT[_md5(path)] = doc.find(".//body").text_content()
    return html_blocks(doc)


HWP_FULLTEXT = {}


def _md5(path_or_bytes):
    import hashlib
    if isinstance(path_or_bytes, bytes):
        return hashlib.md5(path_or_bytes).hexdigest()
    with open(path_or_bytes, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


HWP_STYLE = ({}, {})


def parse_hwp_css(css):
    """parashape-N -> 정렬(l/c/r), charshape-N -> 글자크기(pt)"""
    align, size = {}, {}
    for m in re.finditer(r"p\.parashape-(\d+)\s*\{([^}]*)\}", css):
        a = re.search(r"text-align:\s*(\w+)", m.group(2))
        if a:
            align[m.group(1)] = {"center": "c", "right": "r"}.get(a.group(1), "l")
    for m in re.finditer(r"span\.charshape-(\d+)\s*\{([^}]*)\}", css):
        z = re.search(r"font-size:\s*([\d.]+)pt", m.group(2))
        if z:
            size[m.group(1)] = float(z.group(1))
    return align, size


def _cls_num(el, prefix):
    for c in (el.get("class") or "").split():
        if c.startswith(prefix):
            return c[len(prefix):]
    return None


def finish_cell(cell, lines):
    """lines: [(text, align, size)] -> cell 에 t / a / la / big 채움"""
    out = []
    for t, a, z in lines:
        for ln in clean(t).split("\n"):
            if ln:
                out.append((ln, a or "l", z or 0))
    cell["t"] = "\n".join(x[0] for x in out)
    al = [x[1] for x in out]
    if al and len(set(al)) == 1:
        if al[0] != "l":
            cell["a"] = al[0]
    elif al:
        cell["la"] = "".join(al)
    bg = ["1" if x[2] >= 14 else "0" for x in out]
    if bg and all(b == "1" for b in bg):
        cell["big"] = 1
    elif "1" in bg:
        cell["lb"] = "".join(bg)
    return cell


def col_widths(cells, ncol):
    """cells: [(col, span, width)] -> 각 열 너비 % (정수 리스트)"""
    if ncol <= 0:
        return None
    w = [None] * ncol
    for col, sp, wd in cells:
        if sp == 1 and col < ncol and wd and w[col] is None:
            w[col] = wd
    for _ in range(4):
        for col, sp, wd in cells:
            idx = [i for i in range(col, min(col + sp, ncol))]
            unk = [i for i in idx if w[i] is None]
            if len(unk) == 1 and wd:
                rest = wd - sum(w[i] for i in idx if w[i] is not None)
                if rest > 0:
                    w[unk[0]] = rest
    for col, sp, wd in cells:
        idx = [i for i in range(col, min(col + sp, ncol))]
        unk = [i for i in idx if w[i] is None]
        if unk and wd:
            rest = wd - sum(w[i] for i in idx if w[i] is not None)
            for i in unk:
                w[i] = max(rest, 0) / len(unk) or None
    known = [x for x in w if x]
    if not known:
        return None
    avg = sum(known) / len(known)
    w = [x if x else avg for x in w]
    tot = sum(w)
    return [max(1, round(x * 100 / tot)) for x in w]


def grid_place(rows_spans):
    """rows_spans: [[(cs, rs)]] -> 각 셀의 시작 열 번호 [[col]] 과 전체 열 수"""
    occ = {}
    cols = []
    ncol = 0
    for ri, row in enumerate(rows_spans):
        c = 0
        rc = []
        for cs, rs in row:
            while occ.get((ri, c)):
                c += 1
            rc.append(c)
            for dr in range(rs):
                for dc in range(cs):
                    occ[(ri + dr, c + dc)] = True
            c += cs
            ncol = max(ncol, c)
        cols.append(rc)
    return cols, ncol


def cell_lines(td):
    align, size = HWP_STYLE
    lines = []
    for p in td.iter("p"):
        if any(a.tag == "td" and a is not td for a in p.iterancestors()):
            continue
        a = align.get(_cls_num(p, "parashape-"))
        z = max([size.get(_cls_num(sp, "charshape-"), 0) for sp in p.iter("span")] or [0])
        lines.append((text_no_tables(p), a, z))
        for tbl in p.iter("table"):
            near = next(tbl.iterancestors("td"), None)
            if near is not td:
                continue
            for tr in tbl.iter("tr"):
                if next(tr.iterancestors("table")) is not tbl:
                    continue
                cells = [clean(c.text_content()) for c in tr if c.tag in ("td", "th")]
                cells = [c for c in cells if c]
                if cells:
                    lines.append((" | ".join(cells), None, 0))
    if not lines:
        lines.append((td.text_content(), None, 0))
    return lines


def _mm(style):
    m = re.search(r"width:\s*([\d.]+)mm", style or "")
    return float(m.group(1)) if m else None


def text_no_tables(el):
    """el 의 텍스트에서 하위 table 내용은 제외"""
    buf = []

    def walk(e):
        if e.tag == "table":
            return
        if e.text:
            buf.append(e.text)
        for c in e:
            walk(c)
            if c.tail:
                buf.append(c.tail)
    walk(el)
    return "".join(buf)


def table_rows(tbl):
    rows, spans, widths = [], [], []
    for tr in tbl.iter("tr"):
        if next(tr.iterancestors("table")) is not tbl:
            continue
        row, sp, wd = [], [], []
        for td in tr:
            if td.tag not in ("td", "th"):
                continue
            cs = int(td.get("colspan", "1") or 1)
            rs = int(td.get("rowspan", "1") or 1)
            cell = finish_cell({}, cell_lines(td))
            if cs > 1:
                cell["c"] = cs
            if rs > 1:
                cell["r"] = rs
            row.append(cell)
            sp.append((cs, rs))
            wd.append(_mm(td.get("style")))
        if row:
            rows.append(row)
            spans.append(sp)
            widths.append(wd)
    cols, ncol = grid_place(spans)
    cells = [(cols[i][j], spans[i][j][0], widths[i][j]) for i in range(len(rows)) for j in range(len(rows[i]))]
    return rows, col_widths(cells, ncol)


def table_block(rows, w):
    b = {"table": rows}
    if w and len(w) > 1:
        b["w"] = w
    return b


def html_blocks(doc):
    body = doc.find(".//body")
    blocks = []
    # 문단(p)과, 문단 밖에 바로 놓인 표(table)를 문서 순서대로 읽음.
    # (예전엔 p 안의 표만 읽어서 감사규정 별표1 위임전결 기준표 같은 '문단 밖 표'가 통째로 빠졌음)
    for el in body.iter("p", "table"):
        if any(a.tag == "table" for a in el.iterancestors()):
            continue
        if el.tag == "table":
            if any(a.tag == "p" for a in el.iterancestors()):
                continue  # 문단 안의 표는 아래 p 처리에서 읽음
            rows, w = table_rows(el)
            if rows:
                blocks.append(table_block(rows, w))
            continue
        t = clean(text_no_tables(el))
        if t:
            blocks.append({"p": t})
        for tbl in el.iter("table"):
            if any(a.tag == "table" for a in tbl.iterancestors()):
                continue
            rows, w = table_rows(tbl)
            if rows:
                blocks.append(table_block(rows, w))
    return blocks


# ---------- HWPX ----------

def hwpx_styles(z):
    align, size = {}, {}
    try:
        root = etree.fromstring(z.read("Contents/header.xml"))
    except Exception:
        return align, size
    for pp in root.iter("{*}paraPr"):
        a = next(pp.iter("{*}align"), None)
        if a is not None:
            align[pp.get("id")] = {"CENTER": "c", "RIGHT": "r"}.get(a.get("horizontal"), "l")
    for cp in root.iter("{*}charPr"):
        try:
            size[cp.get("id")] = int(cp.get("height")) / 100
        except (TypeError, ValueError):
            pass
    return align, size


def _ln(e):
    return etree.QName(e).localname


def _kids(e, name):
    return [c for c in e if isinstance(c.tag, str) and _ln(c) == name]


def _ttext(t):
    """<hp:t> 안의 글자. 형광펜(markpen)·탭·줄바꿈 같은 하위 요소 뒤의 글자(tail)까지 모두 읽음"""
    buf = [t.text or ""]
    for c in t:
        if isinstance(c.tag, str):
            name = _ln(c)
            if name == "tab":
                buf.append(" ")
            elif name == "lineBreak":
                buf.append("\n")
        buf.append(c.tail or "")
    return "".join(buf)


def _ptext(p):
    return "".join(_ttext(t) for t in p.iter("{*}t") if _owner_p(t) is p)


def hwpx_table(tbl, st):
    align, size = st
    rows, cells = [], []
    ncol = int(tbl.get("colCnt") or 0)
    for tr in _kids(tbl, "tr"):
        row = []
        for tc in _kids(tr, "tc"):
            lines = []
            for sub in _kids(tc, "subList"):
                for p in _kids(sub, "p"):
                    zs = [size.get(r.get("charPrIDRef"), 0) for r in _kids(p, "run") if any(True for _ in r.iter("{*}t"))]
                    lines.append((_ptext(p), align.get(p.get("paraPrIDRef")), max(zs or [0])))
                    for nt in p.iter("{*}tbl"):
                        if next((a for a in nt.iterancestors() if _ln(a) == "tbl"), None) is not tbl:
                            continue
                        for ntr in _kids(nt, "tr"):
                            lines.append((" | ".join(clean("\n".join(_ptext(q) for q in tc2.iter("{*}p"))).replace("\n", " ")
                                                     for tc2 in _kids(ntr, "tc")), None, 0))
            cell = finish_cell({}, lines)
            span = next(tc.iter("{*}cellSpan"), None)
            addr = next(tc.iter("{*}cellAddr"), None)
            sz = next(tc.iter("{*}cellSz"), None)
            cs = int(span.get("colSpan", 1)) if span is not None else 1
            rs = int(span.get("rowSpan", 1)) if span is not None else 1
            if cs > 1:
                cell["c"] = cs
            if rs > 1:
                cell["r"] = rs
            col = int(addr.get("colAddr", 0)) if addr is not None else 0
            wd = float(sz.get("width", 0)) if sz is not None else 0
            cells.append((col, cs, wd))
            ncol = max(ncol, col + cs)
            row.append(cell)
        if row:
            rows.append(row)
    return rows, col_widths(cells, ncol)


def hwpx_blocks(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    st = hwpx_styles(z)
    secs = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n))
    blocks = []
    for s in secs:
        root = etree.fromstring(z.read(s))
        for p in root.iter("{*}p"):
            if any(_ln(a) == "tbl" for a in p.iterancestors()):
                continue
            txt = _ptext(p)
            if clean(txt):
                blocks.append({"p": clean(txt)})
            for tbl in p.iter("{*}tbl"):
                if any(_ln(a) == "tbl" for a in tbl.iterancestors()):
                    continue
                rows, w = hwpx_table(tbl, st)
                if rows:
                    blocks.append(table_block(rows, w))
    return blocks


def _owner_p(t):
    for a in t.iterancestors():
        if etree.QName(a).localname == "p":
            return a
    return None


# ---------- 공통 ----------

def pdf_blocks(data):
    from pypdf import PdfReader
    blocks = []
    for page in PdfReader(io.BytesIO(data)).pages:
        t = clean(page.extract_text() or "")
        if t:
            blocks.append({"p": t})
    return blocks


def doc_blocks(name, data):
    ext = os.path.splitext(name)[1].lower()
    if ext == ".pdf":
        return pdf_blocks(data)
    if ext == ".hwpx":
        return hwpx_blocks(data)
    if ext == ".hwp":
        if data[:2] == b"PK":
            return hwpx_blocks(data)
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
            f.write(data)
        try:
            return hwp_blocks(f.name)
        finally:
            os.remove(f.name)
    return None


def zip_names(z):
    out = []
    for info in z.infolist():
        n = info.filename
        if not info.flag_bits & 0x800:
            try:
                n = n.encode("cp437").decode("cp949")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        out.append((info, os.path.basename(n)))
    return out


def expand(name, data):
    """파일 하나를 (이름, 데이터) 문서 목록으로 펼친다. zip 은 안의 파일들."""
    if name.lower().endswith(".zip") or data[:2] == b"PK" and not name.lower().endswith((".hwpx", ".hwp")):
        z = zipfile.ZipFile(io.BytesIO(data))
        out = []
        for info, n in zip_names(z):
            if info.is_dir() or not n:
                continue
            out += expand(n, z.read(info))
        return out
    return [(name, data)]


def safe_blocks(name, data):
    if name.lower().endswith(".pdf"):
        try:
            import approval_table
            if approval_table.is_approval_pdf(data):
                secs = approval_table.parse(data)
                if secs:
                    return {"approval": secs}
        except Exception as e:  # noqa: BLE001
            print(f"  ! 전결표 변환 실패 {name}: {e}", file=sys.stderr)
    try:
        return doc_blocks(name, data)
    except Exception as e:  # noqa: BLE001
        print(f"  ! {name}: {e}", file=sys.stderr)
        return None


OVR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overrides")


def apply_override(rule, attachments):
    """overrides/approval.json 에 엑셀 원본이 있으면 PDF 해석 대신 쓴다 (같은 별표 파일일 때만)."""
    try:
        with open(os.path.join(OVR, "approval.json"), encoding="utf-8") as f:
            cfg = json.load(f).get(rule["id"])
    except FileNotFoundError:
        return attachments
    if not cfg:
        return attachments
    nos = {e.get("fileNo") for e in rule.get("extras", [])} | {rule.get("fileNo")}
    if cfg["fileNo"] not in nos:
        print(f"  ! {rule['title']}: 별표 파일이 바뀌어(엑셀 원본 {cfg['fileNo']}) PDF 해석을 씁니다", file=sys.stderr)
        return attachments
    try:
        import approval_xlsx
        with open(os.path.join(OVR, cfg["xlsx"]), "rb") as f:
            data = f.read()
        secs = approval_xlsx.parse(data)
        notes = approval_xlsx.notes(data)
    except Exception as e:  # noqa: BLE001
        print(f"  ! 엑셀 별표 변환 실패 {cfg['xlsx']}: {e}", file=sys.stderr)
        return attachments
    if not secs:
        return attachments
    out, done = [], False
    for name, ab in attachments:
        if isinstance(ab, dict) and "approval" in ab and not done:
            ab = {"approval": secs, "notes": notes}
            done = True
        out.append((name, ab))
    if not done:
        out.append((os.path.splitext(cfg["xlsx"])[0], {"approval": secs, "notes": notes}))
    print(f"  {rule['title']}: 별표를 엑셀 원본으로 대체 ({sum(len(x[1]) for x in secs)}줄)")
    return out


def load_rule(rule):
    """(본문 블록, [(첨부 이름, 첨부 블록 또는 None)])"""
    with open(os.path.join(RAW, rule["file"]), "rb") as f:
        docs = expand(rule["fileName"], f.read())
    for e in rule.get("extras", []):
        with open(os.path.join(RAW, e["file"]), "rb") as f:
            docs += [(n, d) for n, d in expand(e["name"], f.read())]
    readable = [d for d in docs if d[0].lower().endswith((".hwp", ".hwpx"))] or \
        [d for d in docs if d[0].lower().endswith(".pdf")]
    if not readable:
        return None, [(n, None) for n, _ in docs]

    # 본문: 제목이 들어간 파일 > 별지/서식이 아닌 파일 > 가장 큰 파일
    def score(d):
        n = d[0]
        return (not re.search(r"별지|별표|서식|양식|붙임|첨부", n),
                rule["title"].replace(" ", "") in n.replace(" ", ""), len(d[1]))
    main = max(readable, key=score)
    blocks = safe_blocks(*main)
    attachments = []
    for n, d in docs:
        if (n, d) is main or d is main[1]:
            continue
        attachments.append((n, safe_blocks(n, d) if n.lower().endswith((".hwp", ".hwpx", ".pdf")) else None))
    return blocks, attachments


def is_title_line(t):
    return bool(t) and "\n" not in t and 2 <= len(t) <= 60 and t[0] not in "(※[*-ㅇ□○" \
        and not ART_RE.match(t) and not ANNEX_RE.match(t) and not re.match(r"^\d+[.)]", t)


def _cell_title(tb):
    for row in tb["table"][:3]:
        for c in row:
            ln = (c.get("t") or "").split("\n", 1)[0].strip()
            if ln and not ANNEX_RE.match(ln) and 2 <= len(ln) <= 60 and not re.match(r"^(제\s*호|No\.?|\d+)$", ln):
                return ln
    return ""


def fill_annex_titles(secs):
    """제목 없는 [별지] 섹션: 바로 뒤 몇 블록에서 제목(문단 또는 표 첫 칸)을 찾음"""
    for s in secs:
        if s["kind"] != "annex" or s["heading"] or not s["blocks"]:
            continue
        st = 1 if s["blocks"][0].get("fm") else 0
        for i, b in enumerate(s["blocks"][st:st + 3], st):
            if b.get("fd") or b.get("fm"):
                break
            if "p" in b and is_title_line(b["p"]):
                s["heading"] = annex_title(b["p"]) or b["p"]
                s["blocks"][i] = dict(b, ft=1)
                break
            if "table" in b:
                t = _cell_title(b)
                if t:
                    s["heading"] = annex_title(t) or t
                    break


def annex_split(blocks, label, heading, chapter):
    """첨부 파일 블록 안의 [별지]/[별표] 를 서식별 섹션으로 나눔"""
    secs = [{"label": label, "heading": heading, "kind": "attach", "chapter": chapter, "blocks": []}]
    for b in blocks:
        t = b.get("p") or ""
        first = t.split("\n", 1)[0]
        am = ANNEX_RE.match(first) if t and len(first) < 400 else None
        if am:
            kind = re.sub(r"\s+", "", am.group(1))
            title = annex_title(am.group(3))
            if title.startswith("삭제"):
                secs[-1]["blocks"].append(dict(b, fd=1))
                continue
            secs.append({"label": f"{kind} {am.group(2).strip()}".strip(), "heading": title, "kind": "annex",
                         "chapter": "", "blocks": [dict(b, fm=1)]})
            continue
        secs[-1]["blocks"].append(b)
    if not secs[0]["blocks"]:
        secs.pop(0)
    fill_annex_titles(secs)
    return secs


LOST_RE = re.compile(r"^\s*[\[〔【]\s*(<[^>]*>\s*)*$")


def marker_of(b):
    """블록이 [별표]/[별지] 시작 줄이면 (키, 종류, 번호, 뒷부분) — 표 첫 칸에 들어간 경우도 인식"""
    if b.get("p"):
        first = b["p"].split("\n", 1)[0]
        tbl = False
    elif b.get("table") and b["table"] and b["table"][0]:
        first = (b["table"][0][0].get("t") or "").split("\n", 1)[0]
        tbl = True
    else:
        return None
    if len(first) >= 2000:
        return None
    am = ANNEX_RE.match(first)
    if not am:
        return None
    kind = re.sub(r"\s+", "", am.group(1))
    num = re.sub(r"\s+", " ", am.group(2)).strip()
    key = kind + re.sub(r"[\s<].*$", "", re.sub(r"\s+", "", num).replace("서식", "")) if num else kind
    return {"key": key, "kind": kind, "num": num, "rest": am.group(3), "tbl": tbl}


def _junk(b):
    t = b.get("p")
    if t is None:
        return False
    t = t.strip()
    return len(t) < 3 or t[0] in "[〔【"


def find_annex_list(blocks):
    """부칙 뒤 '별표·별지 목록' 범위를 찾음.
    목록은 [별표]/[별지] 줄만 이어지다가, 같은 번호가 다시 나오는 곳(실제 별표 시작)에서 끝난다."""
    f = next((i for i, b in enumerate(blocks) if b.get("p") and marker_of(b)), None)
    if f is None:
        return set()
    seen, mk, L, by_repeat = set(), [], len(blocks), False
    for j in range(f, len(blocks)):
        m = marker_of(blocks[j])
        if m:
            if m["key"] in seen:
                L, by_repeat = j, True
                break
            seen.add(m["key"])
            mk.append(j)
            continue
        if _junk(blocks[j]):
            continue
        L = j
        break
    if not by_repeat and L < len(blocks):
        later = any((m := marker_of(blocks[k])) and m["key"] in seen for k in range(L, len(blocks)))
        if not later:
            # 번호가 다시 안 나오면: 마지막 줄은 바로 뒤 내용을 가진 실제 서식
            if len(mk) < 3:
                return set()
            L = mk[-1]
    if len(mk) < 2:
        return set()
    return set(range(f, L))


def sectionize(blocks):
    """블록을 조문 단위 섹션으로 나눈다.
    [별표]/[별지] 부터는: 목록 한 묶음 → 실제 별표·별지 하나가 한 섹션 (삭제된 것은 작은 줄로)."""
    secs, cur, in_addenda, addenda_n = [], None, False, 0
    chapter, chap = "", []
    in_annex, want_title = False, False
    list_idx = find_annex_list(blocks)
    # 목록 순서: 번호를 못 읽은 실제 서식에 목록의 다음 이름을 붙이는 데 씀
    entries = []
    for i in sorted(list_idx):
        m = marker_of(blocks[i])
        if m and blocks[i].get("p"):
            ti = annex_title(m["rest"])
            entries.append((m["key"], f"{m['kind']} {m['num']}".strip(), ti, ti.startswith("삭제")))
    ptr = 0

    def seek(key):
        nonlocal ptr
        for k, e in enumerate(entries):
            if e[0] == key:
                ptr = k + 1
                return

    def next_entry():
        nonlocal ptr
        while ptr < len(entries) and entries[ptr][3]:
            ptr += 1
        if ptr < len(entries):
            ptr += 1
            return entries[ptr - 1]
        return None

    def new_unnamed():
        e = next_entry()
        return new(e[1] if e else "별표·별지", e[2] if e else "", "annex")

    def new(label, heading, kind):
        nonlocal cur
        cur = {"label": label, "heading": heading, "kind": kind, "chapter": chapter, "blocks": []}
        secs.append(cur)
        return cur

    new("머리말", "", "head")
    for i, b in enumerate(blocks):
        t = b.get("p")
        if i in list_idx:
            if not cur.get("_list"):
                in_annex, chapter = True, ""
                new("별표·별지", "목록", "annex")["_list"] = True
            m = marker_of(b)
            if t and m and annex_title(m["rest"]).startswith("삭제"):
                cur["blocks"].append(dict(b, fd=1))
            elif t:
                cur["blocks"].append({"p": t, "fl": 1})
            else:
                cur["blocks"].append(b)
            continue
        if want_title and t and len(t.strip()) < 2:
            continue  # 'ㄹ' 같은 잡글자는 버리고 계속 제목을 찾음
        if want_title:
            want_title = False
            if is_title_line(t):
                cur["heading"] = annex_title(t) or t
                b = dict(b, ft=1)
        if in_annex and t and LOST_RE.match(t):
            # '[별지 제N호 서식]' 글자가 빠지고 '[' 나 '[<개정 …>' 만 남은 줄 → 목록 순서로 이름을 붙임
            new_unnamed()
            if t.strip("[ "):
                cur["blocks"].append({"p": t.strip("[ "), "fd": 1})
            want_title = not cur["heading"]
            continue
        m = marker_of(b)
        if m and (in_annex or not m["tbl"]):
            label = f"{m['kind']} {m['num']}".strip()
            title = annex_title(m["rest"])
            seek(m["key"])
            in_annex, chapter = True, ""
            if title.startswith("삭제"):
                if not cur.get("_del"):
                    new(label, "삭제", "annex")["_del"] = True
                cur["blocks"].append(dict(b, fd=1))
                continue
            new(label, "" if m["tbl"] else title, "annex")["_key"] = m["key"]
            if not m["tbl"]:
                b = dict(b, fm=1)
                if not title:
                    want_title = True
            cur["blocks"].append(b)
            continue
        if cur.get("_del") and not _junk(b):
            # 삭제 줄들 뒤에 번호를 못 읽은 실제 별표가 이어지는 경우
            new_unnamed()
        if t and not in_annex:
            first = t.split("\n", 1)[0]
            if ADDENDA_RE.match(first) and len(first) < 40:
                in_addenda = True
                addenda_n += 1
                chapter = first
                new("부칙" if addenda_n == 1 else f"부칙({addenda_n})", first, "addenda")
            elif CHAP_RE.match(first) and len(first) < 40 and not in_addenda and "\n" not in t:
                level = CHAP_RE.match(first).group(1)
                if level == "장":
                    chap = [first]
                else:
                    chap = chap[:1] + [first] if level == "절" else chap[:2] + [first]
                chapter = " · ".join(chap)
                continue
            else:
                m = ART_RE.match(first)
                if m:
                    label = re.sub(r"\s+", "", m.group(1))
                    if in_addenda:
                        label = f"부칙 {label}"
                    new(label, (m.group(3) or "").strip(), "article")
        cur["blocks"].append(b)
    fill_annex_titles(secs)
    names = {e[0]: e[2] for e in entries if e[2] and not e[3]}
    for s in secs:
        if s["kind"] == "annex" and not s["heading"] and s.get("_key") in names:
            s["heading"] = names[s["_key"]]
    out = [s for s in secs if s["blocks"] or s["kind"] != "head"]
    for s in out:
        s.pop("_list", None)
        s.pop("_del", None)
        s.pop("_key", None)
    for i, s in enumerate(out):
        s["id"] = f"s{i}"
    return out


def block_text(b):
    if "p" in b:
        return b["p"]
    return "\n".join(" | ".join(c["t"] for c in row) for row in b["table"]
                     if not all(c.get("h") for c in row))


# 그림 설명(대체 글자)은 본문이 아니므로 비교에서 뺌
PIC_ALT = re.compile(r"그림입니다\.\s*원본 그림의 이름:[^\n]*\n?원본 그림의 크기:[^\n]*?pixel(, 세로 \d+pixel)?")


def _raw_text(name, data):
    """검증용: 변환 경로와 다른 방법으로 원문 글자를 통째로 뽑음"""
    ext = os.path.splitext(name)[1].lower()
    if ext in (".hwpx", ".hwp") and data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        out = []
        for n in z.namelist():
            if re.match(r"Contents/section\d+\.xml", n):
                out.append("".join(etree.fromstring(z.read(n)).itertext()))
        return PIC_ALT.sub("", "".join(out))
    if ext == ".hwp" and _md5(data) in HWP_FULLTEXT:
        # 한글 → HTML 변환 결과 '전체'(문단·표 구분 없이)의 글자. 블록 읽기에서 빠진 것을 잡아냄
        return PIC_ALT.sub("", HWP_FULLTEXT[_md5(data)])
    if ext == ".hwp":
        exe = shutil.which("hwp5txt") or os.path.join(os.path.dirname(sys.executable), "hwp5txt")
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
            f.write(data)
        try:
            r = subprocess.run([exe, f.name], capture_output=True, timeout=300)
            out = r.stdout.decode("utf-8", "ignore").replace("<표>", "")
            # 그림 설명(대체 글자)은 본문이 아니므로 비교에서 뺌
            return PIC_ALT.sub("", out)
        finally:
            os.remove(f.name)
    if ext == ".zip":
        z = zipfile.ZipFile(io.BytesIO(data))
        return "".join(_raw_text(n, z.read(info)) for info, n in zip_names(z)
                       if os.path.splitext(n)[1].lower() in (".hwp", ".hwpx"))
    return ""


def text_check(r, secs):
    """원문 글자 중 사이트 데이터에 빠진 비율. 1%를 넘으면 경고 (예: HWPX 형광펜 뒤 글자 누락)"""
    import collections
    try:
        with open(os.path.join(RAW, r["file"]), "rb") as f:
            raw = _raw_text(r["file"], f.read())
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    ours = "".join(block_text(b) for s in secs for b in s["blocks"]) + "".join(s.get("chapter") or "" for s in secs)
    a = collections.Counter(re.sub(r"\s+", "", raw))
    b = collections.Counter(re.sub(r"\s+", "", ours))
    total = sum(a.values())
    miss = sum((a - b).values())
    return {"raw": total, "missing": miss, "ratio": round(miss / total, 4) if total else 0}


def main():
    with open(os.path.join(RAW, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    rules = man["rules"]
    os.makedirs(os.path.join(OUT, "rules"), exist_ok=True)
    index, texts, failed = [], {}, []
    checks, suspect = {}, []
    for r in rules:
        try:
            blocks, attachments = load_rule(r)
        except Exception as e:  # noqa: BLE001
            print(f"! 변환 실패 {r['title']}: {e}", file=sys.stderr)
            blocks, attachments = None, []
        if not blocks:
            failed.append(r["title"])
            blocks = []
        secs = sectionize(blocks)
        attachments = apply_override(r, attachments)
        for name, ab in attachments:
            if isinstance(ab, dict) and "approval" in ab:
                stem = os.path.splitext(name)[0]
                if ab.get("notes"):
                    secs.append({"label": "별표", "heading": "별표 안내", "kind": "attach", "chapter": stem,
                                 "blocks": [{"p": n} for n in ab["notes"]], "id": f"s{len(secs)}"})
                for item in ab["approval"]:
                    unit, rows = item[0], item[1]
                    cat = item[2] if len(item) > 2 else ""
                    secs.append({"label": "전결", "heading": unit, "kind": "attach", "chapter": stem, "cat": cat,
                                 "blocks": [{"table": [[{"t": "세부업무", "h": 1}, {"t": "전결권자", "h": 1}]] +
                                             [[{"t": a}, {"t": w}] for a, w in rows]}],
                                 "id": f"s{len(secs)}"})
                continue
            if ab:
                stem = os.path.splitext(name)[0]
                for x in annex_split(ab, "첨부", stem, ""):
                    x["id"] = f"s{len(secs)}"
                    secs.append(x)
        alltext = "\n".join(block_text(b) for s in secs for b in s["blocks"])
        texts[r["id"]] = alltext
        head = next((s for s in secs if s["kind"] == "head"), None)
        effective = ""
        if head:
            m = re.search(r"시행\s*([\d.\s]+\d)", "\n".join(block_text(b) for b in head["blocks"]))
            if m:
                effective = re.sub(r"\s+", "", m.group(1)).rstrip(".")
        detail = {
            "id": r["id"], "title": r["title"], "category": r["category"],
            "enacted": r["enacted"], "modified": r["modified"], "effective": effective,
            "fileName": r["fileName"], "fileNo": r["fileNo"], "url": r["url"],
            "attachments": [n for n, _ in attachments],
            "extras": [{"fileNo": e["fileNo"], "name": e["name"]} for e in r.get("extras", [])],
            "history": r.get("history", []),
            "parsed": bool(blocks),
            "sections": [{k: s[k] for k in ("id", "label", "heading", "kind", "chapter", "blocks")} for s in secs],
        }
        index.append({
            "id": r["id"], "title": r["title"], "category": r["category"],
            "enacted": r["enacted"], "modified": r["modified"], "fileNo": r["fileNo"],
            "parsed": bool(blocks),
            "secs": [[s["id"], s["label"], s["heading"], "\n".join(block_text(b) for b in s["blocks"])] +
                     ([s["cat"]] if s.get("cat") else []) for s in secs],
        })
        with open(os.path.join(OUT, "rules", f"{r['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, separators=(",", ":"))
        chk = text_check(r, secs)
        checks[r["title"]] = chk
        warn = chk.get("ratio", 0) > 0.01
        if warn:
            suspect.append(r["title"])
        print(f"{'✓' if blocks else '✗'} {r['title']} ({len(secs)}개 조문)"
              + (f"  ! 원문 글자 {chk['missing']}자 누락 의심({chk['ratio']:.1%})" if warn else ""))

    # 관련 사규: 본문에서 다른 사규 제목을 언급한 경우
    titles = {r["id"]: r["title"] for r in rules}
    for item in index:
        txt = texts[item["id"]].replace(" ", "")
        refs = []
        for oid, t in titles.items():
            if oid == item["id"] or len(t) < 3:
                continue
            if t.replace(" ", "") in txt:
                refs.append(oid)
        item["refs"] = refs
    by = {i["id"]: [] for i in index}
    for item in index:
        for o in item["refs"]:
            by[o].append(item["id"])
    for item in index:
        item["refBy"] = by[item["id"]]

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"source": man["source"], "collectedAt": man.get("collectedAt", ""),
                   "rules": index}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "check.json"), "w", encoding="utf-8") as f:
        json.dump(checks, f, ensure_ascii=False, indent=0)
    print(f"\n완료: {len(rules)}건, 변환 실패 {len(failed)}건, 글자 누락 의심 {len(suspect)}건")
    for t in suspect:
        print("  ! 누락 의심", t, checks[t])
    for t in failed:
        print("  ✗", t)


if __name__ == "__main__":
    main()
