# 인천국제공항공사 사규 검색

휴대폰에서 인천국제공항공사 최신 내부규정을 키워드로 검색하고, 조문 단위로 결과와 관련 사규, 상세 본문을 보는 웹앱입니다.
원본은 [ALIO 내부규정 공시](https://www.alio.go.kr/item/itemOrganList.do?apbaId=C0105&reportFormRootNo=21110)입니다.

## 구조

```
국내 PC (작업 스케줄러, 주 1회)        GitHub
scripts/collect.py  ── raw/ push ──▶  Actions: scripts/build.py (HWP → JSON)
  알리오 목록·최신 파일 수집                     └▶ GitHub Pages: site/
```

* 알리오는 해외 IP 접속을 막기 때문에 수집은 국내 PC에서 합니다. GitHub Actions는 변환과 배포만 합니다.
* `raw/manifest.json`: 사규 목록과 최신 파일 정보, `raw/<id>/<fileNo>.hwp|zip`: 최신 개정 원문.
* `site/data/index.json`(검색용), `site/data/rules/<id>.json`(상세)는 빌드 때 생성됩니다.

## 수집 (Windows)

```powershell
python -X utf8 scripts\collect.py --push
```

`scripts\update.ps1`을 작업 스케줄러에 등록하면 주기적으로 실행됩니다.

## 로컬에서 미리보기

```bash
pip install pyhwp six lxml pypdf pdfplumber
python scripts/build.py
python -m http.server -d site 8000
```
