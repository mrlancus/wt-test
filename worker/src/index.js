// wt-analytics Worker: the API, uploads and queue consumer. Static pages come from ../web (assets).

import { handleJob, queueDecode } from "./jobs.js";
import { readHeader } from "./replay.js";
import { json, storeBuffer } from "./util.js";

export { Pipeline } from "./pipeline.js";

const COOKIE = "wt_key";
const MAX_REPLAY_BYTES = 95 * 1024 * 1024;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (url.pathname === "/api/login" && request.method === "POST") return login(request, env);
    if (!(await authorised(request, env))) return json({ error: "login required" }, 401);
    try {
      return await route(request, env, url);
    } catch (e) {
      return json({ error: String(e.message || e) }, e.status || 500);
    }
  },

  async queue(batch, env) {
    for (const message of batch.messages) {
      try {
        await handleJob(env, message.body);
        message.ack();
      } catch (e) {
        console.error("job failed", message.body, e);
        message.retry({ delaySeconds: 60 * 2 ** Math.min(message.attempts, 6) });
      }
    }
  },
};

async function route(request, env, url) {
  const [, , resource, id, action] = url.pathname.split("/");
  const method = request.method;
  if (resource === "upload" && method === "PUT") return uploadClientReplay(request, env, url);
  if (resource === "matches" && !id && method === "GET") return listMatches(env, url);
  if (resource === "matches" && id && !action && method === "GET") return getMatch(env, id);
  if (resource === "matches" && id && action === "redecode" && method === "POST") {
    await queueDecode(env, id);
    return json({ ok: true });
  }
  if (resource === "health" && method === "GET") return health(env);
  return json({ error: "not found" }, 404);
}

/** PUT /api/upload?name=<file name> with the raw .wrpl as the body. Idempotent per session. */
async function uploadClientReplay(request, env, url) {
  const size = Number(request.headers.get("content-length"));
  if (!(size > 0 && size <= MAX_REPLAY_BYTES)) throw Object.assign(new Error("body must be a replay under 95 MB"), { status: 413 });
  const buffer = await request.arrayBuffer();
  const header = readHeader(buffer);
  if (header.part !== 0) throw Object.assign(new Error("upload client replays; server replay parts are fetched automatically"), { status: 400 });
  const started = new Date(header.startTime * 1000).toISOString();
  const key = `raw/replays/client/${started.slice(0, 10)}/${header.session}.wrpl`;
  const existing = await env.DB.prepare("SELECT decode_status FROM matches WHERE session = ?").bind(header.session).first();
  await storeBuffer(env, key, buffer, { session: header.session, kind: "client" });
  if (!existing) {
    await env.DB.prepare("INSERT INTO matches (session, started, map, replay_version) VALUES (?, ?, ?, ?)")
      .bind(header.session, started, header.map, header.version).run();
    await env.JOBS.send({ type: "fetch_server", session: header.session, attempt: 0 }, { delaySeconds: 60 });
  }
  return json({ session: header.session, map: header.map, started, name: url.searchParams.get("name"), new: !existing });
}

async function listMatches(env, url) {
  const limit = Math.min(Number(url.searchParams.get("limit")) || 100, 500);
  const { results } = await env.DB.prepare("SELECT * FROM matches ORDER BY started DESC LIMIT ?").bind(limit).all();
  return json({ matches: results });
}

async function getMatch(env, session) {
  const match = await env.DB.prepare("SELECT * FROM matches WHERE session = ?").bind(session).first();
  if (!match) return json({ error: "no such match" }, 404);
  const { results: files } = await env.DB.prepare("SELECT key, kind, size, sha256 FROM files WHERE session = ? ORDER BY key").bind(session).all();
  return json({ match, files });
}

async function health(env) {
  const [storage, server, decode] = await env.DB.batch([
    env.DB.prepare("SELECT kind, COUNT(*) AS files, SUM(size) AS bytes FROM files GROUP BY kind"),
    env.DB.prepare("SELECT server_status AS status, COUNT(*) AS n FROM matches GROUP BY 1"),
    env.DB.prepare("SELECT decode_status AS status, COUNT(*) AS n FROM matches GROUP BY 1"),
  ]);
  return json({ storage: storage.results, server: server.results, decode: decode.results });
}

// --- auth: one secret key (API_KEY). The helper sends it as a bearer token; the browser gets it as a cookie.

async function authorised(request, env) {
  const bearer = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  const cookie = (request.headers.get("cookie") || "").match(new RegExp(`(?:^|;\\s*)${COOKIE}=([^;]+)`))?.[1];
  const given = bearer || (cookie && decodeURIComponent(cookie));
  return Boolean(given) && (await sameSecret(given, env.API_KEY));
}

async function login(request, env) {
  const { key } = await request.json().catch(() => ({}));
  if (!key || !(await sameSecret(key, env.API_KEY))) return json({ error: "wrong key" }, 401);
  const cookie = `${COOKIE}=${encodeURIComponent(key)}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Strict`;
  return json({ ok: true }, 200, { "set-cookie": cookie });
}

/** Constant-time comparison via hashes of both values. */
async function sameSecret(a, b) {
  if (!b) return false;
  const enc = new TextEncoder();
  const [ha, hb] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(a)), crypto.subtle.digest("SHA-256", enc.encode(b))]);
  return crypto.subtle.timingSafeEqual(ha, hb);
}
