// wt-analytics Worker: the website's API. Static pages come from ../web (assets).
// Replays and full decoded data live on desk-hub; Cloudflare holds only what the website shows,
// plus an inbox for replays uploaded on the site until the PC helper has taken them.

import { readHeader } from "./replay.js";
import { HttpError, json, recordFile } from "./util.js";

const COOKIE = "wt_key";
const MAX_REPLAY_BYTES = 95 * 1024 * 1024;
const INBOX = "inbox/";
// Columns the helper may set on a match row (see schema.sql).
const MATCH_COLUMNS = [
  "started", "map", "mission", "game_mode", "difficulty", "mission_mode", "duration_s", "replay_version", "mrank",
  "vehicles", "country", "kills", "ai_kills", "assists", "deaths", "captures", "score", "result", "end_reason",
  "server_status", "decode_status", "decoder", "schema_version", "decode_error",
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      if (url.pathname === "/api/login" && request.method === "POST") return await login(request, env);
      if (!(await authorised(request, env))) return json({ error: "login required" }, 401);
      return await route(request, env, url);
    } catch (e) {
      return json({ error: String(e.message || e) }, e.status || 500);
    }
  },
};

async function route(request, env, url) {
  const [, , resource, id, ...rest] = url.pathname.split("/");
  const method = request.method;
  if (rest.length) throw new HttpError(404, "not found");
  if (resource === "upload" && method === "PUT") return upload(request, env);
  if (resource === "inbox" && !id && method === "GET") return listInbox(env);
  if (resource === "inbox" && id && method === "GET") return getInbox(env, id);
  if (resource === "inbox" && id && method === "DELETE") return deleteInbox(env, id);
  if (resource === "matches" && !id && method === "GET") return listMatches(env, url);
  if (resource === "matches" && id && method === "GET") return getMatch(env, id);
  if (resource === "matches" && id && method === "PUT") return putMatch(request, env, id);
  if (resource === "health" && method === "GET") return health(env);
  throw new HttpError(404, "not found");
}

/** PUT /api/upload: a client .wrpl as the body. Kept in the inbox until the PC helper takes it. */
async function upload(request, env) {
  const size = Number(request.headers.get("content-length"));
  if (!(size > 0 && size <= MAX_REPLAY_BYTES)) throw new HttpError(413, "body must be a replay under 95 MB");
  const buffer = await request.arrayBuffer();
  const header = readHeader(buffer);
  if (header.part !== 0) throw new HttpError(400, "upload client replays; server replays are fetched automatically");
  const started = new Date(header.startTime * 1000).toISOString();
  const existing = await env.DB.prepare("SELECT decode_status FROM matches WHERE session = ?").bind(header.session).first();
  if (!existing) {
    const key = `${INBOX}${header.session}.wrpl`;
    await recordFile(env, key, buffer, { session: header.session, kind: "inbox" });
    await env.DB.prepare("INSERT INTO matches (session, started, map, replay_version) VALUES (?, ?, ?, ?)")
      .bind(header.session, started, header.map, header.version).run();
  }
  return json({ session: header.session, map: header.map, started, new: !existing });
}

async function listInbox(env) {
  const { objects } = await env.BUCKET.list({ prefix: INBOX });
  return json({ files: objects.map((o) => ({ name: o.key.slice(INBOX.length), size: o.size })) });
}

async function getInbox(env, name) {
  const object = await env.BUCKET.get(`${INBOX}${name}`);
  if (!object) throw new HttpError(404, "not in the inbox");
  return new Response(object.body, { headers: { "content-length": String(object.size), "content-type": "application/octet-stream" } });
}

async function deleteInbox(env, name) {
  const key = `${INBOX}${name}`;
  await env.BUCKET.delete(key);
  await env.DB.prepare("DELETE FROM files WHERE key = ?").bind(key).run();
  return json({ ok: true });
}

async function listMatches(env, url) {
  const limit = Math.min(Number(url.searchParams.get("limit")) || 100, 500);
  const { results } = await env.DB.prepare("SELECT * FROM matches ORDER BY started DESC LIMIT ?").bind(limit).all();
  return json({ matches: results });
}

async function getMatch(env, session) {
  const match = await env.DB.prepare("SELECT * FROM matches WHERE session = ?").bind(session).first();
  if (!match) throw new HttpError(404, "no such match");
  return json({ match });
}

/** PUT /api/matches/<session> from the helper: the match row after the PC has processed the battle. */
async function putMatch(request, env, session) {
  if (!/^[0-9a-f]{16}$/.test(session)) throw new HttpError(400, "bad session id");
  const body = await request.json();
  const row = Object.fromEntries(MATCH_COLUMNS.filter((c) => c in body).map((c) => [c, body[c]]));
  if (Array.isArray(row.vehicles)) row.vehicles = JSON.stringify(row.vehicles);
  const names = Object.keys(row);
  const placeholders = names.map(() => "?").join(", ");
  const updates = names.map((n) => `${n} = excluded.${n}`).join(", ");
  await env.DB.prepare(
    `INSERT INTO matches (session${names.map((n) => `, ${n}`).join("")}) VALUES (?${names.length ? ", " : ""}${placeholders})
     ON CONFLICT (session) DO UPDATE SET ${updates ? `${updates}, ` : ""}updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`,
  ).bind(session, ...names.map((n) => row[n])).run();
  return json({ ok: true });
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
  if (!key || !(await sameSecret(key, env.API_KEY))) throw new HttpError(401, "wrong key");
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
