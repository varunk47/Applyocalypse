-- SimHash fingerprint of the raw JD text; used to flag repostings and
-- cross-listings of a description the user has already processed (agency
-- reposts under a different URL/company that URL dedupe cannot catch).
ALTER TABLE job_descriptions ADD COLUMN jd_simhash TEXT;
CREATE INDEX IF NOT EXISTS idx_job_descriptions_simhash ON job_descriptions(jd_simhash);
