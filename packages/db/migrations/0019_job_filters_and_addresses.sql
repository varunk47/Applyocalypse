-- Rules that decide whether a job is worth applying to at all. The worker
-- checks them once the job description is known and stops the run with the
-- reason before any tailoring. kind picks how value is read:
--   skip_company      a company name to never apply to
--   skip_keyword      a word or phrase in the title or description that rules a job out
--   min_salary        the lowest advertised top-of-range salary worth applying for
--   work_arrangement  remote, hybrid or onsite; when any are set, only those are allowed
--   place             a city, state or country onsite and hybrid jobs must be in
CREATE TABLE IF NOT EXISTS job_filters (
  id          TEXT PRIMARY KEY,
  profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN ('skip_company', 'skip_keyword', 'min_salary', 'work_arrangement', 'place')),
  value       TEXT NOT NULL CHECK (length(trim(value)) > 0),
  enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_job_filters_profile ON job_filters(profile_id);

-- Places the user can live or work from besides the profile's own address.
-- The worker fills forms with the one in the job's city, and counts every
-- city here as an allowed place when place filters are on.
CREATE TABLE IF NOT EXISTS profile_addresses (
  id             TEXT PRIMARY KEY,
  profile_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  label          TEXT NOT NULL DEFAULT '',
  address_line1  TEXT NOT NULL DEFAULT '',
  address_line2  TEXT NOT NULL DEFAULT '',
  city           TEXT NOT NULL CHECK (length(trim(city)) > 0),
  state          TEXT NOT NULL DEFAULT '',
  postal_code    TEXT NOT NULL DEFAULT '',
  country        TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_profile_addresses_profile ON profile_addresses(profile_id);
