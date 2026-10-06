import { getStore } from "@netlify/blobs";
import { json } from "./_yahoo.mjs";
// Listings the live price feeds could not supply, waiting for the cloud build to fetch them.
//   GET  -> { pending: [{ symbol, name, at }], done: [...] }
//   POST { symbol, name? } -> queue it (no PIN: it only asks the build to fetch public price data)
// The build (scripts/sync_changes.py) adds pending symbols to config/extra_listings.csv, publishes their data under
// /data/listings/, and this function clears every symbol that now has a listing file.
const KEY = "fetch-queue";
const MAX_PENDING = 100;
export default async (req) => {
  const store = getStore({ name: "portfolio-engine", consistency: "strong" });
  const state = (await store.get(KEY, { type: "json" })) || { pending: [], done: [] };
  try {
    const base = new URL(req.url).origin;
    if (state.pending.length) {
      const r = await fetch(`${base}/data/listings/index.json`, { headers: { "Cache-Control": "no-cache" } });
      if (r.ok) { const have = new Set(((await r.json()).symbols) || []);
        const moved = state.pending.filter(p => have.has(p.symbol));
        if (moved.length) { state.pending = state.pending.filter(p => !have.has(p.symbol));
          state.done = [...moved.map(p => ({ ...p, done_at: new Date().toISOString() })), ...state.done].slice(0, 200); await store.setJSON(KEY, state); } }
    }
  } catch { /* served as is; reconciled on the next call */ }
  if (req.method === "GET") return json(state);
  if (req.method !== "POST") return json({ error: "method" }, 405);
  let body; try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
  const symbol = String(body.symbol || "").trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.\-]{0,14}$/.test(symbol)) return json({ error: "a listing code such as ASML.AS or 7203.T is required" }, 400);
  if (!state.pending.some(p => p.symbol === symbol)) {
    if (state.pending.length >= MAX_PENDING) return json({ error: "the queue is full; try again after the next update" }, 429);
    state.pending.push({ symbol, name: String(body.name || "").slice(0, 120), at: new Date().toISOString() });
    await store.setJSON(KEY, state);
  }
  return json(state);
};
