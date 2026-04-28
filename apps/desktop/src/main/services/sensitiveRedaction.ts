export const redactSensitiveSupervisorText = (value: string, providerEnv: Record<string, string> = {}): string => {
  let redacted = value;
  for (const [key, secret] of Object.entries(providerEnv)) {
    if (secret.length >= 4) {
      redacted = redacted.split(secret).join("[REDACTED]");
    }
    redacted = redacted.replace(new RegExp(`(${key}\\s*[=:]\\s*)[^\\s,;]+`, "gi"), "$1[REDACTED]");
  }
  return redacted.replace(/\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|OTP|AUTHORIZATION)[A-Z0-9_]*\s*[=:]\s*)[^\s,;]+/gi, "$1[REDACTED]");
};
