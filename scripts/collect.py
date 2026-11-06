"""알리오에서 인천국제공항공사 내부규정 최신 파일을 내려받아 raw/ 에 저장한다.

알리오는 해외 IP 접속을 차단하므로 국내 PC에서 실행해야 한다.
표준 라이브러리만 사용한다.

    python -X utf8 scripts/collect.py          # 수집만
    python -X utf8 scripts/collect.py --push   # 수집 후 변경분 git commit/push
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://www.alio.go.kr"
APBA_ID = "C0105"           # 인천국제공항공사
REPORT_FORM = "21110"       # 내부규정
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
UA = "Mozilla/5.0 (rules-search collector)"
KST = timezone(timedelta(hours=9))


def http(url, data=None, headers=None, retries=3):
    h = {"User-Agent": UA}
    h.update(headers or {})
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"  재시도 {i + 1}: {url} ({e})", file=sys.stderr)
            time.sleep(2 * (i + 1))


def list_rules():
    items, page = [], 1
    while True:
        body = json.dumps({
            "pageNo": page, "apbaId": APBA_ID, "apbaType": "",
            "reportFormRootNo": REPORT_FORM, "search_word": "",
            "search_flag": "title", "bid_type": "", "enfc_istt": "",
        }).encode()
        res = json.loads(http(BASE + "/item/itemReportListSusi.json", body,
                              {"Content-Type": "application/json;charset=UTF-8"}))
        data = res["data"]
        items += data["result"]
        if page >= data["page"]["totalPage"]:
            break
        page += 1
        time.sleep(0.3)
    return items


def detail_url(it):
    q = {
        "disclosureNo": "", "apbaId": it["apbaId"], "nowcode": it["reportFormNo"],
        "reportFormNo": it["reportFormNo"], "table_name": it["tableName"],
        "idx_name": it["idxName"], "idx": it["idx"], "reportGbn": "N",
        "bid_type": it.get("bidType") or "",
    }
    return f"{BASE}/item/itemBoard{it['reportFormNo']}.do?" + urllib.parse.urlencode(q)


def field(page, label):
    m = re.search(r"<span>\s*" + re.escape(label) + r"\s*</span>.*?<p>\s*(.*?)\s*</p>", page, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def parse_detail(page):
    files = [
        {"fileNo": int(n), "name": html.unescape(name).strip()}
        for n, name in re.findall(r'href="/download/rulefiledown\.json\?fileNo=(\d+)"[^>]*>([^<]+)</a>', page)
    ]
    return {
        "category": field(page, "구분"),
        "enacted": field(page, "제·개정일"),
        "modified": field(page, "최종 수정일"),
        "files": files,
    }


ATTACH_RE = re.compile(r"별표|별지|서식|양식|붙임|첨부")
DOC_EXT = (".hwp", ".hwpx", ".zip", ".pdf", ".doc", ".docx")


def pick_files(files):
    """최신 개정본 본문 파일과, 같은 때 함께 올라온 별표·서식 파일을 고른다.

    한 번 개정할 때 본문(hwp)과 별표(pdf)·서식(zip)이 같이 올라오므로
    단순히 가장 최근 파일을 고르면 별표가 본문으로 잡힐 수 있다.
    """
    files = sorted(files, key=lambda f: f["fileNo"])
    docs = [f for f in files if f["name"].lower().endswith(DOC_EXT)] or files
    bodies = [f for f in docs if not ATTACH_RE.search(f["name"])] or docs
    main = dict(bodies[-1])
    extras = [dict(f) for f in docs if f["fileNo"] > main["fileNo"]]
    return main, extras


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="변경분을 git commit 후 push")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    man_path = os.path.join(RAW, "manifest.json")
    old = {}
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as f:
            old = {r["id"]: r for r in json.load(f)["rules"]}

    items = list_rules()
    print(f"목록 {len(items)}건")
    rules, changed = [], []
    for it in items:
        rid = it["idx"]
        url = detail_url(it)
        d = parse_detail(http(url).decode("utf-8", "replace"))
        time.sleep(0.3)
        if not d["files"]:
            print(f"  ! 파일 없음: {it['title']}")
            continue
        main, extras = pick_files(d["files"])
        folder = os.path.join(RAW, rid)
        os.makedirs(folder, exist_ok=True)
        keep = []
        for f in [main, *extras]:
            ext = os.path.splitext(f["name"])[1].lower() or ".bin"
            f["file"] = f"{rid}/{f['fileNo']}{ext}"
            fpath = os.path.join(RAW, f["file"])
            keep.append(os.path.basename(fpath))
            if not os.path.exists(fpath):
                print(f"  ↓ {it['title']} ← {f['name']}")
                data = http(f"{BASE}/download/rulefiledown.json?fileNo={f['fileNo']}")
                with open(fpath, "wb") as fp:
                    fp.write(data)
                if f is main:
                    changed.append(it["title"])
                time.sleep(0.3)
        for other in os.listdir(folder):  # 이전 개정본 정리
            if other not in keep:
                os.remove(os.path.join(folder, other))
        rules.append({
            "id": rid,
            "title": it["title"].strip(),
            "category": d["category"],
            "enacted": d["enacted"] or it.get("stDate", ""),
            "modified": d["modified"] or it.get("idate", ""),
            "fileNo": main["fileNo"],
            "fileName": main["name"],
            "file": main["file"],
            "extras": [{"fileNo": e["fileNo"], "name": e["name"], "file": e["file"]} for e in extras],
            "history": d["files"],
            "url": url,
        })

    ids = {r["id"] for r in rules}
    for rid in old:
        if rid not in ids:
            changed.append(f"삭제: {old[rid]['title']}")
            p = os.path.join(RAW, rid)
            if os.path.isdir(p):
                for f in os.listdir(p):
                    os.remove(os.path.join(p, f))
                os.rmdir(p)

    rules.sort(key=lambda r: r["title"])
    out = {"source": BASE + f"/item/itemOrganList.do?apbaId={APBA_ID}&reportFormRootNo={REPORT_FORM}",
           "rules": rules}
    meta_changed = json.dumps([old.get(r["id"], {}) for r in rules], sort_keys=True) != \
        json.dumps(rules, sort_keys=True)
    if changed or meta_changed or not old:
        out["collectedAt"] = datetime.now(KST).isoformat(timespec="seconds")
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"완료: {len(rules)}건, 새 파일 {len(changed)}건")
    for c in changed:
        print("  -", c)

    if args.push:
        def git(*a):
            return subprocess.run(["git", "-C", ROOT, *a], check=True, capture_output=True, text=True,
                                  encoding="utf-8").stdout
        git("pull", "--rebase", "--autostash")
        git("add", "raw")
        if git("status", "--porcelain", "raw").strip():
            msg = f"사규 갱신 {datetime.now(KST):%Y-%m-%d}" + (f": {', '.join(changed[:5])}" if changed else "")
            git("commit", "-m", msg)
            git("push")
            print("push 완료")
        else:
            print("변경 없음, push 생략")


if __name__ == "__main__":
    main()
