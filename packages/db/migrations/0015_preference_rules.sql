-- The user's own answers, chosen per job at fill time. conditions_json holds
-- optional job conditions ({"location": "GA", "company": ..., "portal": ...});
-- the worker picks the enabled rule with the most conditions that all hold.
CREATE TABLE IF NOT EXISTS preference_rules (
  id              TEXT PRIMARY KEY,
  profile_id      TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  question        TEXT NOT NULL CHECK (length(trim(question)) > 0),
  answer          TEXT NOT NULL CHECK (length(trim(answer)) > 0),
  conditions_json TEXT NOT NULL DEFAULT '{}',
  enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_preference_rules_profile ON preference_rules(profile_id);
