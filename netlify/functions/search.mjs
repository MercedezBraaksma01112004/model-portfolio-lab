import { yfetch, json } from "./_yahoo.mjs";
// GET /.netlify/functions/search?q=bhp  -> matching ASX / US / Cboe listings
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
    return json({ results: [], error: String(e.message || e) }, 502);
  }
};
