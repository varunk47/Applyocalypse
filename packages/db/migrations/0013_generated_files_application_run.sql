-- Ties each generated file to the exact run that produced it. The
-- profile+job fallback in listGeneratedFiles previously let a crashed
-- sibling run's documents leak into another run's approval payload; the
-- fallback now applies only to legacy rows created before this column existed.
ALTER TABLE generated_files ADD COLUMN application_run_id TEXT;
CREATE INDEX IF NOT EXISTS idx_generated_files_application_run_id ON generated_files(application_run_id);
