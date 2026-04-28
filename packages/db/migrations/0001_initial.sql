PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS encrypted_secrets (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('openai','anthropic','gemini','xai','groq','nvidia_nim','openrouter','azure_openai','aws_bedrock','gmail','local')),
  key_name TEXT NOT NULL,
  storage_backend TEXT NOT NULL CHECK (storage_backend IN ('electron_safe_storage','os_keychain','env_ref','external_secret_manager')),
  reference TEXT NOT NULL,
  redacted_hint TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS provider_connections (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('openai','anthropic','gemini','xai','groq','nvidia_nim','openrouter','azure_openai','aws_bedrock','gmail')),
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DISCONNECTED' CHECK (status IN ('DISCONNECTED','CONNECTED','ERROR')),
  secret_ref_id TEXT REFERENCES encrypted_secrets(id) ON DELETE SET NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  last_checked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  email TEXT,
  phone TEXT,
  location TEXT,
  links_json TEXT NOT NULL DEFAULT '[]',
  job_defaults_json TEXT NOT NULL DEFAULT '{}',
  work_authorization_json TEXT NOT NULL DEFAULT '{}',
  equal_employment_defaults_json TEXT NOT NULL DEFAULT '{}',
  user_overrides_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS profile_snapshots (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  reason TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS education_entries (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  institution TEXT NOT NULL,
  degree TEXT,
  field TEXT,
  start_date TEXT,
  end_date TEXT,
  details_json TEXT NOT NULL DEFAULT '[]',
  source_confidence REAL NOT NULL DEFAULT 1 CHECK (source_confidence >= 0 AND source_confidence <= 1),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS experience_entries (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT,
  start_date TEXT,
  end_date TEXT,
  bullets_json TEXT NOT NULL DEFAULT '[]',
  tools_json TEXT NOT NULL DEFAULT '[]',
  source_confidence REAL NOT NULL DEFAULT 1 CHECK (source_confidence >= 0 AND source_confidence <= 1),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS project_entries (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  role TEXT,
  summary TEXT,
  bullets_json TEXT NOT NULL DEFAULT '[]',
  tools_json TEXT NOT NULL DEFAULT '[]',
  links_json TEXT NOT NULL DEFAULT '[]',
  source_confidence REAL NOT NULL DEFAULT 1 CHECK (source_confidence >= 0 AND source_confidence <= 1),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS certification_entries (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  issuer TEXT,
  issued_at TEXT,
  expires_at TEXT,
  credential_url TEXT,
  source_confidence REAL NOT NULL DEFAULT 1 CHECK (source_confidence >= 0 AND source_confidence <= 1),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS skill_groups (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  skills_json TEXT NOT NULL DEFAULT '[]',
  source_confidence REAL NOT NULL DEFAULT 1 CHECK (source_confidence >= 0 AND source_confidence <= 1),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS uploaded_files (
  id TEXT PRIMARY KEY,
  profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
  file_kind TEXT NOT NULL CHECK (file_kind IN ('RESUME','COVER_LETTER','SUPPORTING_DETAILS','OTHER')),
  source_format TEXT NOT NULL CHECK (source_format IN ('PDF','DOCX','TEX','TXT','MD')),
  original_name TEXT NOT NULL,
  local_path TEXT NOT NULL,
  mime_type TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  sha256 TEXT,
  status TEXT NOT NULL CHECK (status IN ('UPLOADED','IMMUTABLE_SOURCE','UNVERIFIED_EDITABLE_MASTER','VERIFIED_EDITABLE_MASTER','REJECTED','DELETED')),
  parent_file_id TEXT REFERENCES uploaded_files(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS parsed_documents (
  id TEXT PRIMARY KEY,
  uploaded_file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
  parser_name TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  canonical_json TEXT NOT NULL,
  style_map_json TEXT NOT NULL DEFAULT '{}',
  anchor_map_json TEXT NOT NULL DEFAULT '{}',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS job_targets (
  id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('URL','TEXT')),
  source_value TEXT NOT NULL,
  company TEXT,
  role TEXT,
  location TEXT,
  portal TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT,
  CHECK (status IN ('PENDING','CLAIMED','PREPARING','PARSING_JD','ANALYZING','TAILORING_RESUME','GENERATING_COVER_LETTER','READY_FOR_REVIEW','RUNNING_AUTOMATION','PAUSED','BLOCKED_CAPTCHA','BLOCKED_MFA','BLOCKED_OTP','BLOCKED_AMBIGUOUS_QUESTION','WAITING_FOR_USER_EDIT','READY_TO_SUBMIT','SUBMITTED','COMPLETED','FAILED','CANCELLED'))
);

CREATE TABLE IF NOT EXISTS job_descriptions (
  id TEXT PRIMARY KEY,
  job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
  raw_text TEXT NOT NULL,
  scraped_url TEXT,
  source TEXT NOT NULL CHECK (source IN ('USER_TEXT','SCRAPED','IMPORTED')),
  sha256 TEXT,
  extracted_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS jd_keyword_sets (
  id TEXT PRIMARY KEY,
  job_description_id TEXT NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
  must_have_json TEXT NOT NULL DEFAULT '[]',
  preferred_json TEXT NOT NULL DEFAULT '[]',
  hard_requirements_json TEXT NOT NULL DEFAULT '[]',
  tools_json TEXT NOT NULL DEFAULT '[]',
  domain_signals_json TEXT NOT NULL DEFAULT '[]',
  location_signals_json TEXT NOT NULL DEFAULT '[]',
  work_authorization_signals_json TEXT NOT NULL DEFAULT '[]',
  seniority_cues_json TEXT NOT NULL DEFAULT '[]',
  communication_cues_json TEXT NOT NULL DEFAULT '[]',
  required_materials_json TEXT NOT NULL DEFAULT '[]',
  cover_letter_likely_required INTEGER NOT NULL DEFAULT 0 CHECK (cover_letter_likely_required IN (0,1)),
  risky_claims_to_avoid_json TEXT NOT NULL DEFAULT '[]',
  evidence_matches_json TEXT NOT NULL DEFAULT '[]',
  missing_truthful_json TEXT NOT NULL DEFAULT '[]',
  truly_missing_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tailoring_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
  jd_keyword_set_id TEXT REFERENCES jd_keyword_sets(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'PREPARING' CHECK (status IN ('PREPARING','ANALYZING','TAILORING_RESUME','GENERATING_COVER_LETTER','READY_FOR_REVIEW','COMPLETED','FAILED','CANCELLED')),
  one_page_plan_json TEXT NOT NULL DEFAULT '{}',
  resume_plan_json TEXT NOT NULL DEFAULT '{}',
  cover_letter_plan_json TEXT NOT NULL DEFAULT '{}',
  validation_summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS generated_files (
  id TEXT PRIMARY KEY,
  tailoring_run_id TEXT REFERENCES tailoring_runs(id) ON DELETE SET NULL,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
  file_kind TEXT NOT NULL CHECK (file_kind IN ('RESUME','COVER_LETTER')),
  format TEXT NOT NULL CHECK (format IN ('DOCX','PDF','TEX','TXT','MD')),
  filename TEXT NOT NULL,
  local_path TEXT NOT NULL,
  sha256 TEXT,
  size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
  upload_status TEXT NOT NULL DEFAULT 'NOT_UPLOADED' CHECK (upload_status IN ('NOT_UPLOADED','UPLOADED','FAILED','SKIPPED')),
  uploaded_at TEXT,
  retention_policy TEXT NOT NULL DEFAULT 'DELETE_AFTER_RETENTION' CHECK (retention_policy IN ('DELETE_AFTER_UPLOAD','DELETE_AFTER_RETENTION','KEEP_UNTIL_USER_DELETES')),
  delete_after TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS validation_reports (
  id TEXT PRIMARY KEY,
  tailoring_run_id TEXT REFERENCES tailoring_runs(id) ON DELETE SET NULL,
  generated_file_id TEXT REFERENCES generated_files(id) ON DELETE SET NULL,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('TXT','MD','DOCX','TEX','PDF_RENDERED')),
  passed INTEGER NOT NULL CHECK (passed IN (0,1)),
  blocking_issues_json TEXT NOT NULL DEFAULT '[]',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  report_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS queue_items (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'PENDING',
  priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1 AND max_attempts <= 5),
  claimed_by TEXT,
  lease_expires_at TEXT,
  heartbeat_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT,
  CHECK (status IN ('PENDING','CLAIMED','PREPARING','PARSING_JD','ANALYZING','TAILORING_RESUME','GENERATING_COVER_LETTER','READY_FOR_REVIEW','RUNNING_AUTOMATION','PAUSED','BLOCKED_CAPTCHA','BLOCKED_MFA','BLOCKED_OTP','BLOCKED_AMBIGUOUS_QUESTION','WAITING_FOR_USER_EDIT','READY_TO_SUBMIT','SUBMITTED','COMPLETED','FAILED','CANCELLED'))
);

CREATE TABLE IF NOT EXISTS application_runs (
  id TEXT PRIMARY KEY,
  queue_item_id TEXT NOT NULL REFERENCES queue_items(id) ON DELETE CASCADE,
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
  tailoring_run_id TEXT REFERENCES tailoring_runs(id) ON DELETE SET NULL,
  status TEXT NOT NULL,
  current_step_id TEXT,
  auto_submit_enabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_submit_enabled IN (0,1)),
  worker_id TEXT,
  lease_expires_at TEXT,
  heartbeat_at TEXT,
  started_at TEXT,
  completed_at TEXT,
  failure_code TEXT,
  failure_message TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  CHECK (status IN ('PENDING','CLAIMED','PREPARING','PARSING_JD','ANALYZING','TAILORING_RESUME','GENERATING_COVER_LETTER','READY_FOR_REVIEW','RUNNING_AUTOMATION','PAUSED','BLOCKED_CAPTCHA','BLOCKED_MFA','BLOCKED_OTP','BLOCKED_AMBIGUOUS_QUESTION','WAITING_FOR_USER_EDIT','READY_TO_SUBMIT','SUBMITTED','COMPLETED','FAILED','CANCELLED'))
);

CREATE TABLE IF NOT EXISTS application_steps (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL CHECK (step_order >= 0),
  step_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','WAITING_FOR_USER','PAUSED','SKIPPED','RETRYING','COMPLETED','FAILED','CANCELLED')),
  page_url TEXT,
  selector TEXT,
  expected_state_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE(application_run_id, step_order)
);

CREATE TABLE IF NOT EXISTS application_answers (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  step_id TEXT REFERENCES application_steps(id) ON DELETE SET NULL,
  field_label TEXT NOT NULL,
  field_type TEXT NOT NULL,
  proposed_value TEXT,
  user_value TEXT,
  source TEXT NOT NULL CHECK (source IN ('PROFILE','JD_ANALYSIS','USER_EDIT','LLM_PROPOSAL','UNKNOWN')),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED','APPROVED','EDITED','APPLIED','REJECTED')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS review_requests (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  step_id TEXT REFERENCES application_steps(id) ON DELETE SET NULL,
  review_type TEXT NOT NULL CHECK (review_type IN ('FINAL_SUBMIT','ANSWER','DOCUMENT','OTP','AMBIGUOUS_QUESTION','CAPTCHA','MFA')),
  prompt TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','APPROVED','REJECTED','EXPIRED','CANCELLED')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  review_request_id TEXT REFERENCES review_requests(id) ON DELETE SET NULL,
  approval_type TEXT NOT NULL CHECK (approval_type IN ('FINAL_SUBMIT','ANSWER_EDIT','DOCUMENT_APPROVAL','OTP_READ','AUTO_SUBMIT')),
  status TEXT NOT NULL CHECK (status IN ('OPEN','APPROVED','REJECTED','EXPIRED','CANCELLED')),
  approved_by TEXT NOT NULL DEFAULT 'local_user',
  decided_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS screenshots (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  step_id TEXT REFERENCES application_steps(id) ON DELETE SET NULL,
  screenshot_id TEXT NOT NULL,
  local_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  width INTEGER NOT NULL CHECK (width > 0),
  height INTEGER NOT NULL CHECK (height > 0),
  sha256 TEXT,
  captured_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS browser_artifacts (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  artifact_type TEXT NOT NULL CHECK (artifact_type IN ('DOM_SNAPSHOT','NETWORK_LOG','CONSOLE_LOG','TRACE','DOWNLOAD')),
  local_path TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL,
  step_id TEXT,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('DEBUG','INFO','WARN','ERROR','CRITICAL')),
  message TEXT NOT NULL,
  machine_state_json TEXT NOT NULL DEFAULT '{}',
  ui_state_json TEXT NOT NULL DEFAULT '{}',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  FOREIGN KEY(application_run_id) REFERENCES application_runs(id) ON DELETE CASCADE,
  FOREIGN KEY(step_id) REFERENCES application_steps(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS otp_sessions (
  id TEXT PRIMARY KEY,
  application_run_id TEXT NOT NULL REFERENCES application_runs(id) ON DELETE CASCADE,
  provider_connection_id TEXT REFERENCES provider_connections(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('REQUESTED','WAITING','COMPLETED','TIMEOUT','FAILED','CANCELLED')),
  purpose TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  expires_at TEXT,
  completed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_provider_connections_provider ON provider_connections(provider);
CREATE INDEX IF NOT EXISTS idx_profiles_deleted_at ON profiles(deleted_at);
CREATE INDEX IF NOT EXISTS idx_education_profile ON education_entries(profile_id);
CREATE INDEX IF NOT EXISTS idx_experience_profile ON experience_entries(profile_id);
CREATE INDEX IF NOT EXISTS idx_projects_profile ON project_entries(profile_id);
CREATE INDEX IF NOT EXISTS idx_skill_groups_profile ON skill_groups(profile_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_profile ON uploaded_files(profile_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_status ON uploaded_files(status);
CREATE INDEX IF NOT EXISTS idx_parsed_documents_file ON parsed_documents(uploaded_file_id);
CREATE INDEX IF NOT EXISTS idx_job_targets_status ON job_targets(status);
CREATE INDEX IF NOT EXISTS idx_job_descriptions_target ON job_descriptions(job_target_id);
CREATE INDEX IF NOT EXISTS idx_jd_keyword_sets_description ON jd_keyword_sets(job_description_id);
CREATE INDEX IF NOT EXISTS idx_tailoring_runs_target ON tailoring_runs(job_target_id);
CREATE INDEX IF NOT EXISTS idx_generated_files_target ON generated_files(job_target_id);
CREATE INDEX IF NOT EXISTS idx_validation_reports_tailoring ON validation_reports(tailoring_run_id);
CREATE INDEX IF NOT EXISTS idx_queue_items_status_priority ON queue_items(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_queue_items_lease ON queue_items(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_application_runs_status ON application_runs(status);
CREATE INDEX IF NOT EXISTS idx_application_runs_queue ON application_runs(queue_item_id);
CREATE INDEX IF NOT EXISTS idx_application_steps_run ON application_steps(application_run_id, step_order);
CREATE INDEX IF NOT EXISTS idx_application_answers_run ON application_answers(application_run_id);
CREATE INDEX IF NOT EXISTS idx_review_requests_run_status ON review_requests(application_run_id, status);
CREATE INDEX IF NOT EXISTS idx_approvals_run ON approvals(application_run_id);
CREATE INDEX IF NOT EXISTS idx_screenshots_run ON screenshots(application_run_id, captured_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_screenshots_run_screenshot_id ON screenshots(application_run_id, screenshot_id);
CREATE INDEX IF NOT EXISTS idx_browser_artifacts_run ON browser_artifacts(application_run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_run_created ON run_events(application_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_otp_sessions_run ON otp_sessions(application_run_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
