// 전결권자 찾기: 문장이나 비슷한 말로 물어봐도 위임전결규정 별표에서 가까운 업무를 골라 준다 (서버 없이 휴대폰에서 계산)
(function (root) {
  "use strict";

  // 의도 표현 (있으면 전결권자를 묻는 질문으로 본다)
  const INTENT = ["전결권자", "전결라인", "전결", "결재권자", "결재라인", "결재", "승인권자", "승인", "누가", "누구", "어디까지", "윗선"];
  // 검색에서 버릴 말
  const STOP = new Set(["가려면", "쓰려면", "받으려면", "하려는데", "쓸", "갈", "알려줘", "알려주세요", "뭐야", "뭐예요", "어떻게", "되나요", "돼", "되는지", "해야", "하나요", "해요", "해", "하는", "하는지", "받아야", "받나요", "받아", "관련", "건", "것", "때", "경우", "좀", "제가", "내가", "우리", "직원이", "직원", "하려면", "하려고", "할", "하면", "처리", "업무", "사항", "에", "가", "이", "은", "는", "을", "를", "의", "도", "만", "까지", "부터"]);
  // 조사·어미 떼기 (긴 것부터)
  const ENDINGS = ["으려면", "하려면", "려면", "하기", "으로는", "에서는", "하려면", "하려고", "할때는", "할때", "하는데", "인가요", "이에요", "예요", "에서", "으로", "에게", "한테", "까지", "부터", "하면", "해야", "해요", "나요", "는요", "은요", "이랑", "랑", "하고", "와", "과", "은", "는", "이", "가", "을", "를", "의", "에", "로", "도", "만", "요"];
  // 비슷한 말 → 별표에 실제로 쓰인 말
  const SYN = {
    "해외": ["국외"], "외국": ["국외"], "해외출장": ["국외출장"], "외국출장": ["국외출장"],
    "연차": ["휴가"], "휴무": ["휴가"], "반차": ["휴가", "시간단위"], "쉬는": ["휴가"],
    "외근": ["외출", "근거리"], "지각": ["조퇴", "외출"], "출장비": ["여비", "출장"],
    "협약": ["협정", "양해각서", "협약"], "mou": ["양해각서"], "엠오유": ["양해각서"],
    "돈": ["지출", "예산"], "비용": ["지출", "예산"], "집행": ["집행", "지출"], "결제": ["지출"], "카드": ["법인카드"],
    "구매": ["구매", "물품", "발주"], "구입": ["구매", "물품"], "조달": ["조달", "계약"], "외주": ["용역", "아웃소싱"],
    "채용": ["임면", "선임"], "임용": ["임면"], "뽑기": ["임면"], "발령": ["인사발령", "전보"], "인사이동": ["전보", "인사발령"],
    "승진": ["승진"], "평가": ["평가"], "그만": ["퇴직"], "사직": ["퇴직"], "퇴사": ["퇴직"], "육아휴직": ["휴직"],
    "표창": ["포상"], "상": ["포상"], "처벌": ["징계"], "문책": ["징계"],
    "교육": ["교육훈련", "연수"], "연수": ["연수원", "교육훈련"], "강사": ["강사"],
    "월급": ["보수"], "급여": ["보수"], "수당": ["보수"], "복지": ["복리후생"],
    "공문": ["문서"], "도장": ["직인", "인감"], "증명서": ["제증명서"], "재직증명": ["제증명서"],
    "소송": ["소송"], "변호사": ["소송", "법률자문"], "법률": ["법률자문", "법령"], "규정": ["사규", "절차(지침)서"], "지침": ["절차(지침)서", "매뉴얼"],
    "보도자료": ["언론"], "기자": ["언론"], "언론": ["언론"], "광고": ["광고"], "홈페이지": ["홈페이지"], "sns": ["뉴미디어"],
    "회의": ["위원회", "협의체", "자문회의"], "행사": ["행사"], "자료": ["자료제출"], "국회": ["국회"],
    "보험": ["보험부보"], "세금": ["세무"], "회계": ["회계결산"], "재산": ["재산"],
    "공사": ["공사", "시공"], "설계": ["설계"], "감리": ["감리"], "유지보수": ["유지보수"], "수리": ["유지보수"], "점검": ["점검"],
    "보안": ["보안"], "개인정보": ["개인정보보호"], "안전": ["안전"], "재난": ["재난"], "소방": ["구조소방"], "제설": ["제설"],
    "민원": ["민원"], "정보공개": ["정보공개"], "차": ["차량"], "자동차": ["차량"],
    "계약변경": ["계약의 변경"], "계약연장": ["계약연장"], "입찰": ["입찰"], "낙찰": ["낙찰"], "계약": ["계약"],
    "회식": ["지출"], "경비": ["지출"], "업무추진비": ["지출"], "회의비": ["지출"], "경조": ["경조"], "야근": ["시간외", "보수"], "초과근무": ["보수"],
    "예산": ["예산"], "투자": ["투자"], "이사회": ["이사회"], "겸직": ["겸업", "겸임"], "부업": ["겸업"],
    "파견": ["파견"], "기부": ["기부"], "사회공헌": ["사회공헌"], "봉사": ["사회공헌"],
  };
  // 직급 (질문에 있으면 그 직급 줄을 먼저)
  const ROLES = [
    ["팀원", ["팀원", "팀장이하"]], ["직원", ["팀원", "팀장이하"]], ["사원", ["팀원", "팀장이하"]],
    ["팀장", ["팀장", "팀장이하"]], ["처장", ["처장", "처장이상"]], ["실장", ["처장"]],
    ["본부장", ["본부장"]], ["단장", ["단장"]], ["부사장", ["부사장"]],
  ];
  // 일의 종류만 말하는 일반어 (업무 대상보다 가볍게 본다)
  const GENERIC = new Set(["시행방침", "방침", "계획", "계획수립", "수립", "시행", "관리", "운영", "보고", "결과보고", "검토", "승인", "결정", "처리", "신청", "작성", "수립및시행"]);
  const ROLE_WORDS = new Set(ROLES.map((r) => r[0]));

  const norm = (s) => String(s).toLowerCase().replace(/\s+/g, "");
  function bigrams(s) { const a = []; for (let i = 0; i < s.length - 1; i++) a.push(s.slice(i, i + 2)); return a; }
  function strip(w) {
    for (const e of ENDINGS) if (w.length > e.length + 1 && w.endsWith(e)) return w.slice(0, -e.length);
    return w;
  }

  let ROWS = [];
  let HAY = "";
  function build(db) {
    ROWS = [];
    const rule = db.rules.find((r) => r.title === "위임전결규정") || db.rules.find((r) => r.secs.some((s) => s[1] === "전결"));
    if (!rule) return 0;
    for (const [sid, label, heading, text, cat] of rule.secs) {
      if (label !== "전결") continue;
      const unit = heading.replace(/^\d+\.\s*/, "");
      for (const line of text.split("\n")) {
        const i = line.lastIndexOf("|");
        if (i < 0) continue;
        const detail = line.slice(0, i).trim(), who = line.slice(i + 1).trim();
        if (!who) continue;
        const ex = (unit.match(/\(([^)]*제외[^)]*)\)/) || [])[1] || "";
        ROWS.push({ idx: ROWS.length, ruleId: rule.id, sid, unit, cat: cat || "", detail, who, nu: norm(unit.replace(/\([^)]*제외[^)]*\)/, "")), nd: norm(detail), nex: norm(ex) });
      }
    }
    HAY = ROWS.map((r) => r.nu + " " + r.nd).join(" ");
    return ROWS.length;
  }

  // 질문 분석
  function parse(q) {
    const raw = String(q).toLowerCase().replace(/[?？!.,~·…"'“”‘’()]/g, " ");
    let intent = false;
    let s = raw;
    for (const w of INTENT) if (s.includes(w)) { intent = true; s = s.split(w).join(" "); }
    const roles = [], terms = [];
    for (let w of s.split(/\s+/).filter(Boolean)) {
      if (!HAY.includes(w)) w = strip(w);
      if (!w || STOP.has(w)) continue;
      const role = ROLES.find((r) => w === r[0] || (w.startsWith(r[0]) && w.length <= r[0].length + 1));
      if (role) { roles.push(role); continue; }
      if (w.length < 2 && !SYN[w]) continue;
      terms.push(w);
    }
    // 붙여 쓴 직급 (예: "팀장휴가")
    for (let i = 0; i < terms.length; i++) {
      for (const r of ROLES) if (terms[i].startsWith(r[0]) && terms[i].length > r[0].length + 1) { roles.push(r); terms[i] = terms[i].slice(r[0].length); }
    }
    return { intent, roles, terms: [...new Set(terms)] };
  }

  function synonyms(t) {
    const out = new Set();
    if (t.length >= 2 && /[비금료]$/.test(t)) out.add("지출");
    for (const [k, vs] of Object.entries(SYN)) {
      if (t === k || (k.length >= 2 && t.includes(k))) vs.forEach((v) => out.add(norm(v)));
    }
    out.delete(t);
    return [...out];
  }

  function find(q, limit = 8) {
    const p = parse(q);
    if (!ROWS.length || !p.terms.length) return { ...p, units: [], rows: [] };
    const hayAll = ROWS.map((r) => r.nu + r.nd).join(" ");
    const terms = [];
    for (const t of p.terms) {
      terms.push(t);
      if (t.length >= 4 && !hayAll.includes(t)) {
        for (let k = 2; k <= t.length - 2; k++) {
          const a = t.slice(0, k), b = t.slice(k);
          if ((hayAll.includes(a) || SYN[a]) && (hayAll.includes(b) || SYN[b])) { terms.pop(); terms.push(a, b); break; }
        }
      }
    }
    const N = ROWS.length;
    const groups = [...new Set(terms)].map((t) => {
      const syn = synonyms(t);
      const df = ROWS.filter((r) => r.nu.includes(t) || r.nd.includes(t) || syn.some((x) => r.nu.includes(x) || r.nd.includes(x))).length;
      const w = (0.7 + 0.6 * Math.log(N / (df + 1)) / Math.log(N)) * (GENERIC.has(t) ? 0.55 : 1);
      const exact = ROWS.some((r) => r.nu.includes(t) || r.nd.includes(t));
      return { t, syn, bg: bigrams(t), w, sw: exact ? 0.45 : 1 };
    });
    const scored = [];
    for (const r of ROWS) {
      let score = 0, matched = 0;
      const why = [], excluded = [];
      for (const g of groups) {
        let best = 0, how = "";
        if (r.nex && r.nex.includes(g.t) && !r.nu.includes(g.t) && !r.nd.includes(g.t)) { excluded.push(g.t); continue; }
        if (r.nu.includes(g.t)) { best = 4; how = g.t; }
        else if (r.nd.includes(g.t)) { best = 3; how = g.t; }
        else {
          for (const s of g.syn) {
            if (r.nu.includes(s)) { if (best < 3 * g.sw) { best = 3 * g.sw; how = `${g.t}→${s}`; } }
            else if (r.nd.includes(s)) { if (best < 2.5 * g.sw) { best = 2.5 * g.sw; how = `${g.t}→${s}`; } }
          }
          if (!best && g.bg.length >= 2) {
            const hay = r.nu + " " + r.nd;
            const hit = g.bg.filter((b) => hay.includes(b)).length / g.bg.length;
            if (hit >= 0.5) { best = 2 * hit; how = g.t + "(유사)"; }
          }
        }
        if (best) { score += best * g.w; matched++; why.push(how); }
      }
      if (!matched && !excluded.length) continue;
      score -= excluded.length * 1.5;
      score += (matched / groups.length) * 3;  // 질문의 낱말을 많이 덮을수록
      if (p.roles.length) {
        const keys = p.roles.flatMap((r) => r[1]);
        if (keys.some((k) => r.nd.includes(k))) score += 2.5;
        else if (/팀원|팀장|처장|본부장|단장|부사장/.test(r.nd)) score -= 0.5;
      }
      const fuzzy = why.filter((w) => w.endsWith("(유사)")).length, viaSyn = why.filter((w) => w.includes("→")).length;
      scored.push({ ...r, score, matched, why, excluded, fuzzy, viaSyn });
    }
    scored.sort((a, b) => b.score - a.score || a.detail.length - b.detail.length);
    // 단위업무별로 묶기
    const units = [];
    const byKey = new Map();
    for (const r of scored) {
      let u = byKey.get(r.sid);
      if (!u) { u = { sid: r.sid, ruleId: r.ruleId, unit: r.unit, cat: r.cat, score: r.score, rows: [], why: new Set(), excluded: new Set(), roleHit: false }; byKey.set(r.sid, u); units.push(u); }
      if (u.rows.length < 10) u.rows.push(r);
      r.why.forEach((w) => u.why.add(w));
      r.excluded.forEach((w) => u.excluded.add(w));
    }
    for (const u of units) {
      const fullRows = scored.filter((x) => x.sid === u.sid && x.matched === groups.length).length;
      u.score += 0.25 * Math.min(fullRows, 6);
    }
    units.sort((a, b) => b.score - a.score);
    return { ...p, units: units.slice(0, limit), rows: scored, terms: groups.map((g) => g.t), full: groups.length };
  }


  // 제4조③: 별표에 없는 사항의 결재권자 기준
  const LEVELS = [
    { who: "사장", text: "이사회 심의·의결 및 보고를 요하는 사항, 중요 정책 및 기본방침", keys: ["이사회", "기본방침", "중요정책", "정책", "주주총회"] },
    { who: "부사장", text: "중장기 전략·연도별 경영계획에 따른 소관부문 사업/운영계획 수립 및 대외 업무, 본부 간 업무조정", keys: ["본부간", "중장기", "경영계획", "전사"] },
    { who: "본부장/단장", text: "소관부문 사업/운영계획 수립, 소관부문 대외 업무, 본부·단 내 업무조정", keys: ["사업계획", "운영계획", "대외", "외부기관", "정부", "국토부", "본부내", "단내", "처간"] },
    { who: "처장", text: "본부 사업/운영계획에 따른 실행계획 수립 및 실행관리", keys: ["실행계획", "실행", "시행계획"] },
    { who: "팀장", text: "처 실행계획에 따른 세부 업무계획 수립 및 실행관리", keys: ["세부계획", "세부", "팀내", "일상"] },
  ];
  function levelHint(q) {
    const n = norm(q);
    for (let i = 0; i < LEVELS.length; i++) if (LEVELS[i].keys.some((k) => n.includes(k))) return i;
    return -1;
  }

  const api = { build, find, parse, INTENT, LEVELS, levelHint };
  if (typeof module !== "undefined") module.exports = api; else root.Jeongyeol = api;
})(this);
