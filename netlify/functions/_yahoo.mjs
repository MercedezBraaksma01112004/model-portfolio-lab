// Shared helpers for the Yahoo Finance endpoints used by the site.
// Yahoo rate-limits anonymous requests from data-centre addresses, so every call carries the consent cookie
// and crumb a browser would have. The pair is cached for the life of the function instance and refreshed on a 429.
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";
const BASE = { "User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-AU,en;q=0.9" };
let auth = null;   // { cookie, crumb, at }

async function handshake() {
  const r = await fetch("https://fc.yahoo.com/", { headers: BASE, redirect: "follow" });
  const cookie = (r.headers.get("set-cookie") || "").split(";")[0];
  const c = await fetch("https://query1.finance.yahoo.com/v1/test/getcrumb", { headers: { ...BASE, Cookie: cookie } });
  const crumb = c.ok ? (await c.text()).trim() : "";
  auth = { cookie, crumb: crumb.includes("<") || crumb.includes("Too Many") ? "" : crumb, at: Date.now() };
  return auth;
}

export async function yfetch(url) {
  if (!auth || Date.now() - auth.at > 20 * 60 * 1000) await handshake().catch(() => { auth = { cookie: "", crumb: "", at: Date.now() }; });
  const call = () => fetch(url + (auth.crumb ? (url.includes("?") ? "&" : "?") + "crumb=" + encodeURIComponent(auth.crumb) : ""),
                           { headers: auth.cookie ? { ...BASE, Cookie: auth.cookie } : BASE });
  let r = await call();
  if (r.status === 429 || r.status === 401) { await handshake().catch(() => {}); r = await call(); }
  if (!r.ok) throw new Error(`Yahoo returned ${r.status}`);
  return r.json();
}
export const json = (body, status = 200, cacheSeconds = 0) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": status === 200 && cacheSeconds ? `public, max-age=${cacheSeconds}` : "no-store" } });
