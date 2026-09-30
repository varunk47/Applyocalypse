-- Applications ask why the applicant left each job and, often, for up to three
-- references. Both come from the user once, during onboarding.
ALTER TABLE experience_entries ADD COLUMN reason_for_leaving TEXT;
ALTER TABLE profiles ADD COLUMN references_json TEXT NOT NULL DEFAULT '[]';
