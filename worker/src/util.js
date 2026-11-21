// Small helpers shared by the Worker modules.

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", ...headers } });

async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Store a buffer in R2 (integrity-checked) and record it in the file manifest. */
export async function recordFile(env, key, buffer, { session, kind }) {
  const sha256 = await sha256Hex(buffer);
  await env.BUCKET.put(key, buffer, { sha256 });
  await env.DB.prepare(
    `INSERT INTO files (key, session, kind, size, sha256) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (key) DO UPDATE SET size = excluded.size, sha256 = excluded.sha256`,
  ).bind(key, session, kind, buffer.byteLength, sha256).run();
  return sha256;
}
