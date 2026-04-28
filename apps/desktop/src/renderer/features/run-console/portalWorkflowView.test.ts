import { describe, expect, it } from "vitest";
import { buildPortalWorkflowSummary, formatWorkflowKind, type RunConsoleEvent } from "./portalWorkflowView";

const baseEvent = {
  runId: "6c83374d-b3bf-4e36-a14d-7ac0220482de",
  stepId: null,
  uiState: {},
  payload: {}
};

describe("portal workflow run-console view model", () => {
  it("builds a review-first portal summary from workflow and action events", () => {
    const events: RunConsoleEvent[] = [
      {
        ...baseEvent,
        eventType: "PORTAL_STATE_OBSERVED",
        timestamp: "2026-01-01T00:00:08.000Z",
        severity: "INFO",
        message: "Greenhouse portal state observed",
        payload: {
          current_url: "https://boards.greenhouse.io/example/jobs/123",
          current_portal_id: "greenhouse",
          host_changed: false,
          portal_changed: false,
          likely_application_surface: true,
          requires_review: false,
          signals: ["known_ats_surface", "multiple_fields_detected"],
          field_count: 5
        }
      },
      {
        ...baseEvent,
        eventType: "PORTAL_ACTION_APPLIED",
        timestamp: "2026-01-01T00:00:05.000Z",
        severity: "INFO",
        message: "Greenhouse portal entry action applied",
        payload: {
          portal_id: "greenhouse",
          attempted_labels: ["Apply for this job", "Apply now"],
          clicked_label: "Apply for this job",
          clicked_tag: "button"
        }
      },
      {
        ...baseEvent,
        eventType: "PORTAL_WORKFLOW_SELECTED",
        timestamp: "2026-01-01T00:00:00.000Z",
        severity: "INFO",
        message: "Portal workflow selected: Greenhouse",
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
          expected_steps: ["Open ATS job page", "Click known apply/start action", "Review answers before fill", "Gate final submit"],
          review_checkpoints: ["Login/MFA/CAPTCHA", "Sensitive questions", "Document approval", "Final submit"],
          notes: ["Click only known apply/start actions."]
        }
      }
    ];

    expect(buildPortalWorkflowSummary(events)).toMatchObject({
      portalId: "greenhouse",
      displayName: "Greenhouse",
      workflowKind: "ATS_DIRECT_FORM",
      adapter: "playwright",
      requiresManualReviewBeforeFill: true,
      actionStatus: "APPLIED",
      clickedLabel: "Apply for this job",
      attemptedLabels: ["Apply for this job", "Apply now"],
      expectedSteps: ["Open ATS job page", "Click known apply/start action", "Review answers before fill", "Gate final submit"],
      reviewCheckpoints: ["Login/MFA/CAPTCHA", "Sensitive questions", "Document approval", "Final submit"],
      pageStateStatus: "TRUSTED",
      likelyApplicationSurface: true,
      stateSignals: ["known_ats_surface", "multiple_fields_detected"]
    });
  });

  it("falls back to JD scrape workflow metadata before the browser launches", () => {
    const events: RunConsoleEvent[] = [
      {
        ...baseEvent,
        eventType: "JD_SCRAPE_STARTED",
        timestamp: "2026-01-01T00:00:00.000Z",
        severity: "INFO",
        message: "Scraping JD from job URL",
        payload: {
          workflow: {
            portal_id: "linkedin",
            display_name: "LinkedIn",
            workflow_kind: "JOB_BOARD_REDIRECT_OR_STEALTH",
            default_adapter: "nodriver",
            requires_high_stealth: true,
            requires_login_watch: true,
            requires_external_redirect_watch: true,
            requires_manual_review_before_fill: true,
            entry_action_labels: ["Easy Apply", "Apply"],
            expected_steps: ["Open job-board listing", "Click known apply action when safe", "Confirm trusted application surface", "Gate final submit"],
            review_checkpoints: ["Login/MFA/CAPTCHA", "Redirect trust", "Sensitive questions", "Final submit"],
            notes: ["Job board flow may redirect to ATS or require login."]
          }
        }
      }
    ];

    expect(buildPortalWorkflowSummary(events)).toMatchObject({
      portalId: "linkedin",
      adapter: "nodriver",
      requiresHighStealth: true,
      expectedSteps: ["Open job-board listing", "Click known apply action when safe", "Confirm trusted application surface", "Gate final submit"],
      reviewCheckpoints: ["Login/MFA/CAPTCHA", "Redirect trust", "Sensitive questions", "Final submit"],
      actionStatus: "PENDING"
    });
  });

  it("formats worker workflow identifiers for compact console labels", () => {
    expect(formatWorkflowKind("JOB_BOARD_REDIRECT_OR_STEALTH")).toBe("Job Board Redirect Or Stealth");
  });
});
