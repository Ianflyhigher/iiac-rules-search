(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const view = $("#view");
  const qInput = $("#q");
  let DB = null;            // index.json
  let byId = {};
  const detailCache = {};
  const RECENT_KEY = "rules.recent";

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // 검색어 → 토큰 (띄어쓰기 무시 매칭: "육아휴직" 이 "육아 휴직" 에도 걸림)
  function tokenize(q) {
    return [...new Set(q.trim().split(/[\s,]+/).filter(Boolean))];
  }
  function tokenRe(tok, flags = "gi") {
    const chars = [...tok.replace(/\s+/g, "")].map(reEsc);
    return new RegExp(chars.join("\\s*"), flags);
  }
  function highlight(text, res) {
    if (!res || !res.length) return esc(text);
    const big = new RegExp(res.map((r) => r.source).join("|"), "gi");
    let out = "", last = 0, m;
    while ((m = big.exec(text))) {
      if (!m[0]) { big.lastIndex++; continue; }
      out += esc(text.slice(last, m.index)) + "<mark>" + esc(m[0]) + "</mark>";
      last = m.index + m[0].length;
    }
    return out + esc(text.slice(last));
  }
  function snippet(text, res, len = 110) {
    let pos = -1;
    for (const r of res) { r.lastIndex = 0; const m = r.exec(text); if (m && (pos < 0 || m.index < pos)) pos = m.index; }
    const flat = text;
    if (pos < 0) return highlight(flat.slice(0, len), res) + (flat.length > len ? "…" : "");
    const start = Math.max(0, pos - 35);
    const s = flat.slice(start, start + len).replace(/\n+/g, " ");
    return (start > 0 ? "…" : "") + highlight(s, res) + (start + len < flat.length ? "…" : "");
  }
  const count = (text, r) => { r.lastIndex = 0; return (text.match(r) || []).length; };

  function search(q) {
    const toks = tokenize(q);
    if (!toks.length) return { toks, res: [], results: [] };
    const res = toks.map((t) => tokenRe(t));
    const results = [];
    for (const rule of DB.rules) {
      let score = 0;
      const tokFound = toks.map(() => false);
      res.forEach((r, i) => { const c = count(rule.title, r); if (c) { tokFound[i] = true; score += 60; } });
      const hits = [];
      for (const [sid, label, heading, text] of rule.secs) {
        let distinct = 0, total = 0, inHead = 0;
        res.forEach((r, i) => {
          const c = count(text, r);
          if (c) { distinct++; total += c; tokFound[i] = true; }
          if (heading && count(heading, r)) inHead++;
        });
        if (distinct) hits.push({ sid, label, heading, text, distinct, total, inHead });
      }
      if (!tokFound.every(Boolean)) continue;
      hits.sort((a, b) => b.distinct - a.distinct || b.inHead - a.inHead || b.total - a.total);
      const full = hits.filter((h) => h.distinct === toks.length);
      score += full.length * 6 + hits.reduce((s, h) => s + h.inHead * 12 + Math.min(h.total, 5), 0);
      results.push({ rule, hits, full: full.length, score });
    }
    results.sort((a, b) => b.score - a.score);
    return { toks, res, results };
  }

  // ---------- 화면 ----------
  function setTitle(t) { document.title = t ? `${t} · 인천국제공항공사 사규검색` : "인천국제공항공사 사규검색"; }
  const ruleMeta = (r) => `${r.category && r.category !== "기타" ? `<span class="badge">${esc(r.category)}</span>` : ""}개정 ${esc(r.enacted || "-")}`;

  function getRecent() { try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; } }
  function addRecent(q) {
    try {
      const list = [q, ...getRecent().filter((x) => x !== q)].slice(0, 10);
      localStorage.setItem(RECENT_KEY, JSON.stringify(list));
    } catch { /* 저장소 사용 불가 */ }
  }

  function renderHome(params) {
    setTitle("");
    qInput.value = "";
    const sort = params.get("sort") || "recent";
    const cat = params.get("cat") || "";
    const cats = [...new Set(DB.rules.map((r) => r.category).filter((c) => c && c !== "기타"))].sort();
    let rules = DB.rules.filter((r) => !cat || r.category === cat);
    rules = rules.slice().sort(sort === "name"
      ? (a, b) => a.title.localeCompare(b.title, "ko")
      : (a, b) => (b.enacted || "").localeCompare(a.enacted || ""));
    const recent = getRecent();
    const link = (k, v) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); return "#/?" + p; };
    view.innerHTML = `
      ${recent.length ? `<div class="label">최근 검색</div><div class="chips">${recent.map((q) => `<a class="chip" href="#/s?q=${encodeURIComponent(q)}">${esc(q)}</a>`).join("")}</div>` : ""}
      <div class="label">전체 사규 ${rules.length}건</div>
      <div class="seg">
        <a class="chip ${sort === "recent" ? "on" : ""}" href="${link("sort", "recent")}">최근 개정순</a>
        <a class="chip ${sort === "name" ? "on" : ""}" href="${link("sort", "name")}">가나다순</a>
      </div>
      ${cats.length > 1 ? `<div class="chips"><a class="chip ${!cat ? "on" : ""}" href="${link("cat", "")}">전체</a>${cats.map((c) => `<a class="chip ${c === cat ? "on" : ""}" href="${link("cat", c)}">${esc(c)}</a>`).join("")}</div>` : ""}
      <div class="card list">${rules.map((r) => `
        <a class="row" href="#/r/${r.id}"><span class="t">${esc(r.title)}</span><span class="d">${esc(r.enacted || "")}</span></a>`).join("")}
      </div>`;
  }

  function renderSearch(params) {
    const q = (params.get("q") || "").trim();
    qInput.value = q;
    setTitle(q);
    if (!q) return renderHome(params);
    addRecent(q);
    const { res, results } = search(q);
    const nArts = results.reduce((s, r) => s + r.hits.length, 0);
    const qp = encodeURIComponent(q);
    const shown = new Set(results.map((r) => r.rule.id));
    // 관련 사규: 상위 결과가 인용하거나 상위 결과를 인용하는 사규
    const rel = new Map();
    for (const r of results.slice(0, 5)) {
      for (const o of [...r.rule.refs, ...r.rule.refBy]) if (!shown.has(o)) rel.set(o, (rel.get(o) || 0) + 1);
    }
    const relList = [...rel.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([id]) => byId[id]).filter(Boolean);

    if (!results.length) {
      view.innerHTML = `<p class="empty">“${esc(q)}”이(가) 들어간 사규가 없습니다.<br>단어를 줄이거나 다른 표현으로 검색해 보세요.</p>`;
      return;
    }
    view.innerHTML = `
      <div class="summary">“${esc(q)}” 사규 ${results.length}건 · 조문 ${nArts}곳</div>
      ${results.map((r, i) => card(r, res, qp, i)).join("")}
      ${relList.length ? `<div class="label">관련 사규 (서로 인용하는 규정)</div><div class="chips">${relList.map((r) => `<a class="chip" href="#/r/${r.id}">${esc(r.title)}</a>`).join("")}</div>` : ""}`;
    view.querySelectorAll(".more").forEach((b) => b.addEventListener("click", () => {
      const box = $(`#more-${b.dataset.i}`); box.hidden = false; b.remove();
    }));
    window.__results = results;
  }

  function card(r, res, qp, i) {
    const hitHtml = (h) => `<a class="hit" href="#/r/${r.rule.id}/${h.sid}?q=${qp}"><b>${esc(h.label)}</b>${h.heading ? ` ${highlight(h.heading, res)}` : ""}<span class="snip">${snippet(h.text, res)}</span></a>`;
    const top = r.hits.slice(0, 3), rest = r.hits.slice(3);
    return `<div class="card">
      <h3><a href="#/r/${r.rule.id}?q=${qp}">${highlight(r.rule.title, res)}</a></h3>
      <div class="meta">${ruleMeta(r.rule)} · 조문 ${r.hits.length}곳</div>
      ${r.rule.parsed ? "" : `<div class="note">본문을 읽지 못한 사규입니다. 제목만 검색됩니다.</div>`}
      ${top.map(hitHtml).join("")}
      ${rest.length ? `<button class="more" data-i="${i}">조문 ${rest.length}곳 더 보기</button><div id="more-${i}" hidden>${rest.map(hitHtml).join("")}</div>` : ""}
    </div>`;
  }

  async function loadDetail(id) {
    if (!detailCache[id]) {
      const r = await fetch(`data/rules/${id}.json`);
      if (!r.ok) throw new Error(r.status);
      detailCache[id] = await r.json();
    }
    return detailCache[id];
  }

  const ART_HEAD = /^(제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*\([^)]*\))?)/;
  function blockHtml(b, res) {
    if (b.p) {
      const m = b.p.match(ART_HEAD);
      if (m) return `<p><strong>${highlight(m[1], res)}</strong>${highlight(b.p.slice(m[1].length), res)}</p>`;
      return `<p>${highlight(b.p, res)}</p>`;
    }
    return `<div class="tw"><table>${b.table.map((row) => `<tr>${row.map((c) => `<td${c.c ? ` colspan="${c.c}"` : ""}${c.r ? ` rowspan="${c.r}"` : ""}>${highlight(c.t, res)}</td>`).join("")}</tr>`).join("")}</table></div>`;
  }

  async function renderRule(id, sid, params) {
    const q = (params.get("q") || "").trim();
    const meta = byId[id];
    if (!meta) { view.innerHTML = `<p class="empty">사규를 찾을 수 없습니다.</p>`; return; }
    setTitle(meta.title);
    qInput.value = q;
    view.innerHTML = `<p class="empty">불러오는 중…</p>`;
    let d;
    try { d = await loadDetail(id); } catch { view.innerHTML = `<p class="empty">본문을 불러오지 못했습니다.</p>`; return; }
    const res = tokenize(q).map((t) => tokenRe(t));
    const refs = meta.refs.map((x) => byId[x]).filter(Boolean);
    const refBy = meta.refBy.map((x) => byId[x]).filter(Boolean);
    let lastChap = "";
    const toc = [];
    const secs = d.sections.map((s) => {
      let chapHtml = "";
      if (s.chapter && s.chapter !== lastChap && s.kind !== "addenda") {
        lastChap = s.chapter; toc.push(`<li class="ch">${esc(s.chapter)}</li>`);
        chapHtml = `<div class="chap">${esc(s.chapter)}</div>`;
      }
      if (s.kind !== "head") toc.push(`<li><a href="#/r/${id}/${s.id}${q ? `?q=${encodeURIComponent(q)}` : ""}">${esc(s.label)}${s.heading ? ` ${esc(s.heading)}` : ""}</a></li>`);
      return `${chapHtml}<section class="sec" id="${s.id}">${s.blocks.filter((b) => !(b.p && s.chapter && b.p === s.chapter && s.kind !== "addenda")).map((b) => blockHtml(b, res)).join("")}</section>`;
    });
    const dl = `https://www.alio.go.kr/download/rulefiledown.json?fileNo=${d.fileNo}`;
    view.innerHTML = `
      <div class="dhead">
        <div class="meta">${ruleMeta(meta)}${d.effective ? ` · 시행 ${esc(d.effective)}` : ""}</div>
        <h2>${esc(d.title)}</h2>
        <div class="links">
          <a class="btn primary" href="${dl}" target="_blank" rel="noopener">원문 파일 받기</a>
          <a class="btn" href="${esc(d.url)}" target="_blank" rel="noopener">알리오에서 보기</a>
          ${q ? `<a class="btn" href="#/s?q=${encodeURIComponent(q)}">← 검색 결과</a>` : ""}
        </div>
        ${d.attachments.length ? `<div class="note">함께 올라온 파일: ${d.attachments.map(esc).join(", ")} (원문 파일에 포함)</div>` : ""}
        ${refs.length ? `<div class="label">이 사규가 인용하는 사규</div><div class="chips">${refs.map((r) => `<a class="chip" href="#/r/${r.id}">${esc(r.title)}</a>`).join("")}</div>` : ""}
        ${refBy.length ? `<div class="label">이 사규를 인용하는 사규</div><div class="chips">${refBy.map((r) => `<a class="chip" href="#/r/${r.id}">${esc(r.title)}</a>`).join("")}</div>` : ""}
      </div>
      <div class="findbar"><span class="ftitle">${esc(d.title)}</span><input id="find" type="search" placeholder="이 사규 안에서 찾기" value="${esc(q)}" enterkeyhint="search"><span class="cnt" id="findCnt"></span><button id="prev" aria-label="이전">▲</button><button id="next" aria-label="다음">▼</button></div>
      ${toc.length > 1 ? `<details class="toc"><summary>목차 (${d.sections.filter((s) => s.kind !== "head").length})</summary><ol>${toc.join("")}</ol></details>` : ""}
      ${d.parsed ? `<div class="doc">${secs.join("")}</div>` : `<div class="note">이 사규는 본문을 자동으로 읽지 못했습니다. 위의 ‘원문 파일 받기’로 확인해 주세요.</div>`}`;
    setupFind(id, d, q);
    if (sid) {
      const el = document.getElementById(sid);
      if (el) { requestAnimationFrame(() => { el.scrollIntoView({ block: "start" }); el.classList.add("target"); }); }
    } else window.scrollTo(0, 0);
  }

  function setupFind(id, d, q0) {
    const input = $("#find"), cnt = $("#findCnt");
    let marks = [], cur = -1;
    const apply = () => {
      const q = input.value.trim();
      const res = tokenize(q).map((t) => tokenRe(t));
      view.querySelectorAll(".sec").forEach((el, i) => {
        const s = d.sections[i];
        if (!s) return;
        el.innerHTML = s.blocks.filter((b) => !(b.p && s.chapter && b.p === s.chapter && s.kind !== "addenda")).map((b) => blockHtml(b, res)).join("");
      });
      marks = [...view.querySelectorAll(".doc mark")];
      cur = -1;
      cnt.textContent = q ? `${marks.length}건` : "";
    };
    const go = (dir) => {
      if (!marks.length) return;
      if (cur >= 0) marks[cur].classList.remove("cur");
      cur = (cur + dir + marks.length) % marks.length;
      marks[cur].classList.add("cur");
      marks[cur].scrollIntoView({ block: "center" });
      cnt.textContent = `${cur + 1}/${marks.length}`;
    };
    let t;
    input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(apply, 250); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); input.blur(); go(1); } });
    $("#next").addEventListener("click", () => go(1));
    $("#prev").addEventListener("click", () => go(-1));
    marks = [...view.querySelectorAll(".doc mark")];
    if (q0) cnt.textContent = `${marks.length}건`;
  }

  // ---------- 라우팅 ----------
  function route() {
    if (!DB) return;
    const h = location.hash.slice(1) || "/";
    const [path, qs] = h.split("?");
    const params = new URLSearchParams(qs || "");
    const parts = path.split("/").filter(Boolean);
    if (parts[0] === "r" && parts[1]) return renderRule(parts[1], parts[2], params);
    if (parts[0] === "s") { window.scrollTo(0, 0); return renderSearch(params); }
    window.scrollTo(0, 0);
    renderHome(params);
  }

  $("#searchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = qInput.value.trim();
    qInput.blur();
    location.hash = q ? `#/s?q=${encodeURIComponent(q)}` : "#/";
  });
  window.addEventListener("hashchange", route);
  const setTopH = () => document.documentElement.style.setProperty("--top-h", $(".top").offsetHeight + "px");
  setTopH(); window.addEventListener("resize", setTopH);

  const top = document.createElement("button");
  top.className = "totop"; top.textContent = "↑"; top.setAttribute("aria-label", "맨 위로");
  top.onclick = () => window.scrollTo({ top: 0, behavior: "smooth" });
  document.body.appendChild(top);
  window.addEventListener("scroll", () => top.classList.toggle("show", window.scrollY > 600), { passive: true });

  fetch("data/index.json").then((r) => r.json()).then((db) => {
    DB = db;
    byId = Object.fromEntries(db.rules.map((r) => [r.id, r]));
    const d = (db.collectedAt || "").slice(0, 10);
    $("#sub").textContent = `${db.rules.length}개 사규${d ? ` · ${d} 기준` : ""}`;
    if (db.source) $("#srcLink").href = db.source;
    route();
  }).catch(() => { view.innerHTML = `<p class="empty">데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>`; });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
})();
