-- D1: the website's tables. Rebuildable from the manifests on the desk-hub share.

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
  server_status  TEXT NOT NULL DEFAULT 'pending',  -- pending | done | missing
  decode_status  TEXT NOT NULL DEFAULT 'inbox',    -- inbox (uploaded on the site, PC not done yet) | done | failed
  decoder        TEXT,                      -- e.g. heat3d-0.2.2
  schema_version INTEGER,
  decode_error   TEXT,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS matches_started ON matches (started);

-- Every object the website keeps in R2, with its hash.
CREATE TABLE IF NOT EXISTS files (
  key        TEXT PRIMARY KEY,              -- R2 key
  session    TEXT,
  kind       TEXT NOT NULL,                 -- inbox | viewer | derived
  size       INTEGER NOT NULL,
  sha256     TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS files_session ON files (session);
