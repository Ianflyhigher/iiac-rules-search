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


  // ---------- 전결권자 판단 ----------
  let JG_READY = false;
  function approvalPanel(q, force) {
    const J = window.Jeongyeol;
    if (!J) return "";
    if (!JG_READY) { J.build(DB); JG_READY = true; }
    const r = J.find(q, 6);
    const RID = (DB.rules.find((x) => x.title === "위임전결규정") || {}).id;
    const art = (n) => RID ? `<a href="#/r/${RID}/s${n}">제${n}조</a>` : `제${n}조`;
    const u0 = r.units[0];
    const b0 = u0 && u0.rows[0];
    const full = b0 && b0.matched === r.full;
    if (!(r.intent || force || full)) return "";
    if (!u0 && !r.intent) return "";
    // 확신 정도: 상(질문의 낱말이 별표에 그대로) / 중(비슷한 말로 맞춤) / 하(일부만 맞거나 못 찾음)
    const conf = !b0 ? 0 : full && !b0.fuzzy && !b0.viaSyn && !u0.excluded.size ? 2 : full && !b0.fuzzy ? 1 : 0;
    const lv = J.levelHint(q);
    const rule43 = `<div class="jg-rule"><b>별표에 딱 맞는 업무가 없을 때</b> (${art(4)} ③): 별표의 비슷한 전결사항에 준하거나 아래 기준으로 결재권자를 정해요.
      <ul>${J.LEVELS.map((L, i) => `<li class="${i === lv ? "me" : ""}"><b>${L.who}</b> ${esc(L.text)}</li>`).join("")}</ul>
      <div class="jg-why">별표에 그 직위가 없으면 차하위 직위자가 결재해요 (${art(4)} ④). 전결로 처리해도 특히 중요한 사항은 상위자에게 보고해요 (${art(5)} ②).</div></div>`;
    if (!u0) {
      return `<div class="card jg"><div class="jg-h">전결권자 판단 <small>위임전결규정 기준</small></div>
        <div class="jg-best">별표에서 이 업무와 비슷한 항목을 찾지 못했어요.${lv >= 0 ? ` 질문 내용으로 보면 <b>${J.LEVELS[lv].who}</b> 전결로 판단돼요.` : ""}</div>${rule43}</div>`;
    }
    const roleKeys = r.roles.flatMap((x) => x[1]);
    const isRole = (row) => roleKeys.length && roleKeys.some((k) => row.nd.includes(k));
    const rows = u0.rows.slice().sort((a, b) => isRole(b) - isRole(a) || a.idx - b.idx);
    const why = [...u0.why].map((w) => w.includes("→") ? `‘${w.split("→")[0]}’ ≈ ‘${w.split("→")[1]}’` : w.endsWith("(유사)") ? `‘${w.replace("(유사)", "")}’ 비슷` : `‘${w}’ 일치`);
    const notes = [];
    if (rows.some((x) => /\d[\d,]*\s*(억|천만|백만|만)?\s*원/.test(x.detail))) notes.push("금액 구간에 따라 전결권자가 달라요. 금액은 부가세를 뺀 금액이에요 (별표 안내).");
    if (rows.some((x) => x.who.startsWith("본부장/단장"))) notes.push("본부장/단장 전결사항이라도 사장·부사장 직속부서는 처/실장 전결이고, 중요사항은 그 직상위자로 올려 처리해요 (별표 안내).");
    if (rows.some((x) => /중요|일반/.test(x.detail))) notes.push(`중요사항은 공사의 권리의무를 정하거나 경영상 중대한 영향을 미치는 사항, 일반사항은 정해진 절차·범위대로 시행하거나 권리의무를 수반하지 않는 사항이에요 (${art(3)}).`);
    if (!roleKeys.length && rows.filter((x) => /팀원|팀장|처장|본부장|부사장/.test(x.detail)).length > 1) notes.push("직급에 따라 달라요. 본인(기안자) 직급 줄을 보세요.");
    if (u0.excluded.size) notes.push(`이 업무 제목에는 ‘${[...u0.excluded].join(", ")}’을(를) 제외한다고 적혀 있어요.`);
    const link = (u) => `#/r/${u.ruleId}/${u.sid}`;
    const alts = r.units.slice(1, 4);
    const cat = (u) => u.cat ? ` <span class="cat">${esc(u.cat)}</span>` : "";
    const head = conf === 2 ? `별표의 <a href="${link(u0)}"><b>${esc(u0.unit)}</b></a>${cat(u0)} 항목이에요.`
      : conf === 1 ? `별표에 그대로 있지는 않지만 <a href="${link(u0)}"><b>${esc(u0.unit)}</b></a>${cat(u0)}에 해당하는 것으로 판단돼요.`
      : `딱 맞는 항목은 없어요. 가장 비슷한 것은 <a href="${link(u0)}"><b>${esc(u0.unit)}</b></a>${cat(u0)}이고, ${art(4)} ③에 따라 이 전결사항에 준해 판단할 수 있어요.`;
    return `<div class="card jg">
      <div class="jg-h">전결권자 판단 <small>위임전결규정 별표 기준</small></div>
      <div class="jg-best">${head}</div>
      ${conf < 2 && lv >= 0 ? `<div class="jg-best">또 질문 내용은 ${art(4)} ③ 기준으로 <b>${J.LEVELS[lv].who}</b> 결재 사항에 가까워요. 두 기준 중 업무 성격에 맞는 쪽을 따르세요.</div>` : ""}
      <div class="tw"><table><tr><th>세부업무</th><th>전결권자</th></tr>${rows.map((x) => `<tr class="${isRole(x) ? "me" : ""}"><td>${esc(x.detail)}</td><td class="who">${esc(x.who)}</td></tr>`).join("")}</table></div>
      ${why.length ? `<div class="jg-why">판단 근거: ${esc(why.join(", "))}</div>` : ""}
      ${notes.map((n) => `<div class="jg-why">※ ${n}</div>`).join("")}
      ${alts.length ? `<div class="jg-alt">다만 이런 전결사항일 수도 있어요. 실제 업무에 맞는지 판단해 보세요.</div>
      <div class="jg-alts">${alts.map((u, i) => `<a class="jg-altbox" href="${link(u)}"><span class="no">${i + 1}</span><span class="t">${esc(u.unit)}${u.cat ? ` <small>${esc(u.cat)}</small>` : ""}</span><span class="d">${esc(u.rows[0].detail)}</span><span class="w">전결권자 <b>${esc(u.rows[0].who)}</b></span></a>`).join("")}</div>` : ""}
      ${conf < 2 ? rule43 : ""}
    </div>`;
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
      ${recent.length ? `<div class="label sec sec-recent">최근 검색</div><div class="chips one">${recent.map((q) => `<a class="chip" href="#/s?q=${encodeURIComponent(q)}">${esc(q)}</a>`).join("")}</div>` : ""}
      <div class="label sec sec-jg">전결권자 물어보기 <small>문장으로 물어봐도 돼요</small></div>
      <div class="chips one">${["해외출장 결재", "팀원 연차", "계약변경 전결"].map((q) => `<a class="chip" href="#/s?q=${encodeURIComponent(q)}">${esc(q)}</a>`).join("")}</div>
      <div class="label sec sec-all">전체 사규 ${rules.length}건</div>
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
    const jg = approvalPanel(q);
    let { res, results } = search(q);
    if (!results.length && window.Jeongyeol) {
      // 문장으로 물어본 경우: 조사·질문 표현을 빼고 다시 찾기
      const terms = window.Jeongyeol.parse(q).terms;
      if (terms.length && terms.join(" ") !== q) ({ res, results } = search(terms.join(" ")));
    }
    if (jg) {
      const only = results.filter((x) => x.rule.title === "위임전결규정");
      if (only.length) results = only;
    }
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
      view.innerHTML = jg || `<p class="empty">“${esc(q)}”이(가) 들어간 사규가 없습니다.<br>단어를 줄이거나 다른 표현으로 검색해 보세요.</p>`;
      return;
    }
    view.innerHTML = `${jg}
      <div class="summary">“${esc(q)}” 사규 ${results.length}건 · 조문 ${nArts}곳</div>
      ${results.map((r, i) => card(r, res, qp, i)).join("")}
`;
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

  // 서식 표: 낱말이 칸을 넘치면 그 표의 글씨를 조금씩 줄여 줄이 안 나뉘게
  function fitTables(root = view) {
    root.querySelectorAll(".tw table.fx").forEach((tb) => {
      let fs = 13;
      tb.style.fontSize = fs + "px";
      const over = () => [...tb.querySelectorAll("td,th")].some((c) => c.scrollWidth > c.clientWidth + 1);
      while (fs > 9.5 && over()) { fs -= 0.5; tb.style.fontSize = fs + "px"; }
    });
  }

  const ART_HEAD = /^(제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*\([^)]*\))?)/;
  function blockHtml(b, res) {
    if (b.p) {
      const m = b.p.match(ART_HEAD);
      if (m) return `<p><strong>${highlight(m[1], res)}</strong>${highlight(b.p.slice(m[1].length), res)}</p>`;
      return `<p>${highlight(b.p, res)}</p>`;
    }
    const AL = { c: "center", r: "right", l: "left" };
    const cellBody = (c) => (c.la || c.lb)
      ? c.t.split("\n").map((ln, i) => `<div${c.lb && c.lb[i] === "1" ? ' class="big"' : ""}${c.la ? ` style="text-align:${AL[c.la[i]] || "left"}"` : ""}>${highlight(ln, res) || "&nbsp;"}</div>`).join("")
      : highlight(c.t, res);
    const cls = (c) => [c.a ? `a${c.a}` : "", c.big ? "big" : ""].filter(Boolean).join(" ");
    let w = b.w;
    if (w) { const fl = Math.min(13, 60 / w.length); w = w.map((x) => Math.max(x, fl)); const t = w.reduce((a, x) => a + x, 0); w = w.map((x) => +(x * 100 / t).toFixed(1)); }
    const fw = w ? ` class="fx" style="min-width:${w.length * 56}px"` : "";
    const cg = w ? `<colgroup>${w.map((x) => `<col style="width:${x}%">`).join("")}</colgroup>` : "";
    return `<div class="tw"><table${fw}>${cg}${b.table.map((row) => `<tr>${row.map((c) => { const k = cls(c); return `<${c.h ? "th" : "td"}${k ? ` class="${k}"` : ""}${c.c ? ` colspan="${c.c}"` : ""}${c.r ? ` rowspan="${c.r}"` : ""}>${cellBody(c)}</${c.h ? "th" : "td"}>`; }).join("")}</tr>`).join("")}</table></div>`;
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
      return `${chapHtml}<section class="sec${s.kind === "head" ? " head" : ""}" id="${s.id}">${s.blocks.filter((b) => !(b.p && s.chapter && b.p === s.chapter && s.kind !== "addenda")).map((b) => blockHtml(b, res)).join("")}</section>`;
    });
    const dl = `https://www.alio.go.kr/download/rulefiledown.json?fileNo=${d.fileNo}`;
    view.innerHTML = `
      <div class="dhead">
        <div class="trow"><h2>${esc(d.title)}</h2><a class="btn sm back" id="backBtn" href="${q ? `#/s?q=${encodeURIComponent(q)}` : "#/"}">뒤로가기</a></div>
        <div class="meta">${ruleMeta(meta)}${d.effective ? ` · 시행 ${esc(d.effective)}` : ""}</div>
        ${refs.length ? `<div class="label rl">이 사규가 인용하는 사규</div><div class="chips sm">${refs.map((r) => `<a class="chip" href="#/r/${r.id}">${esc(r.title)}</a>`).join("")}</div>` : ""}
        ${refBy.length ? `<div class="label rl">이 사규를 인용하는 사규</div><div class="chips sm">${refBy.map((r) => `<a class="chip" href="#/r/${r.id}">${esc(r.title)}</a>`).join("")}</div>` : ""}
      </div>
      <div class="findbar"><span class="ftitle">${esc(d.title)}</span><input id="find" type="search" placeholder="이 사규 안에서 찾기" value="${esc(q)}" enterkeyhint="search"><span class="cnt" id="findCnt"></span><button id="prev" aria-label="이전">▲</button><button id="next" aria-label="다음">▼</button></div>
      ${toc.length > 1 ? `<details class="toc"><summary>목차 (${d.sections.filter((s) => s.kind !== "head").length})</summary><ol>${toc.join("")}</ol></details>` : ""}
      ${d.parsed ? `<div class="doc">${secs.join("")}</div>` : `<div class="note">이 사규는 본문을 자동으로 읽지 못했습니다. 아래 ‘원문 파일 받기’로 확인해 주세요.</div>`}
      <div class="links bottom">
        <a class="btn sm primary" href="${dl}" target="_blank" rel="noopener">원문 파일 받기</a>
        <a class="btn sm" href="${esc(d.url)}" target="_blank" rel="noopener">알리오에서 보기</a>
      </div>
      ${d.attachments.length ? `<div class="note fnote">함께 올라온 파일: ${d.attachments.map(esc).join(", ")} (원문 파일에 포함)</div>` : ""}`;
    setupFind(id, d, q);
    fitTables();
    const bb = $("#backBtn");
    if (bb && history.length > 1) bb.addEventListener("click", (e) => { e.preventDefault(); history.back(); });
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
      fitTables();
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
  setTopH(); window.addEventListener("resize", () => { setTopH(); fitTables(); });

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
