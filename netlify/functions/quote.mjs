import { yfetch, json } from "./_yahoo.mjs";
// GET /.netlify/functions/quote?symbol=BHP.AX -> price, currency, 1y return, name
export default async (req) => {
  const s = new URL(req.url).searchParams.get("symbol")?.trim().toUpperCase();
  if (!s) return json({ error: "symbol required" }, 400);
  try {
    const d = await yfetch(`https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(s)}?range=1y&interval=1d&events=div`);
    const r = d.chart?.result?.[0];
    if (!r) return json({ error: "no data" }, 404);
    const meta = r.meta || {};
    const closes = (r.indicators?.adjclose?.[0]?.adjclose || r.indicators?.quote?.[0]?.close || []).filter(v => v != null);
    const first = closes[0], last = closes[closes.length - 1];
    const divs = Object.values(r.events?.dividends || {}).reduce((t, x) => t + (x.amount || 0), 0);
    return json({ symbol: s, name: meta.longName || meta.shortName || s, currency: meta.currency, price: meta.regularMarketPrice ?? last,
      return_1y_pct: first && last ? +((last / first - 1) * 100).toFixed(2) : null,
      yield_pct: last && divs ? +((divs / last) * 100).toFixed(2) : 0, exchange: meta.exchangeName, type: meta.instrumentType,
      spark: closes.filter((_, i) => i % Math.max(1, Math.floor(closes.length / 60)) === 0).map(v => +(v / first * 100).toFixed(2)) });
  } catch (e) {
    return json({ error: String(e.message || e) }, 502);
  }
};
