-- applyocalypse:no-transaction
-- Expand provider CHECK constraints to include 'zai' (Z.ai / GLM provider).
-- SQLite does not support ALTER COLUMN, so we recreate the two affected tables.

PRAGMA foreign_keys = OFF;

CREATE TABLE encrypted_secrets_new (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('openai','anthropic','gemini','zai','xai','groq','nvidia_nim','openrouter','azure_openai','aws_bedrock','gmail','local')),
  key_name TEXT NOT NULL,
  storage_backend TEXT NOT NULL CHECK (storage_backend IN ('electron_safe_storage','os_keychain','env_ref','external_secret_manager')),
  reference TEXT NOT NULL,
  redacted_hint TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);
INSERT INTO encrypted_secrets_new SELECT * FROM encrypted_secrets;
DROP TABLE encrypted_secrets;
ALTER TABLE encrypted_secrets_new RENAME TO encrypted_secrets;

CREATE TABLE provider_connections_new (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('openai','anthropic','gemini','zai','xai','groq','nvidia_nim','openrouter','azure_openai','aws_bedrock','gmail')),
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DISCONNECTED' CHECK (status IN ('DISCONNECTED','CONNECTED','ERROR')),
  secret_ref_id TEXT REFERENCES encrypted_secrets(id) ON DELETE SET NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  last_checked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  deleted_at TEXT
);
INSERT INTO provider_connections_new SELECT * FROM provider_connections;
DROP TABLE provider_connections;
ALTER TABLE provider_connections_new RENAME TO provider_connections;

PRAGMA foreign_keys = ON;
