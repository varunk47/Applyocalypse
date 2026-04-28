import type { RunEvent, SafeRendererRunEvent } from "@applyocalypse/shared-types";

export type RunConsoleEvent = Pick<RunEvent | SafeRendererRunEvent, "eventType" | "severity" | "message" | "payload" | "timestamp">;

export type PortalWorkflowSummary = {
  portalId: string;
  displayName: string;
  workflowKind: string;
  adapter: string;
  requiresHighStealth: boolean;
  requiresManualReviewBeforeFill: boolean;
  requiresLoginWatch: boolean;
  requiresExternalRedirectWatch: boolean;
  entryActionLabels: string[];
  expectedSteps: string[];
  reviewCheckpoints: string[];
  notes: string[];
  actionStatus: "PENDING" | "APPLIED" | "NOT_APPLIED";
  actionMessage: string;
  clickedLabel: string | null;
  attemptedLabels: string[];
  pageStateStatus: "PENDING" | "TRUSTED" | "REVIEW";
  currentUrl: string | null;
  currentPortalId: string | null;
  portalChanged: boolean;
  hostChanged: boolean;
  likelyApplicationSurface: boolean;
  stateSignals: string[];
  updatedAt: string;
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

const stringValue = (value: unknown, fallback: string): string => (typeof value === "string" && value.trim() ? value.trim() : fallback);

const booleanValue = (value: unknown): boolean => value === true;

const stringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map((item) => item.trim()) : [];

const sortedEvents = (events: readonly RunConsoleEvent[]): RunConsoleEvent[] =>
  [...events].sort((first, second) => first.timestamp.localeCompare(second.timestamp));

const latestEvent = (events: readonly RunConsoleEvent[], eventType: string): RunConsoleEvent | null =>
  sortedEvents(events)
    .filter((event) => event.eventType === eventType)
    .at(-1) ?? null;

const workflowPayloadFrom = (event: RunConsoleEvent | null): Record<string, unknown> => {
  if (!event) {
    return {};
  }
  const payload = asRecord(event.payload);
  if (event.eventType === "JD_SCRAPE_STARTED") {
    return asRecord(payload["workflow"]);
  }
  return payload;
};

export const formatWorkflowKind = (workflowKind: string): string =>
  workflowKind
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");

export const buildPortalWorkflowSummary = (events: readonly RunConsoleEvent[]): PortalWorkflowSummary | null => {
  const workflowEvent = latestEvent(events, "PORTAL_WORKFLOW_SELECTED") ?? latestEvent(events, "JD_SCRAPE_STARTED");
  const workflow = workflowPayloadFrom(workflowEvent);
  if (Object.keys(workflow).length === 0 || !workflowEvent) {
    return null;
  }

  const actionEvent = latestEvent(events, "PORTAL_ACTION_APPLIED");
  const stateEvent = latestEvent(events, "PORTAL_STATE_OBSERVED");
  const actionPayload = asRecord(actionEvent?.payload);
  const statePayload = asRecord(stateEvent?.payload);
  const clickedLabel = stringValue(actionPayload["clicked_label"], "");
  const actionStatus = actionEvent ? (actionEvent.severity === "INFO" ? "APPLIED" : "NOT_APPLIED") : "PENDING";
  const actionMessage = actionEvent?.message ?? "No portal entry action has been attempted yet.";
  const adapter = stringValue(workflow["adapter"], stringValue(workflow["default_adapter"], "nodriver"));
  const pageStateStatus = stateEvent ? (booleanValue(statePayload["requires_review"]) ? "REVIEW" : "TRUSTED") : "PENDING";

  return {
    portalId: stringValue(workflow["portal_id"], "unknown"),
    displayName: stringValue(workflow["display_name"], "Unknown portal"),
    workflowKind: stringValue(workflow["workflow_kind"], "GENERIC_REVIEW_FIRST"),
    adapter,
    requiresHighStealth: booleanValue(workflow["requires_high_stealth"]),
    requiresManualReviewBeforeFill: booleanValue(workflow["requires_manual_review_before_fill"]),
    requiresLoginWatch: booleanValue(workflow["requires_login_watch"]),
    requiresExternalRedirectWatch: booleanValue(workflow["requires_external_redirect_watch"]),
    entryActionLabels: stringArray(workflow["entry_action_labels"]),
    expectedSteps: stringArray(workflow["expected_steps"]),
    reviewCheckpoints: stringArray(workflow["review_checkpoints"]),
    notes: stringArray(workflow["notes"]),
    actionStatus,
    actionMessage,
    clickedLabel: clickedLabel || null,
    attemptedLabels: stringArray(actionPayload["attempted_labels"]),
    pageStateStatus,
    currentUrl: stringValue(statePayload["current_url"], "") || null,
    currentPortalId: stringValue(statePayload["current_portal_id"], "") || null,
    portalChanged: booleanValue(statePayload["portal_changed"]),
    hostChanged: booleanValue(statePayload["host_changed"]),
    likelyApplicationSurface: booleanValue(statePayload["likely_application_surface"]),
    stateSignals: stringArray(statePayload["signals"]),
    updatedAt: stateEvent?.timestamp ?? actionEvent?.timestamp ?? workflowEvent.timestamp
  };
};
