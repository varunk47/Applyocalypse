-- Outreach: people to contact and the messages drafted for them. A message is
-- sent only after it is APPROVED, and sent_at doubles as the send log the daily
-- cap is counted from. Nothing here sends mail by itself.
CREATE TABLE IF NOT EXISTS outreach_contacts (
  id            TEXT PRIMARY KEY,
  profile_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  job_target_id TEXT REFERENCES job_targets(id) ON DELETE SET NULL,
  name          TEXT NOT NULL,
  email         TEXT,
  company       TEXT,
  role_title    TEXT,
  linkedin_url  TEXT,
  notes         TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_outreach_contacts_profile ON outreach_contacts(profile_id);

CREATE TABLE IF NOT EXISTS outreach_messages (
  id            TEXT PRIMARY KEY,
  contact_id    TEXT NOT NULL REFERENCES outreach_contacts(id) ON DELETE CASCADE,
  job_target_id TEXT REFERENCES job_targets(id) ON DELETE SET NULL,
  channel       TEXT NOT NULL CHECK (channel IN ('EMAIL', 'LINKEDIN')),
  subject       TEXT NOT NULL DEFAULT '',
  body          TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'APPROVED', 'SENT', 'FAILED')),
  approved_at   TEXT,
  sent_at       TEXT,
  failure_reason TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_contact ON outreach_messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_sent ON outreach_messages(sent_at);
