ALTER TABLE profiles ADD COLUMN application_email TEXT;
ALTER TABLE profiles ADD COLUMN application_password_secret_ref_id TEXT REFERENCES encrypted_secrets(id) ON DELETE SET NULL;
ALTER TABLE profiles ADD COLUMN otp_provider_connection_id TEXT REFERENCES provider_connections(id) ON DELETE SET NULL;
ALTER TABLE profiles ADD COLUMN otp_handling_enabled INTEGER NOT NULL DEFAULT 0 CHECK (otp_handling_enabled IN (0, 1));

CREATE INDEX IF NOT EXISTS idx_profiles_application_email ON profiles(application_email);
CREATE INDEX IF NOT EXISTS idx_profiles_application_password_secret ON profiles(application_password_secret_ref_id);
CREATE INDEX IF NOT EXISTS idx_profiles_otp_provider_connection ON profiles(otp_provider_connection_id);
