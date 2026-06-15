import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  ChatRepository,
  JobRepository,
  ProfileRepository,
  ProviderRepository,
  QueueRepository,
  RunRepository,
  SettingsRepository,
  UploadRepository,
  ParsedDocumentRepository,
  AuditRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "../index";
import { EqualEmploymentDefaultsSchema, EQUAL_EMPLOYMENT_SEED_DEFAULTS } from "@applyocalypse/shared-schemas";

const tempDirs: string[] = [];

const createDb = (): { db: ApplyocalypseDatabase; dir: string } => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-db-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  return { db, dir };
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("db repositories", () => {
  it("persists theme settings", () => {
    const { db } = createDb();
    try {
      const settings = new SettingsRepository(db);
      settings.setThemePreference("dark");
      expect(settings.getThemePreference()).toBe("dark");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("creates a profile and queues job targets transactionally", () => {
    const { db } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const jobRepository = new JobRepository(db);
      const queueRepository = new QueueRepository(db);

      const profile = profileRepository.createStarterProfile({
        legalName: "Grace Hopper",
        email: "grace@example.com",
        location: "Arlington, VA"
      });

      const enqueued = jobRepository.enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "URL", sourceValue: "https://example.com/jobs/1", autoSubmitEnabled: true }]
      });

      expect(enqueued.jobTargets).toHaveLength(1);
      expect(enqueued.queueItems[0]?.autoSubmitEnabled).toBe(true);
      expect(queueRepository.count()).toBe(1);
      const claimed = queueRepository.claimNext("worker-a", 30_000, 2);
      expect(claimed?.status).toBe("CLAIMED");
      expect(claimed?.autoSubmitEnabled).toBe(true);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("counts review-gated claimed queue items against the local concurrency cap", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Sally Ride" });
      const { queueItems } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [
          { sourceKind: "TEXT", sourceValue: "Role requiring Python" },
          { sourceKind: "TEXT", sourceValue: "Role requiring TypeScript" }
        ]
      });
      const futureLease = new Date(Date.now() + 600_000).toISOString();
      db.prepare(
        `
        UPDATE queue_items
        SET status = 'READY_TO_SUBMIT',
            claimed_by = 'worker-a',
            heartbeat_at = @futureLease,
            lease_expires_at = @futureLease
        WHERE id = @queueItemId
      `
      ).run({ futureLease, queueItemId: queueItems[0]!.id });

      expect(new QueueRepository(db).claimNext("worker-a", 30_000, 1)).toBeNull();
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("fails pending queue items that exhausted their retry budget before claiming more work", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Mae Jemison" });
      const { queueItems } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "TEXT", sourceValue: "Role requiring Python" }]
      });
      db.prepare("UPDATE queue_items SET attempts = max_attempts WHERE id = ?").run(queueItems[0]!.id);

      expect(new QueueRepository(db).claimNext("worker-a", 30_000, 2)).toBeNull();
      expect(new QueueRepository(db).getById(queueItems[0]!.id).status).toBe("FAILED");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("registers upload metadata without storing file bytes", () => {
    const { db, dir } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Katherine Johnson" });
      const resumePath = join(dir, "resume.tex");
      writeFileSync(resumePath, "\\section{Experience}", "utf8");

      const uploaded = new UploadRepository(db).registerLocalFile({
        profileId: profile.id,
        localPath: resumePath,
        fileKind: "RESUME"
      });

      expect(uploaded.sourceFormat).toBe("TEX");
      expect(uploaded.sizeBytes).toBeGreaterThan(0);
      expect(uploaded.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(Object.keys(uploaded)).not.toContain("bytes");
      expect(new UploadRepository(db).list(profile.id)[0]?.id).toBe(uploaded.id);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists parsed document output and conservatively merges high-confidence profile facts", () => {
    const { db, dir } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const profile = profileRepository.createStarterProfile({ legalName: "Ada Lovelace" });
      const resumePath = join(dir, "resume.tex");
      writeFileSync(resumePath, "\\section{Skills}\nPython, TypeScript, SQLite", "utf8");
      const uploaded = new UploadRepository(db).registerLocalFile({
        profileId: profile.id,
        localPath: resumePath,
        fileKind: "RESUME"
      });

      const merge = new ParsedDocumentRepository(db).createAndMerge({
        uploadedFileId: uploaded.id,
        parserName: "applyocalypse-local-parser",
        parserVersion: "0.3.0",
        confidence: 0.84,
        canonical: {
          documentKind: "RESUME",
          sourceFormat: "TEX",
          identity: {
            legalName: "Ada Lovelace",
            email: "ada@example.com",
            phone: null,
            location: null,
            links: []
          },
          sections: [
            {
              sectionId: "section:skills:0",
              label: "Skills",
              normalizedLabel: "skills",
              startLine: 0,
              endLine: 1,
              confidence: 0.86,
              items: ["Python, TypeScript, SQLite"]
            }
          ],
          skillGroups: [{ label: "Skills", skills: ["Python", "TypeScript", "SQLite"], confidence: 0.82 }],
          education: [
            {
              institution: "University of London",
              degree: "Mathematics",
              field: "Analytical Engines",
              startDate: null,
              endDate: null,
              details: ["Coursework in symbolic computation"],
              confidence: 0.82
            }
          ],
          experience: [
            {
              company: "Babbage Lab",
              title: "Computing Collaborator",
              location: "London",
              startDate: "1842",
              endDate: "1843",
              bullets: ["Translated and annotated algorithms for mechanical computation"],
              tools: ["Algorithms", "Mathematics"],
              confidence: 0.86
            }
          ],
          projects: [
            {
              name: "Analytical Engine Notes",
              role: "Author",
              summary: "Documented program logic for mechanical computation",
              bullets: ["Outlined a repeatable method for Bernoulli number calculation"],
              tools: ["Algorithms"],
              links: [],
              confidence: 0.88
            }
          ],
          certifications: [
            {
              name: "Mathematical Correspondence",
              issuer: "Royal Society",
              issuedAt: "1843",
              expiresAt: null,
              credentialUrl: null,
              confidence: 0.79
            }
          ],
          rawTextPreview: "Skills\nPython, TypeScript, SQLite"
        },
        styleMap: {},
        anchorMap: { regions: [] },
        warnings: []
      });

      const canonical = profileRepository.getCanonicalProfile(profile.id);

      expect(merge.updatedProfile?.email).toBe("ada@example.com");
      expect(merge.applied).toContain("profile.email");
      expect(merge.applied).toContain("experience:Babbage Lab:Computing Collaborator");
      expect(merge.applied).toContain("project:Analytical Engine Notes");
      expect(canonical?.skillGroups[0]?.skills).toEqual(["Python", "TypeScript", "SQLite"]);
      expect(canonical?.experience[0]?.company).toBe("Babbage Lab");
      expect(canonical?.projects[0]?.name).toBe("Analytical Engine Notes");
      expect(canonical?.education[0]?.institution).toBe("University of London");
      expect(canonical?.certifications[0]?.issuer).toBe("Royal Society");
      expect(new ParsedDocumentRepository(db).list({ profileId: profile.id })).toHaveLength(1);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("stores provider metadata without exposing secret material in connections", () => {
    const { db } = createDb();
    try {
      const providers = new ProviderRepository(db);
      const secretRefId = providers.createEncryptedSecretReference({
        provider: "openai",
        keyName: "api_key",
        encryptedReference: "encrypted-reference",
        redactedHint: "sk-...1234"
      });

      const connection = providers.upsertConnection({
        provider: "openai",
        displayName: "OpenAI",
        status: "CONNECTED",
        secretRefId,
        metadata: { defaultModel: "gpt-4.1" }
      });

      expect(connection.secretRefId).toBe(secretRefId);
      expect(connection.metadata.defaultModel).toBe("gpt-4.1");
      expect(JSON.stringify(connection)).not.toContain("encrypted-reference");
      expect(providers.getFirstConnectedSecretReference()?.encryptedReference).toBe("encrypted-reference");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("keeps Gmail OTP connections out of the LLM provider runtime selector", () => {
    const { db } = createDb();
    try {
      const providers = new ProviderRepository(db);
      const gmailSecretRefId = providers.createEncryptedSecretReference({
        provider: "gmail",
        keyName: "gmail_otp_password",
        encryptedReference: "gmail-encrypted-reference",
        redactedHint: "gm...1234"
      });
      providers.upsertConnection({
        provider: "gmail",
        displayName: "Gmail OTP",
        status: "CONNECTED",
        secretRefId: gmailSecretRefId,
        metadata: { email: "ada@gmail.com" }
      });

      expect(providers.getFirstConnectedSecretReference()).toBeNull();

      const openAiSecretRefId = providers.createEncryptedSecretReference({
        provider: "openai",
        keyName: "api_key",
        encryptedReference: "openai-encrypted-reference",
        redactedHint: "sk-...1234"
      });
      providers.upsertConnection({
        provider: "openai",
        displayName: "OpenAI",
        status: "CONNECTED",
        secretRefId: openAiSecretRefId,
        metadata: {}
      });

      expect(providers.getFirstConnectedSecretReference()?.provider).toBe("openai");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("stores profile application credential references without exposing the encrypted secret on the profile", () => {
    const { db } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const providers = new ProviderRepository(db);
      const profile = profileRepository.createStarterProfile({ legalName: "Ada Lovelace", email: "ada@example.com" });
      const secretRefId = providers.createEncryptedSecretReference({
        provider: "local",
        keyName: "application_password",
        encryptedReference: "encrypted-application-password",
        redactedHint: "St...12"
      });

      const updated = profileRepository.configureApplicationCredentials({
        profileId: profile.id,
        applicationEmail: "ada@gmail.com",
        passwordSecretRefId: secretRefId,
        otpHandlingEnabled: false
      });

      expect(updated.applicationEmail).toBe("ada@gmail.com");
      expect(updated.applicationPasswordConfigured).toBe(true);
      expect(JSON.stringify(updated)).not.toContain("encrypted-application-password");
      expect(profileRepository.getApplicationCredentialReference(profile.id)?.encryptedReference).toBe("encrypted-application-password");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("appends audit logs without requiring secret payloads", () => {
    const { db } = createDb();
    try {
      const auditId = new AuditRepository(db).append({
        action: "provider.api_key_saved",
        entityType: "provider_connection",
        entityId: "provider-1",
        metadata: { provider: "openai", secretRefId: "secret-1" }
      });
      const row = db.prepare("SELECT * FROM audit_logs WHERE id = ?").get(auditId) as { action: string; metadata_json: string };

      expect(row.action).toBe("provider.api_key_saved");
      expect(row.metadata_json).not.toContain("sk-");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists run control data, answers, approvals, and events", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Margaret Hamilton" });
      const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "TEXT", sourceValue: "Principal engineer role requiring TypeScript" }]
      });
      const runs = new RunRepository(db);
      const run = runs.createApplicationRun({
        queueItemId: queueItems[0]!.id,
        profileId: profile.id,
        jobTargetId: jobTargets[0]!.id,
        autoSubmitEnabled: false
      });
      const step = runs.addStep({
        applicationRunId: run.id,
        stepOrder: 0,
        stepType: "FIELD_REVIEW",
        expectedState: { gate: "before_fill" }
      });
      const answer = runs.upsertAnswer({
        applicationRunId: run.id,
        stepId: step.id,
        fieldLabel: "Work authorization",
        fieldType: "radio",
        proposedValue: null,
        userValue: "Needs user confirmation",
        source: "USER_EDIT",
        confidence: 1,
        status: "EDITED"
      });
      const review = runs.createReviewRequest({
        applicationRunId: run.id,
        stepId: step.id,
        reviewType: "FINAL_SUBMIT",
        prompt: "Approve final submission?"
      });
      const approval = runs.recordApprovalDecision({
        applicationRunId: run.id,
        approvalType: "FINAL_SUBMIT",
        status: "APPROVED"
      });
      runs.addRunEvent({
        eventType: "USER_REVIEW_REQUIRED",
        runId: run.id,
        stepId: step.id,
        timestamp: new Date().toISOString(),
        severity: "WARN",
        message: "Final submit approval required",
        machineState: {},
        uiState: { modal: "approval" },
        payload: {}
      });

      expect(answer.status).toBe("EDITED");
      expect(answer.applyMetadata).toEqual({});
      expect(approval.status).toBe("APPROVED");
      expect(approval.reviewRequestId).toBe(review.id);
      expect(runs.listReviewRequests(run.id)[0]!.status).toBe("APPROVED");
      expect(runs.listRunEvents(run.id)).toHaveLength(1);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("approves and rejects pending answers as explicit review decisions", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Grace Hopper" });
      const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "URL", sourceValue: "https://example.com/job" }]
      });
      const runs = new RunRepository(db);
      const run = runs.createApplicationRun({
        queueItemId: queueItems[0]!.id,
        profileId: profile.id,
        jobTargetId: jobTargets[0]!.id
      });
      runs.upsertAnswer({
        applicationRunId: run.id,
        fieldLabel: "Email address",
        fieldType: "email",
        proposedValue: "grace@example.com",
        source: "PROFILE",
        confidence: 0.98,
        status: "PROPOSED"
      });
      runs.upsertAnswer({
        applicationRunId: run.id,
        fieldLabel: "Work authorization",
        fieldType: "radio",
        proposedValue: "Yes",
        userValue: "Yes",
        source: "USER_EDIT",
        confidence: 1,
        status: "EDITED"
      });

      expect(runs.approvePendingAnswers(run.id)).toBe(2);
      expect(runs.listAnswers(run.id).map((item) => item.status)).toEqual(["APPROVED", "APPROVED"]);
      expect(runs.rejectPendingAnswers(run.id)).toBe(2);
      expect(runs.listAnswers(run.id).map((item) => item.status)).toEqual(["REJECTED", "REJECTED"]);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("recovers stale active runs by pausing them for user inspection", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Dorothy Vaughan" });
      const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "URL", sourceValue: "https://example.com/job" }]
      });
      const run = new RunRepository(db).createApplicationRun({
        queueItemId: queueItems[0]!.id,
        profileId: profile.id,
        jobTargetId: jobTargets[0]!.id
      });
      db.prepare("UPDATE application_runs SET status = 'RUNNING_AUTOMATION', lease_expires_at = '2020-01-01T00:00:00.000Z' WHERE id = ?").run(run.id);
      db.prepare(
        "UPDATE queue_items SET status = 'RUNNING_AUTOMATION', claimed_by = 'worker-a', lease_expires_at = '2020-01-01T00:00:00.000Z', heartbeat_at = '2020-01-01T00:00:00.000Z' WHERE id = ?"
      ).run(queueItems[0]!.id);

      const recovered = new RunRepository(db).recoverStaleRuns("2026-01-01T00:00:00.000Z");
      const updated = new RunRepository(db).getApplicationRun(run.id);
      const queueItem = new QueueRepository(db).getById(queueItems[0]!.id);

      expect(recovered).toBe(1);
      expect(updated.status).toBe("PAUSED");
      expect(updated.failureCode).toBe("STALE_WORKER_RECOVERED");
      expect(queueItem.status).toBe("PAUSED");
      expect(queueItem.claimedBy).toBeNull();
      expect(queueItem.leaseExpiresAt).toBeNull();
      expect(queueItem.heartbeatAt).toBeNull();
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("recovers stale review-gated runs whose workers disappeared during app restart", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Annie Easley" });
      const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "URL", sourceValue: "https://example.com/job" }]
      });
      const run = new RunRepository(db).createApplicationRun({
        queueItemId: queueItems[0]!.id,
        profileId: profile.id,
        jobTargetId: jobTargets[0]!.id
      });
      db.prepare("UPDATE application_runs SET status = 'READY_TO_SUBMIT', lease_expires_at = '2020-01-01T00:00:00.000Z' WHERE id = ?").run(run.id);
      db.prepare(
        "UPDATE queue_items SET status = 'READY_TO_SUBMIT', claimed_by = 'worker-a', lease_expires_at = '2020-01-01T00:00:00.000Z', heartbeat_at = '2020-01-01T00:00:00.000Z' WHERE id = ?"
      ).run(queueItems[0]!.id);

      const recovered = new RunRepository(db).recoverStaleRuns("2026-01-01T00:00:00.000Z");
      const updated = new RunRepository(db).getApplicationRun(run.id);
      const queueItem = new QueueRepository(db).getById(queueItems[0]!.id);

      expect(recovered).toBe(1);
      expect(updated.status).toBe("PAUSED");
      expect(updated.failureCode).toBe("STALE_WORKER_RECOVERED");
      expect(queueItem.status).toBe("PAUSED");
      expect(queueItem.claimedBy).toBeNull();
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("replaceStructuredSections round-trips education, experience, projects, and skillGroups", () => {
    const { db } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const profile = profileRepository.createStarterProfile({ legalName: "Round Trip" });

      profileRepository.replaceStructuredSections(profile.id, {
        education: [{ institution: "MIT", degree: "BS", field: "CS", startDate: "2018-09", endDate: "2022-05" }],
        experience: [{ company: "Acme", title: "Engineer", bullets: ["Built things"] }],
        projects: [{ name: "MyProject", summary: "A project", bullets: ["Feature A"], tools: ["TypeScript"] }],
        skillGroups: [{ label: "Languages", skills: ["TypeScript", "Python"] }]
      });

      const canonical = profileRepository.getCanonicalProfile(profile.id);
      expect(canonical).not.toBeNull();
      expect(canonical!.education[0]?.institution).toBe("MIT");
      expect(canonical!.experience[0]?.company).toBe("Acme");
      expect(canonical!.experience[0]?.bullets).toEqual(["Built things"]);
      expect(canonical!.projects[0]?.name).toBe("MyProject");
      expect(canonical!.skillGroups[0]?.skills).toEqual(["TypeScript", "Python"]);

      // Replace again — old entries must be gone
      profileRepository.replaceStructuredSections(profile.id, {
        education: [],
        experience: [{ company: "NewCo", title: "Senior Engineer" }],
        projects: [],
        skillGroups: []
      });

      const updated = profileRepository.getCanonicalProfile(profile.id);
      expect(updated!.education).toHaveLength(0);
      expect(updated!.experience).toHaveLength(1);
      expect(updated!.experience[0]?.company).toBe("NewCo");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists gpa on education entries through replaceStructuredSections", () => {
    const { db } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const profile = profileRepository.createStarterProfile({ legalName: "Test GPA" });

      profileRepository.replaceStructuredSections(profile.id, {
        education: [{ institution: "Stanford", degree: "BS", field: "CS", gpa: "3.9/4.0", startDate: "2018-09", endDate: "2022-05" }],
        experience: [],
        projects: [],
        skillGroups: []
      });

      const canonical = profileRepository.getCanonicalProfile(profile.id);
      expect(canonical!.education[0]?.gpa).toBe("3.9/4.0");

      profileRepository.replaceStructuredSections(profile.id, {
        education: [{ institution: "Stanford", degree: "BS", field: "CS", startDate: "2018-09", endDate: "2022-05" }],
        experience: [],
        projects: [],
        skillGroups: []
      });

      const updated = profileRepository.getCanonicalProfile(profile.id);
      expect(updated!.education[0]?.gpa).toBeNull();
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("EqualEmploymentDefaultsSchema parses seed defaults and rejects invalid values", () => {
    const parsed = EqualEmploymentDefaultsSchema.parse(EQUAL_EMPLOYMENT_SEED_DEFAULTS);
    expect(parsed.authorizedToWorkUS).toBe("Yes");
    expect(parsed.requiresSponsorship).toBe("Yes");
    expect(parsed.disability).toBe("No");
    expect(parsed.gender).toBe("Male");
    expect(parsed.race).toBe("Asian");
    expect(parsed.sexualOrientation).toEqual(["Heterosexual"]);
    expect(parsed.previouslyEmployedDefault).toBe("No");
    expect(parsed.criminalRecordDefault).toBe("No");

    expect(() => EqualEmploymentDefaultsSchema.parse({ authorizedToWorkUS: "Maybe" })).toThrow();
  });

  it("persists equalEmploymentDefaults through profileRepository.upsert round-trip", () => {
    const { db } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const profile = profileRepository.createStarterProfile({ legalName: "EEO Test" });
      const updated = profileRepository.upsert({ ...profile, equalEmploymentDefaults: EQUAL_EMPLOYMENT_SEED_DEFAULTS });
      const canonical = profileRepository.getCanonicalProfile(updated.id);

      const eeo = canonical!.profile.equalEmploymentDefaults as typeof EQUAL_EMPLOYMENT_SEED_DEFAULTS;
      expect(eeo.authorizedToWorkUS).toBe("Yes");
      expect(eeo.disability).toBe("No");
      expect(eeo.sponsorshipDetailText).toContain("F-1 OPT");
      expect(eeo.sexualOrientation).toEqual(["Heterosexual"]);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists workAuthorization through createStarter + upsert", () => {
    const { db } = createDb();
    try {
      const profileRepository = new ProfileRepository(db);
      const profile = profileRepository.createStarterProfile({ legalName: "Test User" });
      const workAuth = { summary: "F-1 OPT, no sponsorship needed", sponsorshipRequired: false };
      const updated = profileRepository.upsert({ ...profile, workAuthorization: workAuth });
      const canonical = profileRepository.getCanonicalProfile(updated.id);

      expect(canonical).not.toBeNull();
      expect((canonical!.profile.workAuthorization as typeof workAuth).summary).toBe(workAuth.summary);
      expect((canonical!.profile.workAuthorization as typeof workAuth).sponsorshipRequired).toBe(false);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("chat: appendMessage persists and list returns messages in order", () => {
    const { db } = createDb();
    try {
      const chat = new ChatRepository(db);

      const msg1 = chat.appendMessage({ role: "USER", kind: "TEXT", content: "Hello" });
      chat.appendMessage({ role: "SYSTEM", kind: "TEXT", content: "Acknowledged" });
      const msg3 = chat.appendMessage({
        role: "SYSTEM",
        kind: "JOB_CARD",
        content: "",
        metadata: { sourceKind: "URL", sourceValue: "https://example.com/job" }
      });

      expect(msg1.id).toBeTruthy();
      expect(msg1.role).toBe("USER");
      expect(msg1.kind).toBe("TEXT");
      expect(msg1.content).toBe("Hello");
      expect(msg1.batchId).toBeNull();
      expect(msg1.runId).toBeNull();
      expect(msg1.metadata).toEqual({});

      expect(msg3.kind).toBe("JOB_CARD");
      expect(msg3.metadata).toEqual({ sourceKind: "URL", sourceValue: "https://example.com/job" });

      const { items, total } = chat.list();
      expect(total).toBe(3);
      expect(items).toHaveLength(3);
      expect(items[0]!.content).toBe("Hello");
      expect(items[1]!.content).toBe("Acknowledged");
      expect(items[2]!.kind).toBe("JOB_CARD");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("chat: list respects limit and offset", () => {
    const { db } = createDb();
    try {
      const chat = new ChatRepository(db);
      for (let i = 0; i < 5; i++) {
        chat.appendMessage({ role: "USER", kind: "TEXT", content: `msg-${i}` });
      }

      const page1 = chat.list(2, 0);
      expect(page1.items).toHaveLength(2);
      expect(page1.total).toBe(5);
      expect(page1.items[0]!.content).toBe("msg-0");

      const page2 = chat.list(2, 2);
      expect(page2.items[0]!.content).toBe("msg-2");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });
});
