import { yfetch, json } from "./_yahoo.mjs";
import { nasdaqSearch } from "./_nasdaq.mjs";
// GET /.netlify/functions/search?q=bhp  -> matching ASX / US / Cboe and other listings.
// Yahoo first; when it refuses the site's servers, Nasdaq's search for United States listings and the ASX for an ASX code.
const ASX = "https://asx.api.markitdigital.com/asx-research/1.0";
const UA = { "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept": "application/json" };
export default async (req) => {
  const q = new URL(req.url).searchParams.get("q")?.trim();
  if (!q) return json({ results: [] });
  try {
    const d = await yfetch(`https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=12&newsCount=0&listsCount=0`);
    // Australian, United States, Canadian, British, European, New Zealand and major Asian listings.
    const ok = new Set(["ASX", "NMS", "NYQ", "NGM", "PCX", "BTS", "NCM", "ASE", "TOR", "LSE", "PAR", "MIL", "GER", "FRA", "AMS", "MCE", "EBS", "NZE", "HKG", "JPX", "SES", "CXA"]);
    const results = (d.quotes || [])
      .filter(x => x.symbol && ["EQUITY", "ETF"].includes(x.quoteType) && (ok.has(x.exchange) || x.symbol.endsWith(".AX") || x.symbol.endsWith(".XA")))
      .map(x => ({ symbol: x.symbol, name: x.longname || x.shortname || x.symbol, exchange: x.exchDisp || x.exchange, type: x.quoteType }));
    return json({ results }, 200, 3600);
  } catch (e) {
    const results = [];
    const code = q.toUpperCase().replace(/\.AX$/, "");
    if (/^[A-Z0-9]{2,6}$/.test(code)) {
      try { const r = await fetch(`${ASX}/companies/${code.toLowerCase()}/header`, { headers: UA }); const h = r.ok ? ((await r.json()).data || {}) : {};
        if (h.displayName) results.push({ symbol: code + ".AX", name: h.displayName, exchange: "ASX", type: "EQUITY" }); } catch { /* not an ASX code */ }
    }
    try { results.push(...(await nasdaqSearch(q)).slice(0, 10)); } catch { /* Nasdaq unavailable */ }
    return json({ results, fallback: true, error: results.length ? undefined : String(e.message || e) }, 200, 600);
  }
};
