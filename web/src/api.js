export async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({ error: "bad JSON from server" }));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}
