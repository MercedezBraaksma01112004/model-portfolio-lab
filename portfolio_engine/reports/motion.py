"""Shared motion for every page: sections and tiles rise into view once as you scroll, allocation bars wipe in,
chart lines draw themselves, and headline numbers count up the first time they are seen (and glide to their new value
when a choice changes them). Everything is skipped for visitors who ask their system for reduced motion, and for print.
"""

CSS = """
/* motion: one reveal per element, never repeated */
.rv { opacity:0; transform:translateY(16px); transition:opacity .65s ease var(--d,0ms), transform .65s cubic-bezier(.2,.7,.2,1) var(--d,0ms); }
.rv.in { opacity:1; transform:none; }
.stack.rv, .dstack.rv { opacity:1; transform:none; clip-path:inset(0 100% 0 0); transition:clip-path 1.1s cubic-bezier(.3,.7,.2,1) var(--d,0ms); }
.stack.rv.in, .dstack.rv.in { clip-path:inset(0 0 0 0); }
.btn { transition:background .15s, border-color .15s, transform .1s; } .btn:active { transform:translateY(1px); }
.card2 { transition:transform .2s ease, box-shadow .2s ease; } .card2:hover { transform:translateY(-2px); box-shadow:0 8px 24px rgba(30,34,40,.07); }
.seg button { transition:background .15s, border-color .15s, box-shadow .15s; }
@media (prefers-reduced-motion: reduce) { .rv, .stack.rv, .dstack.rv { opacity:1 !important; transform:none !important; clip-path:none !important; transition:none !important; } .card2:hover { transform:none; } }
@media print { .rv, .stack.rv, .dstack.rv { opacity:1 !important; transform:none !important; clip-path:none !important; } }
"""

JS = r"""
(function () {
  if (!("IntersectionObserver" in window)) return;
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const FIRST = "main > section, main > div > section, .wrap > h2, .wrap > .essay, .wrap > .card, .stack, .dstack, .btchart, #p-chart, .tiles > .tile, .numtiles > .tile, .summary > .tile, .groups > div";
  const LATER = ".card2, .cmpgrid, .sheet, #ai-box > div, #ai > div";
  const COUNT = ".tile .v, #readout b";
  const NUM = /\d[\d,]*(?:\.\d+)?/g;
  const seen = new WeakSet(), last = new Map(), running = new Map();

  // reveal
  // a fully clipped element never reports itself as visible, so the bars are watched through their parent
  const proxy = new Map();
  const rio = new IntersectionObserver(es => es.forEach(e => { if (!e.isIntersecting) return; const t = e.target, els = proxy.has(t) ? proxy.get(t).concat(t.classList.contains("rv") ? [t] : []) : [t]; proxy.delete(t); rio.unobserve(t);
    els.forEach(el => { el.classList.add("in"); if (el.matches(".btchart, #p-chart")) draw(el); }); }), { rootMargin: "0px 0px -6% 0px", threshold: 0.01 });
  function reveal(el, i) { if (reduce || el.classList.contains("rv") || el.hidden) return; el.classList.add("rv"); if (i) el.style.setProperty("--d", Math.min(i, 8) * 55 + "ms");
    if (el.matches(".stack, .dstack") && el.parentElement) { const w = el.parentElement; if (!proxy.has(w)) proxy.set(w, []); proxy.get(w).push(el); rio.observe(w); } else rio.observe(el); }
  function scan(root, sel) { root.querySelectorAll(sel).forEach(el => { const sibs = el.parentElement ? [...el.parentElement.children] : []; reveal(el, el.matches(".tile, .card2, .groups > div") ? sibs.indexOf(el) : 0); }); }

  // chart lines draw themselves
  function draw(box) { if (reduce) return; box.querySelectorAll("svg path, svg polyline").forEach(p => {
    const cs = getComputedStyle(p); if (cs.fill !== "none" && p.getAttribute("fill") !== "none") return; let len = 0; try { len = p.getTotalLength(); } catch (e) { return; } if (!len) return;
    p.style.strokeDasharray = len; p.style.strokeDashoffset = len; p.getBoundingClientRect(); p.style.transition = "stroke-dashoffset 1.4s cubic-bezier(.3,.6,.2,1)"; p.style.strokeDashoffset = 0;
    setTimeout(() => { p.style.strokeDasharray = ""; p.style.strokeDashoffset = ""; p.style.transition = ""; }, 1500); }); }

  // numbers: count up when first seen, glide when they change
  const fmt = (v, tok) => { const dec = (tok.split(".")[1] || "").length; let s = Math.abs(v).toFixed(dec); if (tok.includes(",")) { const [a, b] = s.split("."); s = a.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (b ? "." + b : ""); } return s; };
  const skel = t => t.replace(NUM, "#");
  const toNum = t => parseFloat(t.replace(/,/g, ""));
  function textNodes(el) { const out = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) out.push(n); return out; }
  function keyOf(el) { const box = el.closest("[id]"); const lab = el.parentElement && el.parentElement.querySelector(".k"); return (box ? box.id : "") + "|" + (lab ? lab.textContent : [...(box || document).querySelectorAll(COUNT)].indexOf(el)); }
  function tween(el, fromTexts, targets) {
    const nodes = textNodes(el); targets = targets || nodes.map(n => n.data); if (!targets.some(t => /\d/.test(t))) return;
    const plan = nodes.map((n, i) => { const to = targets[i] == null ? n.data : targets[i], from = fromTexts ? fromTexts[i] : null; const toks = to.match(NUM) || [];
      const starts = from != null && skel(from) === skel(to) ? (from.match(NUM) || []).map(toNum) : (fromTexts ? null : toks.map(() => 0)); return { n, to, toks, starts }; });
    if (plan.every(p => !p.starts || !p.toks.length)) { plan.forEach(p => p.n.data = p.to); return; }
    const k = keyOf(el); if (running.has(k)) cancelAnimationFrame(running.get(k));
    const t0 = performance.now(), dur = fromTexts ? 600 : 1100;
    const step = now => { const x = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - x, 3);
      plan.forEach(p => { if (!p.starts || !p.toks.length) { p.n.data = p.to; return; } let i = 0; p.n.data = p.to.replace(NUM, tok => { const a = p.starts[i] || 0, b = toNum(tok); i++; return fmt(a + (b - a) * e, tok); }); });
      if (x < 1) running.set(k, requestAnimationFrame(step)); else { plan.forEach(p => p.n.data = p.to); running.delete(k); } };
    running.set(k, requestAnimationFrame(step));
  }
  const pending = new Map();   // element -> its real text, while it waits (shown as zero) to scroll into view
  const cio = new IntersectionObserver(es => es.forEach(e => { if (!e.isIntersecting) return; const el = e.target; cio.unobserve(el); const t = pending.get(el); pending.delete(el); tween(el, null, t); }), { threshold: 0.35 });
  function watchNumbers(root) { root.querySelectorAll(COUNT).forEach(el => { if (seen.has(el)) return; seen.add(el); const k = keyOf(el), nodes = textNodes(el), texts = nodes.map(n => n.data);
    const prev = last.get(k); last.set(k, texts);
    if (reduce || !texts.some(t => /\d/.test(t))) return;
    if (prev) { if (prev.join("") !== texts.join("")) tween(el, prev); return; }
    if (el.offsetParent !== null) { pending.set(el, texts); nodes.forEach(n => { n.data = n.data.replace(NUM, tok => fmt(0, tok)); }); }
    cio.observe(el); }); }
  const settle = () => { pending.forEach((t, el) => textNodes(el).forEach((n, i) => { if (t[i] != null) n.data = t[i]; })); pending.clear(); };
  window.addEventListener("beforeprint", settle);
  scan(document, FIRST); watchNumbers(document);
  new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) { if (n.nodeType !== 1) continue;
      if (n.matches && n.matches(LATER)) reveal(n, n.parentElement ? [...n.parentElement.children].indexOf(n) : 0); if (n.querySelectorAll) { scan(n, LATER); watchNumbers(n.parentElement || n); } } })
    .observe(document.body, { childList: true, subtree: true });
})();
"""


def inject(page: str) -> str:
    """Add the motion script just before </body> (CSS travels with the shared stylesheet)."""
    return page.replace("</body>", f"<script>{JS}</script>\n</body>", 1)
