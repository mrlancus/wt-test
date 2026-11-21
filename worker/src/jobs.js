// Queue jobs: fetch a battle's server replay, then decode it in the pipeline container.

import { sleep, storeBuffer, storeStream, updateMatch } from "./util.js";

const REPLAY_HOST = "https://wt-game-replays.warthunder.com";
// When part 0 is not there yet: wait this long before the next try (seconds; queue max is 12 h).
const SERVER_RETRY_DELAYS = [120, 600, 1800, 3600, 10800, 43200];
// Gaijin's CDN resets connections now and then; a part is retried this often before giving up for now.
const PART_TRIES = 6;
const MAX_PARTS = 200;

export async function handleJob(env, job) {
  if (job.type === "fetch_server") return fetchServer(env, job);
  if (job.type === "decode") return decodeMatch(env, job.session);
  throw new Error(`unknown job ${job.type}`);
}

async function fetchServer(env, { session, attempt = 0 }) {
  const prefix = `raw/replays/server/${session}/`;
  const have = new Set((await env.BUCKET.list({ prefix })).objects.map((o) => o.key));
  let part = 0;
  for (; part < MAX_PARTS; part++) {
    const key = `${prefix}${String(part).padStart(4, "0")}.wrpl`;
    if (have.has(key)) continue;
    const response = await getPart(session, part);
    if (response === null) break; // 404/403: no more parts
    await storeStream(env, key, response, { session, kind: "server" });
  }
  await updateMatch(env, session, { server_attempts: attempt + 1 });
  if (part > 0) {
    await updateMatch(env, session, { server_status: "done", server_parts: part });
    return queueDecode(env, session);
  }
  if (attempt + 1 < SERVER_RETRY_DELAYS.length) {
    await env.JOBS.send({ type: "fetch_server", session, attempt: attempt + 1 }, { delaySeconds: SERVER_RETRY_DELAYS[attempt + 1] });
    return;
  }
  // Never appeared: decode what we have (the client replay).
  await updateMatch(env, session, { server_status: "missing" });
  return queueDecode(env, session);
}

/** One server replay part: the response, or null when the server says there is no such part. */
async function getPart(session, part) {
  const url = `${REPLAY_HOST}/${session}/${String(part).padStart(4, "0")}.wrpl`;
  let lastError;
  for (let tryNo = 0; tryNo < PART_TRIES; tryNo++) {
    try {
      const response = await fetch(url, { redirect: "follow", headers: { "user-agent": "wt-analytics (personal replay archive)" } });
      if (response.ok) return response;
      await response.body?.cancel();
      if (response.status === 404 || response.status === 403) return null;
      lastError = new Error(`${url}: HTTP ${response.status}`);
    } catch (e) {
      lastError = e;
    }
    await sleep(2000 * 2 ** tryNo);
  }
  throw lastError; // the queue retries the whole job; parts already stored are skipped
}

export async function queueDecode(env, session) {
  await updateMatch(env, session, { decode_status: "queued", decode_error: null });
  await env.JOBS.send({ type: "decode", session });
}

async function decodeMatch(env, session) {
  await updateMatch(env, session, { decode_status: "running" });
  const box = env.PIPELINE.getByName(`job-${session}`);
  const call = (path, init) => box.fetch(`http://pipeline/jobs/${session}${path}`, init);
  try {
    const inputs = await inputFiles(env, session);
    if (!inputs.length) throw new Error("no replay files stored");
    for (const { key, source, name } of inputs) {
      const object = await env.BUCKET.get(key);
      const put = await call(`/in/${source}/${name}`, { method: "PUT", body: object.body, headers: { "content-length": String(object.size) } });
      if (!put.ok) throw new Error(`upload ${key}: ${await put.text()}`);
    }
    const run = await call("/run", { method: "POST", body: JSON.stringify({ me_user_id: env.ME_USER_ID }) });
    const result = await run.json();
    if (!run.ok) throw new Error(result.error);
    for (const [source, { files }] of Object.entries(result.sources)) {
      for (const name of files) {
        const response = await call(`/out/${source}/${name}`);
        if (!response.ok) throw new Error(`fetch output ${source}/${name}: HTTP ${response.status}`);
        await storeStream(env, `decoded/${result.decoder}/${session}/${source}/${name}`, response, { session, kind: "decoded" });
      }
    }
    await storeBuffer(env, `decoded/${result.decoder}/${session}/result.json`, new TextEncoder().encode(JSON.stringify(result)), { session, kind: "decoded" });
    const failed = Object.entries(result.errors);
    await updateMatch(env, session, {
      ...summaryColumns(result.summary),
      decoder: result.decoder,
      schema_version: result.schema_version,
      decode_status: Object.keys(result.sources).length ? "done" : "failed",
      decode_error: failed.length ? failed.map(([s, e]) => `${s}: ${e}`).join("\n") : null,
    });
  } catch (e) {
    await updateMatch(env, session, { decode_status: "failed", decode_error: String(e.stack || e).slice(0, 2000) });
  } finally {
    await call("", { method: "DELETE" }).catch(() => {});
  }
}

async function inputFiles(env, session) {
  const rows = (await env.DB.prepare("SELECT key, kind FROM files WHERE session = ? AND kind IN ('client', 'server') ORDER BY key").bind(session).all()).results;
  return rows.map(({ key, kind }) => ({ key, source: kind, name: key.split("/").pop() }));
}

const SUMMARY_COLUMNS = ["started", "map", "mission", "game_mode", "difficulty", "mission_mode", "duration_s", "replay_version", "mrank", "country", "kills", "ai_kills", "assists", "deaths", "captures", "score", "result", "end_reason"];

function summaryColumns(summary) {
  if (!summary) return {};
  const out = Object.fromEntries(SUMMARY_COLUMNS.map((c) => [c, summary[c] ?? null]));
  out.vehicles = JSON.stringify(summary.vehicles ?? []);
  return out;
}
