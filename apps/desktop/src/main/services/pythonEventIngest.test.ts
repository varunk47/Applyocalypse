import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  JobRepository,
  ProfileRepository,
  RunRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "@applyocalypse/db";
import { ingestPythonEventLine } from "./pythonEventIngest";

const tempDirs: string[] = [];

const createRun = (): { db: ApplyocalypseDatabase; runId: string } => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-ingest-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Mary Jackson" });
  const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
    profileId: profile.id,
    items: [{ sourceKind: "TEXT", sourceValue: "Required: Python" }]
  });
  const run = new RunRepository(db).createApplicationRun({
    queueItemId: queueItems[0]!.id,
    profileId: profile.id,
    jobTargetId: jobTargets[0]!.id
  });
  return { db, runId: run.id };
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("python event ingest", () => {
  it("updates run state and creates review requests from worker events", () => {
    const { db, runId } = createRun();
    try {
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "USER_REVIEW_REQUIRED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "WARN",
          message: "Review tailoring plan",
          machine_state: { gate: "TAILORING_PLAN_REVIEW" },
          ui_state: { requires_user_review: true },
          payload: { cover_letter_required: true }
        })
      });

      const runs = new RunRepository(db);
      expect(runs.getApplicationRun(runId).status).toBe("READY_FOR_REVIEW");
      expect(runs.getApplicationRun(runId).currentStepId).not.toBeNull();
      expect(runs.listSteps(runId)[0]?.status).toBe("WAITING_FOR_USER");
      expect(runs.listSteps(runId)[0]?.stepType).toBe("USER_REVIEW");
      expect(runs.listReviewRequests(runId)).toHaveLength(1);
      expect(runs.listRunEvents(runId)).toHaveLength(1);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("records explicit auto-submit approval without opening a final-submit review request", () => {
    const { db, runId } = createRun();
    try {
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "READY_TO_SUBMIT",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Final submission is preapproved by the explicit auto-submit setting",
          machine_state: { gate: "FINAL_SUBMIT", auto_submit_enabled: true },
          ui_state: { requires_user_review: false },
          payload: { auto_submit_enabled: true }
        })
      });

      const runs = new RunRepository(db);
      const approval = db.prepare("SELECT approval_type, status FROM approvals WHERE application_run_id = ?").get(runId) as {
        approval_type: string;
        status: string;
      };
      expect(runs.getApplicationRun(runId).status).toBe("READY_TO_SUBMIT");
      expect(runs.listReviewRequests(runId)).toHaveLength(0);
      expect(approval.approval_type).toBe("AUTO_SUBMIT");
      expect(approval.status).toBe("APPROVED");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists tailoring plan artifacts and links them to the run", () => {
    const { db, runId } = createRun();
    try {
      const planPath = join(tempDirs.at(-1)!, "tailoring-plan.json");
      writeFileSync(
        planPath,
        JSON.stringify({ matched_evidence: [{ keyword: "python" }], missing_keywords: [], risky_claims_to_avoid: [] }),
        "utf8"
      );

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "USER_REVIEW_REQUIRED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "WARN",
          message: "Review truthful tailoring plan before document mutation",
          machine_state: { gate: "TAILORING_PLAN_REVIEW" },
          ui_state: { requires_user_review: true },
          payload: { tailoring_plan_path: planPath, cover_letter_required: false }
        })
      });

      const run = new RunRepository(db).getApplicationRun(runId);
      const tailoringCount = db.prepare("SELECT COUNT(*) AS count FROM tailoring_runs").get() as { count: number };
      expect(run.tailoringRunId).not.toBeNull();
      expect(tailoringCount.count).toBe(1);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists generated file metadata without storing file bytes", () => {
    const { db, runId } = createRun();
    try {
      const artifactPath = join(tempDirs.at(-1)!, "Mary Jackson Example Resume.md");
      writeFileSync(artifactPath, "# Mary Jackson\n\n## Skills\nPython\n", "utf8");

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "RESUME_RENDERED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Resume review artifact rendered",
          machine_state: { format: "MD", review_only: true },
          ui_state: { current_step: "document_review" },
          payload: {
            file_kind: "RESUME",
            format: "MD",
            filename: "Mary Jackson Example Resume.md",
            local_path: artifactPath,
            sha256: "a".repeat(64),
            size_bytes: 32,
            retention_policy: "DELETE_AFTER_RETENTION",
            delete_after: "2026-01-15T00:00:00.000Z",
            review_only: true
          }
        })
      });

      const files = new RunRepository(db).listGeneratedFiles(runId);
      const row = db.prepare("SELECT * FROM generated_files WHERE id = ?").get(files[0]!.id) as Record<string, unknown>;
      expect(files).toHaveLength(1);
      expect(files[0]?.format).toBe("MD");
      expect(row).not.toHaveProperty("bytes");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("marks generated files as uploaded from browser upload events", () => {
    const { db, runId } = createRun();
    try {
      const artifactPath = join(tempDirs.at(-1)!, "Mary Jackson Example Resume.pdf");
      writeFileSync(artifactPath, "%PDF-1.7", "utf8");
      const runs = new RunRepository(db);

      ingestPythonEventLine({
        db,
        windows: () => [],
        safeArtifactRoots: [tempDirs.at(-1)!],
        rawLine: JSON.stringify({
          event_type: "RESUME_RENDERED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Resume PDF rendered",
          machine_state: { format: "PDF" },
          ui_state: { current_step: "document_review" },
          payload: {
            file_kind: "RESUME",
            format: "PDF",
            filename: "Mary Jackson Example Resume.pdf",
            local_path: artifactPath,
            sha256: "d".repeat(64),
            size_bytes: 8,
            retention_policy: "DELETE_AFTER_RETENTION",
            delete_after: "2026-01-15T00:00:00.000Z",
            review_only: false
          }
        })
      });

      const file = runs.listGeneratedFiles(runId)[0]!;
      ingestPythonEventLine({
        db,
        windows: () => [],
        safeArtifactRoots: [tempDirs.at(-1)!],
        rawLine: JSON.stringify({
          event_type: "FILE_UPLOADED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:05:00.000Z",
          severity: "INFO",
          message: "Uploaded reviewed document to Resume",
          machine_state: { selector: "#resume" },
          ui_state: { current_step: "file_upload" },
          payload: {
            generated_file_id: file.id,
            file_kind: "RESUME",
            format: "PDF",
            filename: file.filename,
            local_path: artifactPath,
            field_label: "Resume",
            field_type: "file",
            selector: "#resume"
          }
        })
      });

      const uploadedFile = runs.listGeneratedFiles(runId)[0]!;
      expect(uploadedFile.uploadStatus).toBe("UPLOADED");
      expect(uploadedFile.uploadedAt).toBe("2026-01-01T00:05:00.000Z");
      expect(runs.getApplicationRun(runId).status).toBe("RUNNING_AUTOMATION");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("rejects generated artifact paths outside configured safe roots", () => {
    const { db, runId } = createRun();
    try {
      const artifactPath = join(tempDirs.at(-1)!, "outside.md");
      writeFileSync(artifactPath, "# Outside\n", "utf8");

      expect(() =>
        ingestPythonEventLine({
          db,
          windows: () => [],
          safeArtifactRoots: [join(tempDirs.at(-1)!, "allowed")],
          rawLine: JSON.stringify({
            event_type: "RESUME_RENDERED",
            run_id: runId,
            step_id: null,
            timestamp: "2026-01-01T00:00:00.000Z",
            severity: "INFO",
            message: "Resume rendered outside roots",
            machine_state: {},
            ui_state: {},
            payload: {
              file_kind: "RESUME",
              format: "MD",
              filename: "outside.md",
              local_path: artifactPath,
              sha256: "c".repeat(64),
              size_bytes: 10,
              retention_policy: "DELETE_AFTER_RETENTION",
              delete_after: null,
              review_only: true
            }
          })
        })
      ).toThrow(/outside Applyocalypse artifact roots/);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists browser artifacts as local metadata references", () => {
    const { db, runId } = createRun();
    try {
      const artifactPath = join(tempDirs.at(-1)!, "dom-snapshot.json");
      writeFileSync(artifactPath, JSON.stringify({ title: "Application", fields: [] }), "utf8");

      ingestPythonEventLine({
        db,
        windows: () => [],
        safeArtifactRoots: [tempDirs.at(-1)!],
        rawLine: JSON.stringify({
          event_type: "BROWSER_ARTIFACT_CAPTURED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "DOM snapshot captured",
          machine_state: { artifact_type: "DOM_SNAPSHOT" },
          ui_state: { current_step: "page_review" },
          payload: {
            artifact_id: "artifact-dom-1",
            artifact_type: "DOM_SNAPSHOT",
            local_path: artifactPath,
            mime_type: "application/json",
            metadata: { field_count: 0 },
            captured_at: "2026-01-01T00:00:00.000Z"
          }
        })
      });

      const row = db.prepare("SELECT artifact_type, local_path, metadata_json FROM browser_artifacts").get() as {
        artifact_type: string;
        local_path: string;
        metadata_json: string;
      };
      expect(row.artifact_type).toBe("DOM_SNAPSHOT");
      expect(row.local_path).toBe(artifactPath);
      expect(row.metadata_json).toContain("field_count");
      expect(new RunRepository(db).getApplicationRun(runId).status).toBe("RUNNING_AUTOMATION");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists screenshot metadata only after validating the local artifact file", () => {
    const { db, runId } = createRun();
    try {
      const screenshotBytes = Buffer.from("fake-png");
      const screenshotPath = join(tempDirs.at(-1)!, "browser-step.png");
      const sha256 = createHash("sha256").update(screenshotBytes).digest("hex");
      writeFileSync(screenshotPath, screenshotBytes);

      ingestPythonEventLine({
        db,
        windows: () => [],
        safeArtifactRoots: [tempDirs.at(-1)!],
        rawLine: JSON.stringify({
          event_type: "SCREENSHOT_CAPTURED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Apply-phase screenshot captured",
          machine_state: { screenshot_id: "reviewed-fields-applied-1" },
          ui_state: { current_step: "field_application" },
          payload: {
            screenshot_id: "reviewed-fields-applied-1",
            local_path: screenshotPath,
            mime_type: "image/png",
            width: 900,
            height: 700,
            sha256,
            captured_at: "2026-01-01T00:00:00.000Z"
          }
        })
      });

      const row = db.prepare("SELECT screenshot_id, local_path, sha256 FROM screenshots WHERE application_run_id = ?").get(runId) as {
        screenshot_id: string;
        local_path: string;
        sha256: string;
      };
      expect(row.screenshot_id).toBe("reviewed-fields-applied-1");
      expect(row.local_path).toBe(screenshotPath);
      expect(row.sha256).toBe(sha256);

      const updatedBytes = Buffer.from("fake-png-updated");
      const updatedScreenshotPath = join(tempDirs.at(-1)!, "browser-step-updated.png");
      const updatedSha256 = createHash("sha256").update(updatedBytes).digest("hex");
      writeFileSync(updatedScreenshotPath, updatedBytes);

      ingestPythonEventLine({
        db,
        windows: () => [],
        safeArtifactRoots: [tempDirs.at(-1)!],
        rawLine: JSON.stringify({
          event_type: "SCREENSHOT_CAPTURED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:01.000Z",
          severity: "INFO",
          message: "Apply-phase screenshot recaptured",
          machine_state: { screenshot_id: "reviewed-fields-applied-1" },
          ui_state: { current_step: "field_application" },
          payload: {
            screenshot_id: "reviewed-fields-applied-1",
            local_path: updatedScreenshotPath,
            mime_type: "image/png",
            width: 901,
            height: 701,
            sha256: updatedSha256,
            captured_at: "2026-01-01T00:00:01.000Z"
          }
        })
      });

      const rows = db.prepare("SELECT screenshot_id, local_path, sha256, width, height FROM screenshots WHERE application_run_id = ?").all(runId) as Array<{
        screenshot_id: string;
        local_path: string;
        sha256: string;
        width: number;
        height: number;
      }>;
      expect(rows).toHaveLength(1);
      expect(rows[0]?.local_path).toBe(updatedScreenshotPath);
      expect(rows[0]?.sha256).toBe(updatedSha256);
      expect(rows[0]?.width).toBe(901);
      expect(rows[0]?.height).toBe(701);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("rejects screenshot metadata when the emitted hash does not match the local file", () => {
    const { db, runId } = createRun();
    try {
      const screenshotPath = join(tempDirs.at(-1)!, "browser-step.png");
      writeFileSync(screenshotPath, Buffer.from("fake-png"));

      expect(() =>
        ingestPythonEventLine({
          db,
          windows: () => [],
          safeArtifactRoots: [tempDirs.at(-1)!],
          rawLine: JSON.stringify({
            event_type: "SCREENSHOT_CAPTURED",
            run_id: runId,
            step_id: null,
            timestamp: "2026-01-01T00:00:00.000Z",
            severity: "INFO",
            message: "Apply-phase screenshot captured",
            machine_state: { screenshot_id: "reviewed-fields-applied-1" },
            ui_state: { current_step: "field_application" },
            payload: {
              screenshot_id: "reviewed-fields-applied-1",
              local_path: screenshotPath,
              mime_type: "image/png",
              width: 900,
              height: 700,
              sha256: "0".repeat(64),
              captured_at: "2026-01-01T00:00:00.000Z"
            }
          })
        })
      ).toThrow(/sha256 does not match/);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("materializes portal workflow events into automation steps", () => {
    const { db, runId } = createRun();
    try {
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "PORTAL_WORKFLOW_SELECTED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Portal workflow selected: Greenhouse",
          machine_state: { portal_id: "greenhouse", workflow_kind: "ATS_DIRECT_FORM", adapter: "playwright" },
          ui_state: { current_step: "portal_workflow" },
          payload: {
            portal_id: "greenhouse",
            display_name: "Greenhouse",
            workflow_kind: "ATS_DIRECT_FORM",
            default_adapter: "playwright",
            adapter: "playwright",
            requires_high_stealth: false,
            requires_login_watch: false,
            requires_external_redirect_watch: false,
            requires_manual_review_before_fill: true,
            entry_action_labels: ["Apply for this job", "Apply now"],
            notes: ["Click only known apply/start actions."]
          }
        })
      });

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "PORTAL_ACTION_APPLIED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:05.000Z",
          severity: "INFO",
          message: "Greenhouse portal entry action applied",
          machine_state: { portal_id: "greenhouse", workflow_kind: "ATS_DIRECT_FORM", context: "observation" },
          ui_state: { current_step: "portal_workflow" },
          payload: {
            portal_id: "greenhouse",
            workflow_kind: "ATS_DIRECT_FORM",
            context: "observation",
            attempted_labels: ["Apply for this job", "Apply now"],
            clicked_label: "Apply for this job",
            clicked_tag: "button",
            href: null
          }
        })
      });

      const runs = new RunRepository(db);
      const steps = runs.listSteps(runId);
      expect(runs.getApplicationRun(runId).status).toBe("RUNNING_AUTOMATION");
      expect(steps).toHaveLength(1);
      expect(steps[0]?.stepType).toBe("PORTAL_WORKFLOW");
      expect(steps[0]?.status).toBe("COMPLETED");
      expect(JSON.stringify(steps[0]?.result)).toContain("clicked_label");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("maps blocker pause events to blocked run statuses and review requests", () => {
    const { db, runId } = createRun();
    try {
      const rawLine = JSON.stringify({
        event_type: "PAUSED",
        run_id: runId,
        step_id: null,
        timestamp: "2026-01-01T00:00:00.000Z",
        severity: "WARN",
        message: "CAPTCHA challenge detected",
        machine_state: { reason: "CAPTCHA_DETECTED" },
        ui_state: { requires_user_review: true },
        payload: { blockers: [{ blocker_type: "CAPTCHA", confidence: 0.92 }] }
      });

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine
      });
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine
      });

      const runs = new RunRepository(db);
      const reviewRequests = runs.listReviewRequests(runId);
      const auditRow = db.prepare("SELECT action, metadata_json FROM audit_logs WHERE entity_id = ?").get(runId) as
        | { action: string; metadata_json: string }
        | undefined;
      expect(runs.getApplicationRun(runId).status).toBe("BLOCKED_CAPTCHA");
      expect(reviewRequests).toHaveLength(1);
      expect(reviewRequests[0]?.reviewType).toBe("CAPTCHA");
      expect(reviewRequests[0]?.status).toBe("OPEN");
      expect(auditRow?.action).toBe("automation.blocked.captcha");
      expect(auditRow?.metadata_json).toContain("CAPTCHA_DETECTED");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("maps field review pauses to answer review requests without duplicates", () => {
    const { db, runId } = createRun();
    try {
      const rawLine = JSON.stringify({
        event_type: "PAUSED",
        run_id: runId,
        step_id: null,
        timestamp: "2026-01-01T00:00:00.000Z",
        severity: "WARN",
        message: "Browser automation paused because required application fields need reviewed answers",
        machine_state: { reason: "FIELD_REVIEW_REQUIRED", missing_answer_count: 1 },
        ui_state: { requires_user_review: true, current_step: "field_review" },
        payload: {
          missing_answers: [{ field_label: "Email address", field_type: "email", selector: "#email", required: true }]
        }
      });

      ingestPythonEventLine({ db, windows: () => [], rawLine });
      ingestPythonEventLine({ db, windows: () => [], rawLine });

      const runs = new RunRepository(db);
      const reviewRequests = runs.listReviewRequests(runId);
      expect(runs.getApplicationRun(runId).status).toBe("PAUSED");
      expect(reviewRequests).toHaveLength(1);
      expect(reviewRequests[0]?.reviewType).toBe("ANSWER");
      expect(reviewRequests[0]?.payload.reason).toBe("FIELD_REVIEW_REQUIRED");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("creates login review requests without claiming a blocked submit state", () => {
    const { db, runId } = createRun();
    try {
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "PAUSED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "WARN",
          message: "Login page detected",
          machine_state: { reason: "LOGIN_DETECTED" },
          ui_state: { requires_user_review: true },
          payload: { blockers: [{ blocker_type: "LOGIN", confidence: 0.9 }] }
        })
      });

      const runs = new RunRepository(db);
      const reviewRequests = runs.listReviewRequests(runId);
      expect(runs.getApplicationRun(runId).status).toBe("PAUSED");
      expect(reviewRequests).toHaveLength(1);
      expect(reviewRequests[0]?.reviewType).toBe("LOGIN");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("creates portal entry review requests for manual apply/start clicks", () => {
    const { db, runId } = createRun();
    try {
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "PAUSED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "WARN",
          message: "Lever requires a manual portal entry action before fields can be trusted.",
          machine_state: {
            reason: "PORTAL_ENTRY_ACTION_REQUIRED",
            portal_id: "lever",
            workflow_kind: "ATS_DIRECT_FORM"
          },
          ui_state: { requires_user_review: true, current_step: "portal_entry" },
          payload: {
            portal_id: "lever",
            attempted_labels: ["Apply for this job", "Apply now"],
            ambiguity_code: "AMBIGUOUS_PORTAL_ACTION",
            candidate_count: 2,
            candidate_labels: ["Apply for this job", "Apply now"]
          }
        })
      });

      const runs = new RunRepository(db);
      const reviewRequests = runs.listReviewRequests(runId);
      expect(runs.getApplicationRun(runId).status).toBe("PAUSED");
      expect(reviewRequests).toHaveLength(1);
      expect(reviewRequests[0]?.reviewType).toBe("PORTAL_ENTRY");
      expect(reviewRequests[0]?.payload.reason).toBe("PORTAL_ENTRY_ACTION_REQUIRED");
      expect(reviewRequests[0]?.payload.candidate_labels).toEqual(["Apply for this job", "Apply now"]);
      expect(reviewRequests[0]?.payload.ambiguity_code).toBe("AMBIGUOUS_PORTAL_ACTION");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("creates portal step review requests for ambiguous non-final progression actions", () => {
    const { db, runId } = createRun();
    try {
      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "PAUSED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "WARN",
          message: "Application step progression needs manual review before automation can continue.",
          machine_state: {
            reason: "PORTAL_STEP_ACTION_REQUIRED",
            portal_id: "workday",
            workflow_kind: "ATS_DIRECT_FORM"
          },
          ui_state: { requires_user_review: true, current_step: "portal_step" },
          payload: {
            portal_id: "workday",
            action_role: "STEP_PROGRESSION",
            attempted_labels: ["Next", "Continue", "Review application"],
            ambiguity_code: "AMBIGUOUS_PORTAL_ACTION",
            candidate_count: 2,
            candidate_labels: ["Continue", "Review application"]
          }
        })
      });

      const runs = new RunRepository(db);
      const reviewRequests = runs.listReviewRequests(runId);
      expect(runs.getApplicationRun(runId).status).toBe("PAUSED");
      expect(reviewRequests).toHaveLength(1);
      expect(reviewRequests[0]?.reviewType).toBe("PORTAL_STEP");
      expect(reviewRequests[0]?.payload.candidate_labels).toEqual(["Continue", "Review application"]);
      expect(reviewRequests[0]?.payload.ambiguity_code).toBe("AMBIGUOUS_PORTAL_ACTION");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists validation reports linked to generated files", () => {
    const { db, runId } = createRun();
    try {
      const artifactPath = join(tempDirs.at(-1)!, "Mary Jackson Example Resume.md");
      const reportPath = join(tempDirs.at(-1)!, "validation-report.json");
      writeFileSync(artifactPath, "# Mary Jackson\n\n## Skills\nPython\n", "utf8");
      writeFileSync(reportPath, JSON.stringify({ passed: true, blocking_issues: [], warnings: [{ code: "LONG_BULLET" }] }), "utf8");

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "RESUME_RENDERED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Resume review artifact rendered",
          machine_state: { format: "MD", review_only: true },
          ui_state: { current_step: "document_review" },
          payload: {
            file_kind: "RESUME",
            format: "MD",
            filename: "Mary Jackson Example Resume.md",
            local_path: artifactPath,
            sha256: "b".repeat(64),
            size_bytes: 32,
            retention_policy: "DELETE_AFTER_RETENTION",
            delete_after: "2026-01-15T00:00:00.000Z",
            review_only: true,
            validation_report_path: reportPath
          }
        })
      });

      const report = db.prepare("SELECT passed, source_kind, generated_file_id, warnings_json FROM validation_reports").get() as {
        passed: number;
        source_kind: string;
        generated_file_id: string | null;
        warnings_json: string;
      };
      expect(report.passed).toBe(1);
      expect(report.source_kind).toBe("MD");
      expect(report.generated_file_id).not.toBeNull();
      expect(report.warnings_json).toContain("LONG_BULLET");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists proposed answers idempotently using the worker source", () => {
    const { db, runId } = createRun();
    try {
      const rawLine = JSON.stringify({
        event_type: "FIELD_VALUE_PROPOSED",
        run_id: runId,
        step_id: null,
        timestamp: "2026-01-01T00:00:00.000Z",
        severity: "INFO",
        message: "Proposed answer for Email",
        machine_state: {},
        ui_state: { current_step: "field_review" },
        payload: {
          field_label: "Email",
          field_type: "text",
          proposed_value: "mary@example.com",
          confidence: 0.96,
          source: "PROFILE"
        }
      });

      ingestPythonEventLine({ db, windows: () => [], rawLine });
      ingestPythonEventLine({ db, windows: () => [], rawLine });

      const answers = new RunRepository(db).listAnswers(runId);
      const steps = new RunRepository(db).listSteps(runId);
      expect(answers).toHaveLength(1);
      expect(steps).toHaveLength(1);
      expect(steps[0]?.stepType).toBe("FIELD_REVIEW");
      expect(answers[0]?.source).toBe("PROFILE");
      expect(answers[0]?.proposedValue).toBe("mary@example.com");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("marks reviewed answers as applied when browser fill succeeds", () => {
    const { db, runId } = createRun();
    try {
      const runs = new RunRepository(db);
      runs.upsertAnswer({
        applicationRunId: runId,
        stepId: null,
        fieldLabel: "Email address",
        fieldType: "email",
        proposedValue: "mary@example.com",
        source: "PROFILE",
        confidence: 0.96,
        status: "APPROVED"
      });

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "FIELD_VALUE_APPLIED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Applied reviewed answer to Email address",
          machine_state: { selector: "#email" },
          ui_state: { current_step: "automation" },
          payload: {
            field_label: "Email address",
            field_type: "email",
            selector: "#email",
            value_length: 16,
            source: "USER_EDIT",
            applied_action: "set_value"
          }
        })
      });

      const answer = runs.listAnswers(runId)[0];
      expect(answer?.status).toBe("APPLIED");
      expect(answer?.applyMetadata).toMatchObject({
        appliedAction: "set_value",
        selector: "#email",
        valueLength: 16,
        source: "USER_EDIT"
      });
      expect(JSON.stringify(answer?.applyMetadata)).not.toContain("mary@example.com");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists JD analysis into structured job description tables", () => {
    const { db, runId } = createRun();
    try {
      const sourceTextPath = join(tempDirs.at(-1)!, "job-description.txt");
      writeFileSync(sourceTextPath, "Required: Python and TypeScript. Cover letter required.", "utf8");

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "JD_ANALYSIS_COMPLETED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Job description analysis completed",
          machine_state: {},
          ui_state: { current_step: "review" },
          payload: {
            source_text_path: sourceTextPath,
            must_have_keywords: ["python"],
            preferred_keywords: ["typescript"],
            hard_requirements: ["Required: Python and TypeScript."],
            tools_and_technologies: ["python", "typescript"],
            domain_signals: [],
            location_signals: [],
            work_authorization_signals: [],
            seniority_cues: [],
            communication_cues: [],
            required_materials: ["resume", "cover_letter"],
            cover_letter_likely_required: true,
            risky_claims_to_avoid: []
          }
        })
      });

      const descriptionCount = db.prepare("SELECT COUNT(*) AS count FROM job_descriptions").get() as { count: number };
      const keywordSet = db.prepare("SELECT cover_letter_likely_required, must_have_json FROM jd_keyword_sets").get() as {
        cover_letter_likely_required: number;
        must_have_json: string;
      };
      expect(descriptionCount.count).toBe(1);
      expect(keywordSet.cover_letter_likely_required).toBe(1);
      expect(keywordSet.must_have_json).toContain("python");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("persists browser-scraped JD analysis with scraped source metadata", () => {
    const { db, runId } = createRun();
    try {
      const sourceTextPath = join(tempDirs.at(-1)!, "job-description-scraped.txt");
      writeFileSync(sourceTextPath, "Required: Python. Apply through this portal.", "utf8");

      ingestPythonEventLine({
        db,
        windows: () => [],
        rawLine: JSON.stringify({
          event_type: "JD_ANALYSIS_COMPLETED",
          run_id: runId,
          step_id: null,
          timestamp: "2026-01-01T00:00:00.000Z",
          severity: "INFO",
          message: "Job description analysis completed",
          machine_state: {},
          ui_state: { current_step: "review" },
          payload: {
            source_text_path: sourceTextPath,
            jd_source: "SCRAPED",
            url: "https://boards.greenhouse.io/example/jobs/123",
            must_have_keywords: ["python"],
            preferred_keywords: [],
            hard_requirements: ["Required: Python."],
            tools_and_technologies: ["python"],
            domain_signals: [],
            location_signals: [],
            work_authorization_signals: [],
            seniority_cues: [],
            communication_cues: [],
            required_materials: ["resume"],
            cover_letter_likely_required: false,
            risky_claims_to_avoid: []
          }
        })
      });

      const description = db.prepare("SELECT source, scraped_url FROM job_descriptions").get() as {
        source: string;
        scraped_url: string | null;
      };
      expect(description.source).toBe("SCRAPED");
      expect(description.scraped_url).toBe("https://boards.greenhouse.io/example/jobs/123");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });
});
