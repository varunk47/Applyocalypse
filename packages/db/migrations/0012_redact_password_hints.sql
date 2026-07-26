-- Scrub previously-persisted partial-plaintext hints for password-class secrets.
-- redacted_hint stored first3...last4 of the value, which for typical password
-- lengths exposes most of the password in plaintext SQLite.
UPDATE encrypted_secrets
SET redacted_hint = '[REDACTED]'
WHERE key_name IN ('application_password', 'gmail_otp_password');
