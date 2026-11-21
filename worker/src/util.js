// Small helpers shared by the Worker modules.

export const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", ...headers } });

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Store a buffer in R2 (integrity-checked) and record it in the file manifest. */
export async function storeBuffer(env, key, buffer, { session, kind }) {
  const sha256 = await sha256Hex(buffer);
  await env.BUCKET.put(key, buffer, { sha256 });
  await recordFile(env, key, buffer.byteLength, sha256, session, kind);
  return sha256;
}

/** Store a response body of known length in R2 without buffering it, and record it. */
export async function storeStream(env, key, response, { session, kind }) {
  const length = Number(response.headers.get("content-length"));
  if (!Number.isFinite(length)) throw new Error(`no content-length for ${key}`);
  const { readable, writable } = new FixedLengthStream(length);
  await Promise.all([response.body.pipeTo(writable), env.BUCKET.put(key, readable)]);
  await recordFile(env, key, length, null, session, kind);
}

async function recordFile(env, key, size, sha256, session, kind) {
  await env.DB.prepare(
    `INSERT INTO files (key, session, kind, size, sha256) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (key) DO UPDATE SET size = excluded.size, sha256 = excluded.sha256`,
  ).bind(key, session, kind, size, sha256).run();
}

export async function updateMatch(env, session, fields) {
  const names = Object.keys(fields);
  const sets = names.map((n) => `${n} = ?`).join(", ");
  await env.DB.prepare(
    `UPDATE matches SET ${sets}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE session = ?`,
  ).bind(...names.map((n) => fields[n]), session).run();
}
