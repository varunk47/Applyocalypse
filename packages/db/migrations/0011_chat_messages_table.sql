CREATE TABLE IF NOT EXISTS chat_messages (
  id           TEXT PRIMARY KEY,
  batch_id     TEXT,
  run_id       TEXT REFERENCES application_runs(id) ON DELETE SET NULL,
  job_id       TEXT REFERENCES queue_items(id) ON DELETE SET NULL,
  role         TEXT NOT NULL CHECK (role IN ('USER', 'SYSTEM')),
  kind         TEXT NOT NULL CHECK (kind IN ('TEXT', 'JOB_CARD', 'BATCH_HEADER')),
  content      TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);
