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
    return html_blocks(doc)


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
    for p in body.iter("p"):
        if any(a.tag == "table" for a in p.iterancestors()):
            continue
        t = clean(text_no_tables(p))
        if t:
            blocks.append({"p": t})
        for tbl in p.iter("table"):
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


def _ptext(p):
    return "".join(t.text or "" for t in p.iter("{*}t") if _owner_p(t) is p)


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


def sectionize(blocks):
    """블록을 조문 단위 섹션으로 나눈다."""
    secs, cur, in_addenda, addenda_n = [], None, False, 0
    chapter, chap = "", []

    def new(label, heading, kind):
        nonlocal cur
        cur = {"label": label, "heading": heading, "kind": kind, "chapter": chapter, "blocks": []}
        secs.append(cur)

    new("머리말", "", "head")
    for b in blocks:
        t = b.get("p")
        if t:
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
    out = []
    for s in secs:
        if s["blocks"] or s["kind"] != "head":
            out.append(s)
    for i, s in enumerate(out):
        s["id"] = f"s{i}"
    return out


def block_text(b):
    if "p" in b:
        return b["p"]
    return "\n".join(" | ".join(c["t"] for c in row) for row in b["table"]
                     if not all(c.get("h") for c in row))


def main():
    with open(os.path.join(RAW, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    rules = man["rules"]
    os.makedirs(os.path.join(OUT, "rules"), exist_ok=True)
    index, texts, failed = [], {}, []
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
                secs.append({"label": "첨부", "heading": stem, "kind": "attach", "chapter": "",
                             "blocks": ab, "id": f"s{len(secs)}"})
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
        print(f"{'✓' if blocks else '✗'} {r['title']} ({len(secs)}개 조문)")

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
    print(f"\n완료: {len(rules)}건, 변환 실패 {len(failed)}건")
    for t in failed:
        print("  ✗", t)


if __name__ == "__main__":
    main()
