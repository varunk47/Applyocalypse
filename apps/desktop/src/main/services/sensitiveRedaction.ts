export const redactSensitiveSupervisorText = (value: string, providerEnv: Record<string, string> = {}): string => {
  let redacted = value;
  for (const [key, secret] of Object.entries(providerEnv)) {
    if (secret.length >= 4) {
      redacted = redacted.split(secret).join("[REDACTED]");
      try {
        // Tracebacks from HTTP clients often carry the secret percent-encoded inside URLs.
        const encoded = encodeURIComponent(secret);
        if (encoded !== secret) {
          redacted = redacted.split(encoded).join("[REDACTED]");
        }
      } catch {
        // Lone surrogates cannot be percent-encoded; the literal pass above already ran.
      }
    }
    const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    redacted = redacted.replace(new RegExp(`(${escapedKey}\\s*[=:]\\s*)[^\\s;]+`, "gi"), "$1[REDACTED]");
  }
  return redacted.replace(/\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|OTP|AUTHORIZATION)[A-Z0-9_]*\s*[=:]\s*)[^\s;]+/gi, "$1[REDACTED]");
};
