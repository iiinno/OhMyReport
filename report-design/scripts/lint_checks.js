// report-design のレンダリング検査。lint_report.py がページへ差し込んで実行する。
// 結果は ASCII だけの JSON にして、id が __rdlint_out の pre へ書き出す。
(function () {
  const CFG = window.__RDLINT_CFG;
  const MODE = CFG.mode; // desktop | mobile | print
  const issues = [];
  const SKIP_ID = /^__rdlint/;

  function add(rule, level, msg, el) {
    issues.push({ rule, level, msg, where: el ? where(el) : "" });
  }

  function where(el) {
    const parts = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 3; i++, n = n.parentElement) {
      let s = n.tagName.toLowerCase();
      if (n.id) s += "#" + n.id;
      const cls = (n.getAttribute("class") || "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
      if (cls.length) s += "." + cls.join(".");
      parts.unshift(s);
      if (n.tagName === "BODY") break;
    }
    const text = (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 24);
    return parts.join(" > ") + (text ? " 「" + text + "」" : "");
  }

  // ---------- 色 ----------
  function parseColor(s) {
    if (!s) return null;
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  function hex(c) {
    return "#" + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, "0")).join("").toUpperCase();
  }
  function lum(c) {
    const a = c.slice(0, 3).map(v => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
  }
  function ratio(a, b) {
    const x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  function blend(top, under) {
    const a = top[3];
    return [0, 1, 2].map(i => top[i] * a + under[i] * (1 - a)).concat(1);
  }
  function bgOf(el) {
    const stack = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = parseColor(getComputedStyle(n).backgroundColor);
      if (c && c[3] > 0) {
        stack.push(c);
        if (c[3] >= 1) break;
      }
    }
    let out = [255, 255, 255, 1];
    for (let i = stack.length - 1; i >= 0; i--) out = blend(stack[i], out);
    return out;
  }

  const PALETTE = new Set(CFG.palette.map(s => s.toUpperCase()));
  // 文書が独自の --accent を持っていても、それを強調色として数える
  const ACCENT = new Set(CFG.accent.map(s => s.toUpperCase()));
  for (const name of ["--accent", "--accent-ink"]) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim().toUpperCase();
    if (/^#[0-9A-F]{6}$/.test(v)) ACCENT.add(v);
  }

  // ---------- 対象の集め方 ----------
  const all = Array.from(document.body.querySelectorAll("*")).filter(el => !SKIP_ID.test(el.id || ""));
  function visible(el) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function inSvg(el) { return el instanceof SVGElement; }
  function ownText(el) {
    let t = "";
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
    return t.trim();
  }
  const vis = all.filter(visible);
  const htmlText = vis.filter(el => !inSvg(el) && ownText(el) && !["SCRIPT", "STYLE", "TITLE"].includes(el.tagName));
  const px = v => parseFloat(v) || 0;

  // ---------- X2: トークンが base.css のままか ----------
  const rootCs = getComputedStyle(document.documentElement);
  if (!rootCs.getPropertyValue("--paper").trim()) {
    add("X2", "error", "base.css が埋め込まれていない。assets/base.css をそのまま <style> に入れる", null);
  } else if (MODE !== "print") {
    const diff = [];
    for (const [name, val] of Object.entries(CFG.tokens)) {
      const got = rootCs.getPropertyValue(name).trim().replace(/\s+/g, " ");
      if (got.toUpperCase() !== val.toUpperCase()) diff.push(`${name}: ${got || "未定義"} → ${val}`);
    }
    if (diff.length) {
      add("X2", "error", `base.css のトークンが ${diff.length} 個違う。base.css を書き換えずに埋め込む（${diff.slice(0, 3).join("、")}${diff.length > 3 ? " ほか" : ""}）`, null);
    }
  }

  // ---------- T1: 文字サイズ ----------
  const SIZES = MODE === "print" ? CFG.printSizes : CFG.screenSizes.concat(CFG.screenExtra);
  const badSize = new Map();
  for (const el of htmlText) {
    const fs = px(getComputedStyle(el).fontSize);
    if (!SIZES.some(s => Math.abs(s - fs) < 0.15)) {
      const k = fs.toFixed(2).replace(/\.?0+$/, "");
      if (!badSize.has(k)) badSize.set(k, { el, n: 0 });
      badSize.get(k).n++;
    }
  }
  for (const [k, v] of badSize) {
    add("T1", "error", `文字サイズ ${k}px は規定外（${v.n}か所）。使えるのは ${SIZES.map(s => +s.toFixed(2)).join(" / ")}px`, v.el);
  }

  // ---------- C1: コントラスト ----------
  const lowC = new Map();
  for (const el of htmlText) {
    const cs = getComputedStyle(el);
    let fg = parseColor(cs.color);
    if (!fg) continue;
    const bg = bgOf(el);
    if (fg[3] < 1) fg = blend(fg, bg);
    const fs = px(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = (fs >= 24 || (bold && fs >= 18.66)) ? 3 : 4.5;
    const r = ratio(fg, bg);
    if (r < need) {
      const k = hex(fg) + " on " + hex(bg);
      if (!lowC.has(k)) lowC.set(k, { el, r, need, n: 0 });
      lowC.get(k).n++;
    }
  }
  for (const [k, v] of lowC) {
    add("C1", "error", `コントラスト比 ${v.r.toFixed(2)}（必要 ${v.need}）: ${k}（${v.n}か所）`, v.el);
  }

  // ---------- C2: パレット外の色 ----------
  const offPal = new Map();
  function checkColor(c, el, what) {
    if (!c || c[3] === 0) return;
    const h = hex(c);
    if (!PALETTE.has(h) || c[3] < 1) {
      const k = h + (c[3] < 1 ? ` α${c[3]}` : "") + `（${what}）`;
      if (!offPal.has(k)) offPal.set(k, el);
    }
  }
  for (const el of vis) {
    const cs = getComputedStyle(el);
    if (inSvg(el)) {
      if (el.tagName === "svg") continue;
      if (cs.fill && cs.fill !== "none") checkColor(parseColor(cs.fill), el, "fill");
      if (cs.stroke && cs.stroke !== "none") checkColor(parseColor(cs.stroke), el, "stroke");
      continue;
    }
    if (ownText(el)) checkColor(parseColor(cs.color), el, "文字");
    checkColor(parseColor(cs.backgroundColor), el, "背景");
    for (const side of ["Top", "Right", "Bottom", "Left"]) {
      if (px(cs["border" + side + "Width"]) > 0 && cs["border" + side + "Style"] !== "none") {
        checkColor(parseColor(cs["border" + side + "Color"]), el, "罫線");
      }
    }
    if (px(cs.outlineWidth) > 0 && cs.outlineStyle !== "none") checkColor(parseColor(cs.outlineColor), el, "outline");
  }
  for (const [k, el] of offPal) add("C2", "error", `パレット外の色 ${k}`, el);

  // ---------- C3 / C4: 強調色 ----------
  function usesAccent(el) {
    const cs = getComputedStyle(el);
    const hits = [];
    if (inSvg(el)) {
      for (const p of ["fill", "stroke"]) {
        const c = parseColor(cs[p]);
        if (c && c[3] > 0 && ACCENT.has(hex(c))) hits.push(p);
      }
      return hits.length > 0;
    }
    const c = parseColor(cs.color);
    if (ownText(el) && c && ACCENT.has(hex(c))) return true;
    const b = parseColor(cs.backgroundColor);
    if (b && b[3] > 0 && ACCENT.has(hex(b))) return true;
    for (const side of ["Top", "Right", "Bottom", "Left"]) {
      if (px(cs["border" + side + "Width"]) > 0 && cs["border" + side + "Style"] !== "none") {
        const bc = parseColor(cs["border" + side + "Color"]);
        if (bc && ACCENT.has(hex(bc))) return true;
      }
    }
    return false;
  }
  // 1ブロック = 冒頭・結論・各セクション・奥付。入れ子のときは外側だけを数える
  const cand = Array.from(document.querySelectorAll("header, section, footer, .conclusion, .masthead, .sec")).filter(visible);
  const blocks = cand.filter(el => !cand.some(o => o !== el && o.contains(el)));
  const GROUP = "svg, .bars, .dots, table, .log, .findings, .stats";
  for (const block of blocks) {
    const groups = new Set();
    let first = null;
    for (const el of [block].concat(Array.from(block.querySelectorAll("*")))) {
      if (!visible(el) || !usesAccent(el)) continue;
      const g = el.closest(GROUP);
      const key = g && block.contains(g) ? g : el;
      if (Array.from(groups).some(k => k !== key && k.contains && k.contains(key))) continue;
      groups.add(key);
      if (!first) first = el;
    }
    if (groups.size > 1) {
      add("C3", "error", `強調色が1ブロックに ${groups.size} か所ある（上限 1）。主役の1つ以外は --ink か --mark にする`, first);
    }
  }
  for (const el of vis) {
    if (inSvg(el) || !ownText(el)) continue;
    const cs = getComputedStyle(el);
    const inData = el.closest("tbody, figure, .bars, .dots, .log");
    const isHead = el.closest("h1, h2, h3, h4, .kicker, .label, caption, thead")
      || (!inData && px(cs.fontSize) <= 14)
      || px(cs.letterSpacing) >= 0.05 * px(cs.fontSize);
    if (!isHead) continue;
    const c = parseColor(getComputedStyle(el).color);
    if (c && ACCENT.has(hex(c))) add("C4", "error", "見出し・小ラベル・番号に強調色を使っている", el);
  }

  // ---------- S1: 禁止装飾 ----------
  for (const el of vis) {
    if (inSvg(el) && el.tagName !== "svg") continue;
    const cs = getComputedStyle(el);
    if (cs.boxShadow !== "none") add("S1", "error", "box-shadow を使っている", el);
    if (cs.textShadow !== "none") add("S1", "error", "text-shadow を使っている", el);
    if (cs.backdropFilter && cs.backdropFilter !== "none") add("S1", "error", "backdrop-filter を使っている", el);
    if (cs.filter !== "none") add("S1", "error", "filter を使っている", el);
    if (/gradient\(/.test(cs.backgroundImage)) add("S1", "error", "グラデーションを使っている", el);
    const r = el.getBoundingClientRect();
    for (const k of ["borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius"]) {
      const v = cs[k];
      if (/%/.test(v)) {
        if (r.width > 16 || r.height > 16) { add("S1", "error", `角丸 ${v} は 16px を超える要素に使えない`, el); break; }
      } else if (px(v) > 8) { add("S1", "error", `角丸 ${v} は上限 8px を超える`, el); break; }
    }
    const t = cs.transform;
    if (t && t !== "none" && ownText(el)) {
      const m = t.match(/matrix\(([^)]+)\)/);
      if (m) {
        const v = m[1].split(",").map(Number);
        if (Math.abs(Math.hypot(v[0], v[1]) - 1) > 0.01) add("S1", "error", "transform で文字を拡大縮小している", el);
      }
    }
  }

  // ---------- S2 / S3: 面とカード ----------
  const PAPER = CFG.paper.toUpperCase();
  const CHART = ".bars, .dots, svg, table, pre";
  // 面 = 縦横とも 40px 以上で、紙と違う背景色を持つ要素。グラフの棒や点は面に数えない
  function filled(el) {
    const c = parseColor(getComputedStyle(el).backgroundColor);
    if (!c || c[3] === 0 || hex(c) === PAPER) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 40 && r.height >= 40;
  }
  function boxed(el) {
    const cs = getComputedStyle(el);
    if (filled(el)) return true;
    return ["Top", "Right", "Bottom", "Left"].every(s => px(cs["border" + s + "Width"]) > 0 && cs["border" + s + "Style"] !== "none");
  }
  for (const el of vis) {
    if (inSvg(el) || el.closest(".bars, .dots") || !filled(el)) continue;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (filled(p)) { add("S2", "error", "色のついた面の中に、さらに色のついた面を入れている", el); break; }
    }
  }
  for (const el of vis) {
    if (inSvg(el) || el.closest(CHART)) continue;
    const kids = Array.from(el.children).filter(visible);
    if (kids.filter(boxed).length >= 3) add("S3", "error", "箱で囲んだ要素を3つ以上並べている。罫線の一覧・表・帯にする", el);
  }

  // ---------- L1: はみ出しと横スクロール ----------
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) {
    add("L1", "error", `ページが横にはみ出している（幅 ${document.documentElement.scrollWidth}px、画面 ${vw}px）`, null);
  }
  const flagged = new Set();
  for (const el of vis) {
    if (inSvg(el) && el.tagName !== "svg") continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) {
      if (el.parentElement && flagged.has(el.parentElement)) { flagged.add(el); continue; }
      flagged.add(el);
      add("L1", "error", `画面の外へはみ出している（右端 ${Math.round(r.right)}px）`, el);
      continue;
    }
    const cs = getComputedStyle(el);
    if (["auto", "scroll", "hidden", "clip"].includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 1 && el.tagName !== "BODY" && el.tagName !== "HTML") {
      add("L1", "error", cs.overflowX === "hidden" || cs.overflowX === "clip" ? "中身が横に切れている" : "横スクロールが発生している", el);
    }
  }

  // ---------- L2: 表 ----------
  for (const t of document.querySelectorAll("table")) {
    if (!visible(t)) continue;
    let cols = 0;
    for (const tr of t.rows) cols = Math.max(cols, Array.from(tr.cells).reduce((s, c) => s + (c.colSpan || 1), 0));
    if (cols > 8) add("L2", "error", `表が ${cols} 列ある（上限 8）。意味のまとまりで2つの表に分ける`, t);
    else if (cols >= 7 && !t.querySelector("col[style*=width], col[class]")) add("L2", "warn", `表が ${cols} 列ある。<col> で列幅を決める`, t);
    if (!t.querySelector("th")) add("L2", "error", "表に見出しセル <th> がない", t);
  }

  // ---------- L3: 比率 ----------
  if (MODE === "desktop") {
    const RATIOS = [1, 1.618, 2];
    for (const el of vis) {
      if (inSvg(el) || el.closest("figure, .bars, .dots, .log, .stats, table, .meta")) continue;
      const cs = getComputedStyle(el);
      if (cs.display !== "grid" && cs.display !== "inline-grid") continue;
      const tracks = cs.gridTemplateColumns.split(/\s+/).map(px).filter(v => v > 0);
      // 見出し列のような細い列を持つ行の組み方は対象外。版面を割る大きな列だけを見る
      if (tracks.some(t => t < 200)) continue;
      if (tracks.length === 2) {
        const r = Math.max(...tracks) / Math.min(...tracks);
        if (!RATIOS.some(x => Math.abs(r / x - 1) < 0.04)) {
          add("L3", "error", `2列の比率 ${r.toFixed(2)}:1 は規定外。1:1・1.618:1・2:1 から選ぶ`, el);
        }
      } else if (tracks.length >= 3) {
        const mx = Math.max(...tracks), mn = Math.min(...tracks);
        if (mx / mn > 1.03) add("L3", "error", "3列以上を不均等に割っている。等分にする", el);
      }
    }
  }

  // ---------- T2 / T3 / T4: 行長・見出しの行数・文字サイズの数 ----------
  if (MODE === "desktop") {
    for (const el of vis) {
      if (!["P", "LI"].includes(el.tagName) || el.closest("table, figure, .side, .bars, .dots, .log, .stats, .meta, .findings, .colophon, .split")) continue;
      const cs = getComputedStyle(el);
      if (/grid|flex/.test(cs.display)) continue;
      const fs = px(cs.fontSize);
      const w = el.clientWidth - px(cs.paddingLeft) - px(cs.paddingRight);
      const limit = fs >= 24 ? 35 : 43;
      if (w / fs > limit) add("T2", "error", `1行が約 ${Math.round(w / fs)} 字ある（上限 ${limit - 1} 字）`, el);
    }
  }
  if (MODE !== "print") {
    for (const h of document.querySelectorAll("h1, h2, h3")) {
      if (!visible(h)) continue;
      const cs = getComputedStyle(h);
      const lines = Math.round(h.getBoundingClientRect().height / px(cs.lineHeight));
      if (lines > 2) add("T3", MODE === "mobile" && h.tagName === "H1" ? "warn" : "error", `${h.tagName} が ${lines} 行になっている（上限 2 行）。文を短くする`, h);
    }
  }
  // 1ブロックで使う文字サイズは5段階まで
  for (const block of blocks) {
    const set = new Set(htmlText.filter(el => block.contains(el)).map(el => Math.round(px(getComputedStyle(el).fontSize) * 100) / 100));
    if (set.size > 5) add("T4", "error", `1ブロックに文字サイズが ${set.size} 種類ある（${Array.from(set).sort((x, y) => x - y).join("/")}px）。上限 5`, block);
  }

  // ---------- F1 / F2 / F3 / F4: 図 ----------
  const minSvgText = MODE === "print" ? 12 : 14;
  for (const svg of document.querySelectorAll("svg")) {
    if (!visible(svg) || svg.ownerSVGElement) continue;
    const sr = svg.getBoundingClientRect();
    const decorative = svg.getAttribute("aria-hidden") === "true";
    if (!decorative && sr.width > 40) {
      const named = svg.getAttribute("role") === "img" && (svg.getAttribute("aria-label") || svg.querySelector(":scope > title"));
      if (!named) add("F3", "error", 'SVG に role="img" と aria-label（または <title>）がない', svg);
    }
    const texts = Array.from(svg.querySelectorAll("text")).filter(visible);
    let small = null;
    for (const t of texts) {
      const m = t.getScreenCTM();
      const scale = m ? Math.hypot(m.a, m.b) : 1;
      const size = px(getComputedStyle(t).fontSize) * scale;
      if (size < minSvgText - 0.05 && (!small || size < small.size)) small = { t, size };
      const r = t.getBoundingClientRect();
      if (r.left < sr.left - 1 || r.right > sr.right + 1 || r.top < sr.top - 1 || r.bottom > sr.bottom + 1) {
        add("F2", "error", "図の文字が SVG の外にはみ出している", t);
      }
    }
    if (small) add("F1", "error", `図の文字が表示上 ${small.size.toFixed(1)}px になる（下限 ${minSvgText}px）。viewBox を狭めるか、幅の狭い画面用の版を用意する`, small.t);
    for (let i = 0; i < texts.length; i++) {
      const a = texts[i].getBoundingClientRect();
      for (let j = i + 1; j < texts.length; j++) {
        const b = texts[j].getBoundingClientRect();
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 1 && oy > 2) add("F2", "error", `図の文字どうしが重なっている（「${texts[j].textContent.trim().slice(0, 12)}」と）`, texts[i]);
      }
      for (const ar of svg.querySelectorAll(".arrow")) {
        const b = ar.getBoundingClientRect();
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 0 && oy > 0) add("F2", "error", "図の文字と矢印の先が重なっている", texts[i]);
      }
    }
  }
  for (const f of document.querySelectorAll("figure")) {
    if (visible(f) && !f.querySelector("figcaption")) add("F3", "warn", "figure に figcaption がない", f);
  }
  for (const li of document.querySelectorAll(".bars > li, .dots > li:not(.scale)")) {
    if (!visible(li)) continue;
    const v = li.querySelector(".val");
    if (!v || !v.textContent.trim()) add("F4", "error", "グラフの項目に数値（.val）が書かれていない", li);
  }
  for (const d of document.querySelectorAll(".dots")) {
    if (visible(d) && !d.querySelector(":scope > li.scale")) add("F4", "error", "点グラフに目盛りの行（li.scale）がない", d);
  }

  // ---------- W: 言葉 ----------
  const VAGUE = CFG.vagueHeadings;
  const BANNED = CFG.bannedTitle.map(s => new RegExp(s, "i"));
  for (const h of document.querySelectorAll("h1, h2, h3, .kicker")) {
    if (!visible(h)) continue;
    const t = h.textContent.replace(/\s+/g, " ").trim();
    const bare = t.replace(/^[0-9０-９.\s]+/, "");
    if (h.tagName !== "DIV" && h.tagName !== "SPAN" && !h.classList.contains("kicker") && VAGUE.includes(bare)) {
      add("W1", "error", `見出し「${bare}」は中身を表していない。何について何を言う節かを書く`, h);
    }
    for (const re of BANNED) if (re.test(t)) add("W1", "error", `見出しに定型句「${t.match(re)[0]}」がある`, h);
    if (/^[0-9０-９]{1,2}(\s|\.|$)/.test(t) || h.querySelector(".num, .no")) {
      add("W4", "warn", "見出しに番号を付けている。本文から番号で参照しないなら外す", h);
    }
  }
  const ENG = new RegExp("^(" + CFG.englishLabels.join("|") + ")$", "i");
  for (const el of document.querySelectorAll(".kicker, .label")) {
    if (visible(el) && ENG.test(el.textContent.trim())) add("W5", "error", `英語の飾りラベル「${el.textContent.trim()}」を使っている`, el);
  }
  const bodyText = document.body.innerText;
  for (const s of CFG.production) {
    const m = bodyText.match(new RegExp(s));
    if (m) add("W2", "error", `制作の経緯が本文に残っている:「${m[0]}」`, null);
  }
  const abs = document.querySelector(".abstract");
  if (abs) {
    const n = (abs.textContent.match(/[。．.!?！？](?=\s|$|[^0-9])/g) || []).length;
    if (n > 2) add("W3", "error", `要旨が ${n} 文ある（上限 2 文）`, abs);
    for (const s of CFG.abstractBanned) if (abs.textContent.includes(s)) add("W3", "error", `要旨に定型句「${s}」がある`, abs);
  } else if (MODE === "desktop") {
    add("W3", "warn", "要旨（.abstract）がない", null);
  }

  // ---------- X1: 外部依存 ----------
  for (const s of document.querySelectorAll("script")) {
    if (SKIP_ID.test(s.id || "")) continue;
    if (s.src) add("X1", "error", `外部スクリプトを読み込んでいる: ${s.src}`, s);
    else if (MODE === "desktop") add("X1", "warn", "スクリプトがある。スクリプトなしで読めるか確かめる", s);
  }
  for (const l of document.querySelectorAll('link[rel~="stylesheet"]')) {
    if (/^https?:/i.test(l.href) && !/^file:/i.test(l.href)) add("X1", "error", `外部 CSS を読み込んでいる: ${l.href}`, l);
    else if (MODE === "desktop") add("X1", "warn", "CSS を別ファイルで読み込んでいる。提出版は <style> に埋め込む", l);
  }
  for (const img of document.querySelectorAll("img")) {
    if (/^https?:/i.test(img.getAttribute("src") || "")) add("X1", "warn", "画像をネットから読み込んでいる", img);
    if (!img.hasAttribute("alt")) add("F3", "error", "img に alt がない", img);
  }

  // Windows では Chrome の標準出力が ANSI コードページになるため、非 ASCII を \u でエスケープする
  const json = JSON.stringify({
    mode: MODE,
    width: vw,
    height: document.documentElement.scrollHeight,
    issues,
  }).replace(/[\u007f-￿]/g, c => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  // 幅の狭い画面の検査は iframe の中で動くので、結果を親へ渡す
  if (window.parent !== window) {
    window.parent.postMessage(json, "*");
  } else {
    const out = document.createElement("pre");
    out.id = "__rdlint_out";
    out.textContent = json;
    document.body.appendChild(out);
  }
})();
