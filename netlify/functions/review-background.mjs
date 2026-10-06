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
- Compare like with like. Each holding's "exposure" says what part of the market it gives (asset class, segment such as
  small companies, income, infrastructure, long/short, a sector or theme, and region) and "management" says whether it is
  active, index or a direct holding. Only suggest replacing a holding with one that gives the same exposure. Never
  suggest replacing an active small companies, income, long/short, activist, thematic, sector, infrastructure or credit
  fund with a broad market index fund (A200, VAS, IOZ, STW, VGS, IVV, VEU and the like) on fees: that changes what the
  portfolio owns, not just what it costs. Do not recommend exiting active managers as a group; judge each on whether its
  fee is reasonable for what it does, and if you name a cheaper equivalent, say what would be given up.
- "role_in_model" and "advisers_reason" are the adviser's own reasons for a holding. Respect them: question one only when
  the data contradict it, and say which data.
- Be relevant. Suggest only changes that materially move risk, allocation against the target, cost, income or liquidity
  for this portfolio, at most six, most important first. A deliberate tilt recorded in the adviser's reasons is not an
  error to correct.
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

// Basis of advice drafts in the adviser's house style ({ mode: "boa" } payloads from the builder).
const BOA_SYSTEM = `You write the basis of advice for each investment recommended in an Australian financial adviser's Statement of
Advice: the passage that explains why the investment is recommended. You receive the portfolio, one record per holding (its
facts, its role in the model, and a facts-only draft the tool wrote), and, when the adviser has supplied them, examples of
basis of advice passages from their own Statements of Advice.

Write one passage per holding.
- When examples are supplied, match them closely: the same structure and headings, order, sentence length, tone,
  level of detail, use of first person ("we recommend") and phrasing conventions. They show the house style; do not copy
  their facts, which belong to other investments and other clients.
- When no examples are supplied, use three short parts headed "Why we recommend it", "Advantages" and "Other things to
  consider", in plain sentences.
- Use only the facts provided for that holding. Never cite past returns, performance, price targets, forecasts or
  expected returns: past performance is not a reason to recommend an investment. Do not invent fees, yields or features.
- Do not invent anything about the client. Where the passage needs a client-specific reason (their objectives, risk
  profile, timeframe, tax position, existing investments), write a short placeholder in square brackets, for example
  [client's objective of a reliable retirement income].
- Explain the role the holding plays in the portfolio, using role_in_model where it is given, and give the main risks
  plainly. For active funds say what the manager is paid to do; for hybrids, notes and subordinated debt say where they
  rank and that they can fall in value in a crisis; for single companies say why a small weight.
- Australian spelling, plain English, no em dashes. About 90 to 160 words per holding unless the examples are longer or
  shorter.
Return only JSON in this shape: {"drafts": [{"code": "the holding's code exactly as given", "text": "the passage"}]}`;

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
    // The key may be in ANTHROPIC_API_KEY or in the ModelPortfolio variable; use the first that looks like an Anthropic key.
    // Surrounding spaces, line breaks and quotation marks from pasting are ignored.
    const read = name => String((globalThis.Netlify && Netlify.env.get(name)) || process.env[name] || "").trim().replace(/^["'\s]+|["'\s]+$/g, "");
    const names = ["ANTHROPIC_API_KEY", "ModelPortfolio", "MODEL_PORTFOLIO_KEY"];
    const apiKey = names.map(read).find(v => v.startsWith("sk-ant-")) || names.map(read).find(Boolean) || "";
    if (!apiKey) return fail("The AI review is not set up: the site has no ANTHROPIC_API_KEY.");
    if (!apiKey.startsWith("sk-ant-")) return fail("The ANTHROPIC_API_KEY on the site does not look like an Anthropic API key (they start with sk-ant-). Replace it in Netlify's environment variables.");
    const boa = (body.payload || {}).mode === "boa";
    const payload = JSON.stringify(body.payload || {});
    if (payload.length > 160000) return fail(boa ? "Too many holdings to draft in one go; draft them in two halves." : "The portfolio is too large to review in one go.");
    await store.setJSON(job, { status: "running", at: new Date().toISOString() });
    // One call to Claude: the parsed JSON result (or the raw text), the model and the usage, or an error message.
    const call = async (system, content, maxTokens) => {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: JSON.stringify({ model: MODEL, max_tokens: maxTokens, system, messages: [{ role: "user", content }] }),
      });
      const out = await r.json().catch(() => ({}));
      if (r.status === 401) return { error: "Anthropic rejected the site's API key (401). Create a new key in the Anthropic Console, paste it into ANTHROPIC_API_KEY in Netlify, and redeploy the site." };
      if (!r.ok) return { error: `The AI service returned ${r.status}${out.error && out.error.message ? ": " + out.error.message : ""}` };
      const text = (out.content || []).filter(c => c.type === "text").map(c => c.text).join("\n").trim();
      let result = null;
      try { result = JSON.parse(text.replace(/^```(?:json)?\s*|\s*```$/g, "")); } catch { const m = text.match(/\{[\s\S]*\}/); if (m) { try { result = JSON.parse(m[0]); } catch { /* fall through */ } } }
      return { result, text, model: out.model || MODEL, usage: out.usage || null };
    };
    if (boa) {
      // Ten holdings per call, so no single request runs long; progress is written as each batch finishes.
      const all = (body.payload.holdings || []); const drafts = []; let model = MODEL, lastError = "";
      for (let i = 0; i < all.length; i += 10) {
        const part = { ...body.payload, holdings: all.slice(i, i + 10) };
        const got = await call(BOA_SYSTEM, `Write the basis of advice for each holding below. Data as JSON:\n${JSON.stringify(part)}`, 8000);
        if (got.error) { lastError = got.error; if (!drafts.length && got.error.includes("401")) return fail(got.error); continue; }
        model = got.model; drafts.push(...((got.result && got.result.drafts) || []));
        await store.setJSON(job, { status: "running", at: new Date().toISOString(), done: Math.min(i + 10, all.length), of: all.length });
      }
      if (!drafts.length) return fail(lastError || "The AI did not return any drafts.");
      await store.setJSON(job, { status: "done", at: new Date().toISOString(), model, result: { drafts }, text: "", partial: drafts.length < all.length ? lastError || "some holdings were not drafted" : "",
                                 remaining_today: DAILY_LIMIT - used - 1 });
      return;
    }
    const got = await call(SYSTEM, `Review this portfolio. Data as JSON:\n${payload}`, 3000);
    if (got.error) return fail(got.error);
    await store.setJSON(job, { status: "done", at: new Date().toISOString(), model: got.model, result: got.result, text: got.result ? "" : got.text,
                               usage: got.usage, remaining_today: DAILY_LIMIT - used - 1 });
  } catch (e) {
    await fail(`The review failed: ${String(e.message || e).slice(0, 200)}`);
  }
};
