-- applyocalypse:no-transaction
PRAGMA foreign_keys=off;
PRAGMA legacy_alter_table=ON;

ALTER TABLE review_requests RENAME TO review_requests_old;

CREATE TABLE review_requests (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  step_id TEXT REFERENCES application_steps(id) ON DELETE SET NULL,
  review_type TEXT NOT NULL CHECK (review_type IN ('FINAL_SUBMIT','ANSWER','DOCUMENT','OTP','AMBIGUOUS_QUESTION','CAPTCHA','MFA','LOGIN','PORTAL_ENTRY')),
  prompt TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','APPROVED','REJECTED','EXPIRED','CANCELLED')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  resolved_at TEXT
);

INSERT INTO review_requests (
  id, application_run_id, step_id, review_type, prompt, payload_json,
  status, created_at, updated_at, resolved_at
)
SELECT
  id, application_run_id, step_id, review_type, prompt, payload_json,
  status, created_at, updated_at, resolved_at
FROM review_requests_old;

DROP TABLE review_requests_old;

CREATE INDEX IF NOT EXISTS idx_review_requests_run_status ON review_requests(application_run_id, status);

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=on;
