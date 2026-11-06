"""위임전결규정 별표(PDF)의 전결권자 표를 칸 위치 기준으로 읽는다.

PDF를 텍스트로만 뽑으면 ○ 가 팀장·처장·본부장/단장·부사장·사장 중
어느 칸인지 사라지므로, pdfplumber 로 표 칸(cell)과 글자 좌표를 읽어
"단위업무 / 세부업무 / 전결권자" 행으로 되살린다.
"""
import io
import re

PENDING = "\u0000pending"
APPROVERS = ["팀장", "처장", "본부장/단장", "부사장", "사장"]
SUB_RE = re.compile(r"^\s*([가-하]\)|\d+\)|[①-⑳])")
BULLET_RE = re.compile(r"^\s*[·•∙ㆍ\-]")


def _level(text):
    if BULLET_RE.match(text):
        return 2
    if SUB_RE.match(text):
        return 1
    return 0


def is_approval_pdf(data):
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return False
            t = pdf.pages[0].extract_text() or ""
            if len(pdf.pages) > 1:
                t += pdf.pages[1].extract_text() or ""
    except Exception:  # noqa: BLE001
        return False
    return "전결권자" in t and all(a in t for a in ("팀장", "처장", "부사장"))


def _lines(words, tol=4):
    rows = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1]["top"] - w["top"]) <= tol:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})
    for r in rows:
        r["words"].sort(key=lambda w: w["x0"])
        r["text"] = re.sub(r"\s*[○△◯◎]+\s*", " ", " ".join(w["text"] for w in r["words"])).strip()
    return rows


def parse(data):
    """[(단원 제목, [[세부업무, 전결권자], ...]), ...]"""
    import pdfplumber

    units = []          # [(cat, unit, rows)]
    cur_key = None
    cat_big = cat_mid = unit = ""
    stack = []          # 세부업무 머리말 계층
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            words = pg.extract_words()
            anchor = [w for w in words if w["text"] == "전결권자" and w["x0"] > pg.width * 0.55]
            if not anchor:
                continue
            a0 = anchor[0]["top"]
            hwords = [w for w in words if w["text"] in APPROVERS and a0 - 2 <= w["top"] <= a0 + 35]
            hdr = {}
            for w in hwords:
                hdr.setdefault(w["text"], (w["x0"] + w["x1"]) / 2)
            if len(hdr) < 5:
                continue
            col_x = [hdr[a] for a in APPROVERS]
            mark_left = col_x[0] - 25
            tables = pg.find_tables()
            if not tables:
                continue
            tbl = max(tables, key=lambda t: len(t.cells))
            header_bottom = max(w["bottom"] for w in hwords)
            cells = [c for c in tbl.cells if c[1] >= header_bottom - 1]
            x_detail = min((w["x0"] for w in words if w["text"] == "세부" and a0 - 2 <= w["top"] <= a0 + 35), default=560) - 200
            x_detail = min(x_detail, 390)

            def inside(w, c):
                cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
                return c[0] - 1 <= cx <= c[2] + 1 and c[1] - 1 <= cy <= c[3] + 1

            body = [w for w in words if w["top"] >= header_bottom]
            kind = {}
            for c in cells:
                if c[0] >= mark_left:
                    kind[c] = "mark"
                elif c[0] >= x_detail - 10:
                    kind[c] = "detail"
                elif c[0] >= 198 and c[2] >= mark_left - 30:
                    kind[c] = "uspan"   # 세부업무 없이 단위업무가 세부칸까지 합쳐진 경우
                elif c[0] >= 198:
                    kind[c] = "uname"
                elif c[0] >= 175:
                    kind[c] = "uno"
                elif c[0] >= 90 or c[2] >= 175:
                    kind[c] = "mid"
                else:
                    kind[c] = "big"
            ctext = {}
            for c in cells:
                ws = [w for w in body if inside(w, c)]
                if kind[c] in ("big",):
                    ctext[c] = "".join(w["text"] for w in sorted(ws, key=lambda w: w["top"]))
                else:
                    ctext[c] = " ".join(l["text"] for l in _lines(ws))
            marks = [w for w in body if w["x0"] >= mark_left and re.fullmatch(r"[○△◯◎]+", w["text"])]
            mlines = _lines(marks, tol=5)

            def cell_at(y, kinds):
                best = None
                for c in cells:
                    if kind[c] in kinds and c[1] - 1 <= y <= c[3] + 1:
                        if best is None or (c[3] - c[1]) < (best[3] - best[1]):
                            best = c
                return best

            # 세부업무 칸 단위로 처리
            # 표 머리 줄에 끼어 있는 단위업무(쪽이 바뀌며 칸이 잘린 경우)
            band = [w for w in words if a0 - 2 <= w["top"] <= header_bottom + 2 and 181 <= w["x0"] < x_detail - 10]
            btxt = " ".join(w["text"] for w in sorted(band, key=lambda w: w["x0"])).replace("단위업무", "").strip()
            if btxt:
                m0 = re.match(r"(\d+)\s*(.+)", btxt)
                unit = f"{m0.group(1)}. {m0.group(2)}" if m0 else btxt
                if units and units[-1][1] == PENDING:
                    units[-1] = (units[-1][0], unit, units[-1][2])
                    cur_key = (units[-1][0], unit)
            dcells = sorted([c for c in cells if kind[c] in ("detail", "uspan")], key=lambda c: c[1])
            for dc in dcells:
                ymid = (dc[1] + dc[3]) / 2
                un = dc if kind[dc] == "uspan" else cell_at(ymid, ("uname",))
                if un is None and any(kind[c] == "uname" and c[3] < ymid for c in cells):
                    unit = PENDING  # 단위업무 칸이 다음 쪽 머리에 이어짐
                if un is not None and ctext.get(un):
                    no = cell_at(ymid, ("uno",))
                    unit = (f"{ctext[no]}. " if no is not None and ctext.get(no) else "") + ctext[un]
                m = cell_at(ymid, ("mid",))
                if m is not None and ctext.get(m):
                    cat_mid = ctext[m]
                cat = cat_mid
                key = (cat, unit)
                if key != cur_key:
                    units.append((cat, unit, []))
                    cur_key = key
                    stack = []
                rows = units[-1][2]
                dlines = _lines([w for w in body if inside(w, dc)])
                dml = [ml for ml in mlines if dc[1] - 1 <= ml["top"] <= dc[3] + 1]
                if not dlines:
                    continue

                def who(ml):
                    got = []
                    for w in ml["words"]:
                        cx = (w["x0"] + w["x1"]) / 2
                        i = min(range(5), key=lambda k: abs(col_x[k] - cx))
                        got.append((i, w["text"]))
                    main = [APPROVERS[i] for i, t in got if "○" in t or "◯" in t or "◎" in t]
                    via = [APPROVERS[i] for i, t in got if "△" in t]
                    s = ", ".join(main) or "-"
                    if via:
                        s += f" ({', '.join(via)} 경유)"
                    return s

                if not dml:
                    # 표시가 없는 칸: 다음 칸들의 머리말
                    t = " ".join(l["text"] for l in dlines)
                    lv = _level(t)
                    stack = [s for s in stack if s[0] < lv] + [(lv, t)]
                    continue
                if len(dml) == 1:
                    t = " ".join(l["text"] for l in dlines)
                    lv = _level(t)
                    stack = [s for s in stack if s[0] < lv]
                    label = " › ".join([s[1] for s in stack] + [t])
                    rows.append([label, who(dml[0])])
                    continue
                # 한 칸 안에 여러 줄이 각각 표시를 가진 경우
                used = set()
                for ml in dml:
                    li = min(range(len(dlines)), key=lambda k: abs(dlines[k]["top"] - ml["top"]))
                    used.add(li)
                for k, l in enumerate(dlines):
                    t = l["text"]
                    lv = _level(t)
                    if k not in used:
                        if t.startswith(("*", "※")) and rows:
                            rows[-1][0] += " " + t
                        else:
                            stack = [s for s in stack if s[0] < lv] + [(lv, t)]
                        continue
                    ml = min(dml, key=lambda m: abs(m["top"] - l["top"]))
                    stack = [s for s in stack if s[0] < lv]
                    rows.append([" › ".join([s[1] for s in stack] + [t]), who(ml)])
                    stack = stack  # 같은 머리말 유지
    out = []
    for _, _, rows in units:
        for r in rows:
            r[0] = re.sub(r"(^|› )[·•∙ㆍ]\s*", r"\1", r[0])
    for cat, unit, rows in units:
        if not rows or unit == PENDING:
            continue
        # 업무구분(대분류)은 쪽이 바뀌면 칸이 비어 잘못 이어질 수 있어 단위업무만 쓴다
        out.append((unit.strip(), rows))
    return out
