-- applyocalypse: Phase 2.1 — extended profile fields (all additive)

ALTER TABLE profiles ADD COLUMN first_name TEXT;
ALTER TABLE profiles ADD COLUMN last_name TEXT;
ALTER TABLE profiles ADD COLUMN address_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE profiles ADD COLUMN linkedin_url TEXT;
ALTER TABLE profiles ADD COLUMN github_url TEXT;

ALTER TABLE education_entries ADD COLUMN gpa TEXT;
