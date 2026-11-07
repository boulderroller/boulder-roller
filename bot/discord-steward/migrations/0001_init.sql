CREATE TABLE IF NOT EXISTS counters (
  scope TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS intakes (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL,
  reporter_id TEXT NOT NULL,
  reporter_tag TEXT NOT NULL,
  guild_id TEXT,
  source_channel_id TEXT,
  target_channel_id TEXT,
  staff_message_id TEXT,
  fields_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_intakes_status_created
  ON intakes(status, created_at);

CREATE INDEX IF NOT EXISTS idx_intakes_reporter_created
  ON intakes(reporter_id, created_at);

CREATE TABLE IF NOT EXISTS intake_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  intake_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  actor_tag TEXT NOT NULL,
  action TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (intake_id) REFERENCES intakes(id)
);

CREATE INDEX IF NOT EXISTS idx_intake_events_intake_created
  ON intake_events(intake_id, created_at);
