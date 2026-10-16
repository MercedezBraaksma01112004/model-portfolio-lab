import { getStore } from "@netlify/blobs";
// GET ?job=<id> -> the AI review written by review-background, or { status: "pending" } until it is ready.
// Job ids are random UUIDs made by the page, so only the visitor who started a review can read it.
export default async (req) => {
  const job = new URL(req.url).searchParams.get("job") || "";
  const res = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  if (!/^[0-9a-f-]{20,60}$/i.test(job)) return res({ error: "job id required" }, 400);
  const v = await getStore({ name: "reviews", consistency: "strong" }).get(job, { type: "json" });
  return res(v || { status: "pending" });
};
