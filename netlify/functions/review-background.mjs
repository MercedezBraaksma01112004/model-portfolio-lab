import { getStore } from "@netlify/blobs";
// AI review of a portfolio from the "Build your own portfolio" page, run as a background function because a
// considered review takes longer than a synchronous function may run.
//   POST { job, token, payload }  -> 202 at once; the result is written to the "reviews" store under `job`
//   and read back by review-status.
// Only signed-in visitors (a valid Supabase session token) can run it, and each account has a daily limit, so a
// stranger cannot spend the site's API credit. The API key lives in the ANTHROPIC_API_KEY environment variable.
const SUPABASE_URL = "https://dmeypgcdjtudqreifgoe.supabase.co";
const SUPABASE_KEY = "sb_publishable_Hl5Cn1f6Bk7hIqdFQYefqA_YpCo5gRI";   // the public (publishable) key, as in the page
const MODEL = "claude-sonnet-5-5";
const DAILY_LIMIT = 25;

const SYSTEM = `You review model investment portfolios built in an Australian financial adviser's learning tool.
You receive the portfolio (holdings, weights, asset classes, costs, income, risk measures), the long-run target
allocation it is compared with, the platform and its fees, the findings of the tool's own rule-based check, and a
list of other holdings available in the tool's universe.

Write a review that a paraplanner could act on. For each suggestion say exactly what to change (which holding, from
what weight to what weight, or which holding to swap for which), why it improves the portfolio, and what it costs or
risks. Prioritise: allocation against the target, diversification and concentration, cost (fund fees and platform),
income and franking where relevant, liquidity, and overlap between holdings.

Rules:
- Use only the data provided. Do not invent prices, fees, ratings or holdings. When suggesting an addition, prefer
  holdings from the provided universe list and use their codes.
- Do not justify any change by past returns; past performance is not a reason to recommend a holding.
- The analyst consensus provided is an aggregate of brokers from a free data feed, not licensee research; treat it as
  a prompt for review, not a verdict.
- This is general information for a learning tool, not personal advice. Do not address a client. Note where a
  client's objectives or circumstances would change the answer.
- Australian spelling, plain English, no em dashes.
Return only JSON in this shape:
{"summary": "two or three sentences", "strengths": ["..."],
 "suggestions": [{"priority": "high|medium|low", "title": "short", "change": "the exact change", "why": "the reason", "tradeoff": "cost or risk of making it"}],
 "questions": ["what the adviser should find out about the client before acting"]}`;

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export default async (req) => {
  const store = getStore({ name: "reviews", consistency: "strong" });
  let body;
  try { body = await req.json(); } catch { return; }
  const job = String(body.job || "");
  if (!/^[0-9a-f-]{20,60}$/i.test(job)) return;
  const fail = async (error) => { await store.setJSON(job, { status: "error", error, at: new Date().toISOString() }); };
  try {
    // 1. who is asking
    const u = await fetch(`${SUPABASE_URL}/auth/v1/user`, { headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${body.token || ""}` } });
    if (!u.ok) return fail("Sign in to use the AI review.");
    const user = await u.json();
    // 2. daily limit per account
    const day = new Date().toISOString().slice(0, 10);
    const usage = getStore({ name: "review-usage", consistency: "strong" });
    const key = `${user.id}/${day}`;
    const used = Number(await usage.get(key)) || 0;
    if (used >= DAILY_LIMIT) return fail(`You have used today's ${DAILY_LIMIT} AI reviews. The limit resets at 10 am Brisbane time.`);
    await usage.set(key, String(used + 1));
    // 3. the request itself
    // Tolerate the usual pasting accidents: surrounding spaces, line breaks and quotation marks.
    const apiKey = String((globalThis.Netlify && Netlify.env.get("ANTHROPIC_API_KEY")) || process.env.ANTHROPIC_API_KEY || "").trim().replace(/^["'\s]+|["'\s]+$/g, "");
    if (!apiKey) return fail("The AI review is not set up: the site has no ANTHROPIC_API_KEY.");
    if (!apiKey.startsWith("sk-ant-")) return fail("The ANTHROPIC_API_KEY on the site does not look like an Anthropic API key (they start with sk-ant-). Replace it in Netlify's environment variables.");
    const payload = JSON.stringify(body.payload || {});
    if (payload.length > 120000) return fail("The portfolio is too large to review in one go.");
    await store.setJSON(job, { status: "running", at: new Date().toISOString() });
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({ model: MODEL, max_tokens: 3000, system: SYSTEM,
        messages: [{ role: "user", content: `Review this portfolio. Data as JSON:\n${payload}` }] }),
    });
    const out = await r.json().catch(() => ({}));
    if (r.status === 401) return fail("Anthropic rejected the site's API key (401). Create a new key in the Anthropic Console, paste it into ANTHROPIC_API_KEY in Netlify, and redeploy the site.");
    if (!r.ok) return fail(`The AI service returned ${r.status}${out.error && out.error.message ? ": " + out.error.message : ""}`);
    const text = (out.content || []).filter(c => c.type === "text").map(c => c.text).join("\n").trim();
    let result = null;
    try { result = JSON.parse(text.replace(/^```(?:json)?\s*|\s*```$/g, "")); } catch { const m = text.match(/\{[\s\S]*\}/); if (m) { try { result = JSON.parse(m[0]); } catch { /* fall through */ } } }
    await store.setJSON(job, { status: "done", at: new Date().toISOString(), model: out.model || MODEL, result, text: result ? "" : text,
                               usage: out.usage || null, remaining_today: DAILY_LIMIT - used - 1 });
  } catch (e) {
    await fail(`The review failed: ${String(e.message || e).slice(0, 200)}`);
  }
};
