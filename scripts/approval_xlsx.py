"""위임전결규정 별표 엑셀 원본 → [(단위업무, [[세부업무, 전결권자], ...]), ...]
approval_table.py(PDF 좌표 해석)와 같은 모양으로 돌려준다. 엑셀이 있으면 PDF보다 정확하다."""
import io
import re

import openpyxl

APPROVERS = ["팀장", "처장", "본부장/단장", "부사장", "사장"]


def _level(t):
    s = t.strip()
    if re.match(r"^[·•∙ㆍ]", s):
        return 2
    if re.match(r"^[가-하]\)", s):
        return 1
    return 0


def _clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()


def notes(data):
    """표 위의 ※ 안내문"""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb["별표 전체"] if "별표 전체" in wb.sheetnames else wb.worksheets[0]
    out = []
    for r in range(1, 30):
        vals = [_clean(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)]
        t = " ".join(v for v in vals if v)
        if t.replace(" ", "").startswith("업무구분"):
            break
        if t.startswith("※"):
            out.append(t)
        elif out and t and not t.startswith("["):
            out[-1] += " " + t
    return out


def parse(data):
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb["별표 전체"] if "별표 전체" in wb.sheetnames else wb.worksheets[0]
    # 머리글 찾기: '세부 업무' 칸과 결재 직위 칸
    hdr = None
    for r in range(1, 40):
        for c in range(1, ws.max_column + 1):
            if _clean(ws.cell(r, c).value).replace(" ", "") == "세부업무":
                hdr = (r, c)
                break
        if hdr:
            break
    if not hdr:
        return []
    hr, dcol = hdr
    cols = {}
    for r in (hr, hr + 1):
        for c in range(dcol + 1, ws.max_column + 1):
            t = _clean(ws.cell(r, c).value)
            if t in APPROVERS:
                cols[t] = c
    if len(cols) < 5:
        return []
    ucol, ncol = dcol - 1, dcol - 2   # 단위업무, 번호
    ccols = list(range(max(1, ncol - 3), ncol))  # 업무구분 (대·중·소)
    cat = ["", "", ""]
    units, stack = [], []
    for r in range(hr + 2, ws.max_row + 1):
        for i, c in enumerate(ccols[-3:]):
            t = _clean(ws.cell(r, c).value)
            if t:
                t = re.sub(r"(?<=[A-Za-z]) (?=[A-Za-z])", "", re.sub(r"\(※.*", "", t)).replace(" / ", "/").strip()
                cat[i] = t
                for j in range(i + 1, 3):
                    cat[j] = ""
        no, uname, d = _clean(ws.cell(r, ncol).value), _clean(ws.cell(r, ucol).value), _clean(ws.cell(r, dcol).value)
        if uname:
            units.append([f"{no}. {uname}" if no else uname, [], " › ".join(dict.fromkeys(x for x in cat if x))])
            stack = []
        if not units:
            continue
        marks = {a: _clean(ws.cell(r, c).value) for a, c in cols.items()}
        main = [a for a in APPROVERS if marks[a] and marks[a][0] in "○◯◎O0"]
        via = [a for a in APPROVERS if "△" in marks[a]]
        if not d:
            if uname and (main or via):
                d = uname          # 세부업무 없이 단위업무 줄에 바로 표시된 경우
            else:
                continue
        rows = units[-1][1]
        lv = _level(d)
        if not main and not via:
            if d.startswith(("*", "※")) and rows:
                rows[-1][0] += " " + d
            else:
                stack = [s for s in stack if s[0] < lv] + [(lv, d)]
            continue
        stack = [s for s in stack if s[0] < lv]
        label = " › ".join([s[1] for s in stack] + [d])
        label = re.sub(r"(^|› )[·•∙ㆍ]\s*", r"\1", label)
        who = ", ".join(main) or "-"
        if via:
            who += f" ({', '.join(via)} 경유)"
        rows.append([label, who])
    return [(u, rows, c) for u, rows, c in units if rows]
