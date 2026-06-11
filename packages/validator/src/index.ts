export type ValidationSeverity = "blocking" | "warning";

export type ValidationIssue = {
  severity: ValidationSeverity;
  code: string;
  message: string;
  location?: string;
};

export type ValidationReport = {
  passed: boolean;
  blockingIssues: ValidationIssue[];
  warnings: ValidationIssue[];
};

export const BANNED_WORDS = [
  "leverage",
  "utilize",
  "spearheaded",
  "robust",
  "comprehensive",
  "seamless",
  "transformative",
  "passionate",
  "excited",
  "thrilled",
  "dynamic",
  "innovative",
  "holistic",
  "empower",
  "foster",
  "harness",
  "deep dive"
] as const;

const EM_DASH = "\u2014";
const WEAK_BULLET_PATTERNS = [
  /\bresponsible for\b/i,
  /\bworked on\b/i,
  /\bhelped with\b/i,
  /\bparticipated in\b/i,
  /\bvarious\b/i
] as const;

const REQUIRED_RESUME_SECTION_PATTERNS = [
  /\bexperience\b/i,
  /\bskills?\b/i
] as const;

const COVER_LETTER_SIGN_OFF = /\b(sincerely|best regards|regards|thank you)\b/i;

export type ValidateTextOptions = {
  artifactKind: "resume" | "cover_letter" | "generic";
  maxCoverLetterWords?: number;
  bulletCharLimit?: number;
};

const countWords = (value: string): number => value.trim().split(/\s+/).filter(Boolean).length;

export const validateTextArtifact = (content: string, options: ValidateTextOptions): ValidationReport => {
  const lower = content.toLowerCase();
  const blockingIssues: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];

  for (const word of BANNED_WORDS) {
    const pattern = new RegExp(`\\b${word.replace(" ", "\\s+")}\\b`, "i");
    if (pattern.test(lower)) {
      blockingIssues.push({
        severity: "blocking",
        code: "BANNED_WORD",
        message: `Banned wording found: ${word}`
      });
    }
  }

  const emDashCount = content.split(EM_DASH).length - 1;
  if (emDashCount > 0) {
    blockingIssues.push({
      severity: "blocking",
      code: "EM_DASH",
      message: `Em dash count must be 0. Found ${emDashCount}.`
    });
  }

  if (options.artifactKind === "cover_letter") {
    const wordCount = countWords(content);
    const maxWords = options.maxCoverLetterWords ?? 450;
    if (wordCount > maxWords) {
      blockingIssues.push({
        severity: "blocking",
        code: "COVER_LETTER_TOO_LONG",
        message: `Cover letter has ${wordCount} words. Maximum is ${maxWords}.`
      });
    }

    if (/^(i am applying for|i'?m writing to apply|i am writing to apply)\b/i.test(content.trim())) {
      warnings.push({
        severity: "warning",
        code: "GENERIC_OPENER",
        message: "Cover letter starts with a generic opener."
      });
    }

    if (!COVER_LETTER_SIGN_OFF.test(content)) {
      warnings.push({
        severity: "warning",
        code: "MISSING_SIGN_OFF",
        message: "Cover letter should include a human sign-off."
      });
    }
  }

  if (options.artifactKind === "resume") {
    const charLimit = options.bulletCharLimit ?? 240;
    const bullets = content.split(/\r?\n/).filter((line) => /^\s*[-*]\s+/.test(line));
    for (const [index, bullet] of bullets.entries()) {
      if (countWords(bullet) > 32) {
        warnings.push({
          severity: "warning",
          code: "LONG_BULLET",
          message: "Resume bullet is longer than the target length.",
          location: `bullet:${index + 1}`
        });
      }
      const bulletText = bullet.replace(/^\s*[-*]\s+/, "");
      if (bulletText.length > charLimit) {
        warnings.push({
          severity: "warning",
          code: "BULLET_TOO_LONG",
          message: `Resume bullet exceeds ${charLimit} characters (${bulletText.length} chars).`,
          location: `bullet:${index + 1}`
        });
      }
      if (WEAK_BULLET_PATTERNS.some((pattern) => pattern.test(bullet))) {
        warnings.push({
          severity: "warning",
          code: "WEAK_BULLET",
          message: "Resume bullet uses weak or vague phrasing.",
          location: `bullet:${index + 1}`
        });
      }
    }

    for (const pattern of REQUIRED_RESUME_SECTION_PATTERNS) {
      if (!pattern.test(content)) {
        warnings.push({
          severity: "warning",
          code: "RESUME_MISSING_SECTION",
          message: "Resume may be missing an expected section."
        });
      }
    }

    const bulletStarts = bullets
      .map((bullet) => bullet.replace(/^\s*[-*]\s+/, "").trim().split(/\s+/)[0]?.toLowerCase())
      .filter((word): word is string => Boolean(word));
    const startCounts = new Map<string, number>();
    for (const word of bulletStarts) {
      startCounts.set(word, (startCounts.get(word) ?? 0) + 1);
    }
    if ([...startCounts.values()].some((count) => count >= 3)) {
      warnings.push({
        severity: "warning",
        code: "REPETITIVE_RHYTHM",
        message: "Multiple bullets start with the same word."
      });
    }
  }

  return {
    passed: blockingIssues.length === 0,
    blockingIssues,
    warnings
  };
};
