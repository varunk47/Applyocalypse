const SECRET_PATTERNS = [
  /sk-[a-zA-Z0-9_-]{16,}/g,
  /api[_-]?key["']?\s*[:=]\s*["'][^"']+["']/gi,
  /token["']?\s*[:=]\s*["'][^"']+["']/gi,
  /password["']?\s*[:=]\s*["'][^"']+["']/gi,
  /\b\d{6}\b/g
];

export const redactSensitiveText = (value: string): string =>
  SECRET_PATTERNS.reduce((current, pattern) => current.replace(pattern, "[REDACTED]"), value);

export const safeJson = (value: unknown): string => redactSensitiveText(JSON.stringify(value));
