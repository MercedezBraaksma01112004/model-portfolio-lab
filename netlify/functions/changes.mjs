import { getStore } from "@netlify/blobs";
import { json } from "./_yahoo.mjs";
// Change queue for the portfolio engine.
//   GET  -> { pending: [...], applied: [...] }
//   POST { pin, action: "add"|"remove", ticker, asset_class?, name?, vehicle?, note? }   -> queue a change
//   POST { pin, action: "applied", ids: [...] }                                           -> mark changes applied (called by the Mac build)
const KEY = "changes";
export default async (req) => {
  const store = getStore({ name: "portfolio-engine", consistency: "strong" });
  const state = (await store.get(KEY, { type: "json" })) || { pending: [], applied: [] };
  if (req.method === "GET") return json(state);
  if (req.method !== "POST") return json({ error: "method" }, 405);
  let body;
  try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
  const pin = process.env.EDIT_PIN || "";
  if (!pin || String(body.pin || "") !== pin) return json({ error: "wrong PIN" }, 403);
  if (body.action === "applied") {
    const ids = new Set(body.ids || []);
    const moved = state.pending.filter(c => ids.has(c.id));
    state.pending = state.pending.filter(c => !ids.has(c.id));
    state.applied = [...moved.map(c => ({ ...c, applied_at: new Date().toISOString() })), ...state.applied].slice(0, 200);
  } else if (body.action === "add" || body.action === "remove") {
    const ticker = String(body.ticker || "").trim().toUpperCase();
    if (!ticker) return json({ error: "ticker required" }, 400);
    if (body.action === "add" && !body.asset_class) return json({ error: "asset_class required" }, 400);
    state.pending = state.pending.filter(c => c.ticker !== ticker);
    state.pending.push({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), action: body.action, ticker,
      asset_class: body.asset_class || "", name: body.name || ticker, vehicle: body.vehicle || "", role: body.role || "satellite",
      min_tier: body.min_tier || "core", weight_hint: body.weight_hint || 3, note: body.note || "", requested_at: new Date().toISOString() });
  } else if (body.action === "cancel") {
    state.pending = state.pending.filter(c => c.id !== body.id);
  } else {
    return json({ error: "unknown action" }, 400);
  }
  await store.setJSON(KEY, state);
  return json(state);
};
