-- D1: the manifest and small summary tables. Everything here is rebuildable from R2.

-- One row per battle, with the status of every pipeline step.
CREATE TABLE IF NOT EXISTS matches (
  session        TEXT PRIMARY KEY,          -- 16-digit hex session id
  started        TEXT,                      -- ISO time, UTC
  map            TEXT,
  mission        TEXT,
  game_mode      TEXT,                      -- air | ground | ...
  difficulty     TEXT,                      -- AB | RB | SB
  mission_mode   TEXT,                      -- Dom2, BfD, ...
  duration_s     REAL,
  replay_version INTEGER,
  mrank          INTEGER,                   -- matchmaking rank (BR bracket)
  vehicles       TEXT,                      -- JSON array of vehicle ids in my lineup
  country        TEXT,
  kills          INTEGER,
  ai_kills       INTEGER,
  assists        INTEGER,
  deaths         INTEGER,
  captures       INTEGER,
  score          INTEGER,
  result         TEXT,                      -- win | loss | NULL
  end_reason     TEXT,
  server_status  TEXT NOT NULL DEFAULT 'pending',  -- pending | done | missing | failed
  server_parts   INTEGER,
  server_attempts INTEGER NOT NULL DEFAULT 0,
  decode_status  TEXT NOT NULL DEFAULT 'waiting',  -- waiting | queued | running | done | failed
  decoder        TEXT,                      -- e.g. heat3d-0.2.2
  schema_version INTEGER,
  decode_error   TEXT,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS matches_started ON matches (started);

-- Every object stored in R2, with its hash: the file manifest.
CREATE TABLE IF NOT EXISTS files (
  key        TEXT PRIMARY KEY,              -- R2 key
  session    TEXT,
  kind       TEXT NOT NULL,                 -- client | server | live | decoded
  size       INTEGER NOT NULL,
  sha256     TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS files_session ON files (session);
