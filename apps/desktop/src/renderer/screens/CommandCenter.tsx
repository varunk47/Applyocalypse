import { For, Show, createEffect, createMemo } from "solid-js";
import { createStore } from "solid-js/store";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileText,
  FolderOpen,
  KeyRound,
  Pause,
  Play,
  RefreshCcw,
  Save,
  Send,
  Settings,
  ShieldCheck,
  SkipForward,
  Square,
  Upload,
  Wrench
} from "lucide-solid";
import type { ApplicationAnswer, Approval, ReviewRequest } from "@applyocalypse/shared-types";
import { useAppState } from "../contexts/AppState";
import { buildAnchorRepairEditorModel } from "../features/documents/anchorRepairEditor";
import { buildEditableMasterDiagnostics } from "../features/documents/documentDiagnostics";
import { buildCoverLetterRequirementSummary } from "../features/run-console/materialRequirementsView";
import { buildPortalWorkflowSummary, formatWorkflowKind } from "../features/run-console/portalWorkflowView";

const navItems = ["Intake", "Profile", "Queue", "Run Console", "Documents", "History", "Settings"];

const providerOptions = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Gemini" },
  { value: "xai", label: "xAI Grok" },
  { value: "groq", label: "Groq" },
  { value: "nvidia_nim", label: "NVIDIA NIM" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "aws_bedrock", label: "AWS Bedrock" }
] as const;

const fieldQueue = [
  { label: "Legal name", value: "From verified profile" },
  { label: "Work authorization", value: "Needs explicit confirmation" },
  { label: "Resume upload", value: "Waiting for tailored artifact" },
  { label: "Cover letter", value: "Generate only if required" }
];

const diagnostics = [
  "Renderer isolated from SQLite, filesystem, secrets, and Python processes.",
  "Screenshots are file metadata only. No base64 screenshots cross IPC.",
  "Final submit gate is enabled by default."
];

const artifactUrlForPath = (localPath: string) => `applyocalypse://artifact?path=${encodeURIComponent(localPath)}`;

const metadataString = (metadata: Record<string, unknown>, key: string): string | null => {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

const answerApplySummary = (answer: ApplicationAnswer): string => {
  const metadata = answer.applyMetadata ?? {};
  const action = metadataString(metadata, "appliedAction");
  const selectedLabel = metadataString(metadata, "selectedLabel");
  const checked = typeof metadata["checked"] === "boolean" ? metadata["checked"] : null;
  if (answer.status === "APPLIED") {
    if (action === "set_checkbox" && checked !== null) {
      return checked ? "Checked after review" : "Unchecked after review";
    }
    if (selectedLabel) {
      return `Selected ${selectedLabel}`;
    }
    if (action === "select_option") {
      return "Selected reviewed option";
    }
    if (action === "set_radio") {
      return "Selected reviewed radio option";
    }
    return "Applied after review";
  }
  if (answer.status === "EDITED") {
    return "User-edited answer waiting for automation";
  }
  if (answer.status === "APPROVED") {
    return "Approved answer waiting for automation";
  }
  if (answer.status === "REJECTED") {
    return "Rejected by user";
  }
  return "Proposed answer waiting for review";
};

export const CommandCenter = () => {
  const {
    state,
    setThemePreference,
    setMaxConcurrentApplications,
    chooseOutputDir,
    createStarterProfile,
    configureApplicationCredentials,
    saveProfile,
    saveProviderApiKey,
    enqueueJobText,
    pickAndRegisterResume,
    pickAndRegisterSupportingDetails,
    pickAndRegisterCoverLetter,
    confirmEditableMaster,
    repairEditableMasterAnchors,
    openLocalPath,
    loadRunDetail,
    updateAnswer,
    pauseActiveRun,
    resumeActiveRun,
    cancelActiveRun,
    retryCurrentStep,
    skipCurrentStep,
    resolveReviewRequest,
    approveFinalSubmit,
    rejectFinalSubmit
  } = useAppState();
  const [form, setForm] = createStore({
    legalName: "",
    email: "",
    location: "",
    applicationEmail: "",
    applicationPassword: "",
    gmailOtpEnabled: false,
    profileLegalName: "",
    profileDisplayName: "",
    profileEmail: "",
    profilePhone: "",
    profileLocation: "",
    profileWorkAuthorization: "",
    profileApplicationEmail: "",
    profileApplicationPassword: "",
    profileGmailOtpEnabled: false,
    jobInput: "",
    provider: "openai" as (typeof providerOptions)[number]["value"],
    providerDisplayName: "OpenAI",
    providerModel: "",
    providerApiBase: "",
    providerApiVersion: "",
    providerAwsAccessKeyId: "",
    providerAwsRegion: "",
    providerApiKey: "",
    autoSubmitEnabled: false,
    rejectReason: "Final submit rejected by local user."
  });
  let hydratedProfileId = "";
  const portalWorkflow = createMemo(() => buildPortalWorkflowSummary(state.runDetail?.events ?? state.events));
  const coverLetterRequirement = createMemo(() => buildCoverLetterRequirementSummary(state.runDetail?.events ?? state.events));

  createEffect(() => {
    const profile = state.profile;
    if (!profile || profile.id === hydratedProfileId) {
      return;
    }
    hydratedProfileId = profile.id;
    setForm({
      profileDisplayName: profile.displayName,
      profileLegalName: profile.legalName,
      profileEmail: profile.email ?? "",
      profilePhone: profile.phone ?? "",
      profileLocation: profile.location ?? "",
      profileWorkAuthorization: String(profile.workAuthorization["summary"] ?? ""),
      profileApplicationEmail: profile.applicationEmail ?? profile.email ?? "",
      profileApplicationPassword: "",
      profileGmailOtpEnabled: profile.otpHandlingEnabled
    });
  });

  const applicationPasswordIsValid = (value: string): boolean =>
    /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$/.test(value);

  const submitStarterProfile = (): void => {
    if (!applicationPasswordIsValid(form.applicationPassword)) {
      return;
    }
    void createStarterProfile({
      legalName: form.legalName,
      email: form.email || null,
      location: form.location || null,
      applicationEmail: form.applicationEmail,
      applicationPassword: form.applicationPassword,
      gmailOtpEnabled: form.gmailOtpEnabled
    });
    setForm("applicationPassword", "");
  };

  const submitProfileEdits = (): void => {
    if (!state.profile) {
      return;
    }
    void saveProfile({
      ...state.profile,
      legalName: form.profileLegalName || state.profile.legalName,
      displayName: form.profileDisplayName || state.profile.displayName,
      email: form.profileEmail || null,
      phone: form.profilePhone || null,
      location: form.profileLocation || null,
      workAuthorization: {
        ...state.profile.workAuthorization,
        ...(form.profileWorkAuthorization ? { summary: form.profileWorkAuthorization } : {})
      }
    });
  };

  const submitApplicationCredentials = (): void => {
    if (!state.profile || !applicationPasswordIsValid(form.profileApplicationPassword)) {
      return;
    }
    void configureApplicationCredentials({
      profileId: state.profile.id,
      applicationEmail: form.profileApplicationEmail,
      applicationPassword: form.profileApplicationPassword,
      gmailOtpEnabled: form.profileGmailOtpEnabled
    });
    setForm("profileApplicationPassword", "");
  };

  const runForQueueItem = (queueItemId: string) => state.applicationRuns.find((run) => run.queueItemId === queueItemId) ?? null;
  const parsedDocumentForFile = (uploadedFileId: string) =>
    state.parsedDocuments.find((document) => document.uploadedFileId === uploadedFileId) ?? null;
  const isManualBlockerReview = (reviewType: string): boolean =>
    ["CAPTCHA", "MFA", "OTP", "AMBIGUOUS_QUESTION", "LOGIN", "PORTAL_ENTRY", "PORTAL_STEP"].includes(reviewType);
  const approvalTypeForReview = (reviewType: string): Approval["approvalType"] => {
    if (reviewType === "DOCUMENT") {
      return "DOCUMENT_APPROVAL";
    }
    if (reviewType === "ANSWER") {
      return "ANSWER_EDIT";
    }
    if (reviewType === "OTP") {
      return "OTP_READ";
    }
    if (reviewType === "FINAL_SUBMIT") {
      return "FINAL_SUBMIT";
    }
    return "FINAL_SUBMIT";
  };
  const reviewInstruction = (request: { reviewType: string }): string => {
    if (request.reviewType === "OTP") {
      return "Enter the code directly in the job portal, then mark it handled. Applyocalypse will not store OTP codes.";
    }
    if (request.reviewType === "CAPTCHA") {
      return "Complete the challenge in the portal, then resume automation from the same step.";
    }
    if (request.reviewType === "MFA") {
      return "Approve the sign-in challenge outside Applyocalypse, then resume automation.";
    }
    if (request.reviewType === "LOGIN") {
      return "Sign in or create the required account in the portal, then resume automation from the same page.";
    }
    if (request.reviewType === "PORTAL_ENTRY") {
      return "Click the portal apply or start action in the browser, then resume automation from that page.";
    }
    if (request.reviewType === "PORTAL_STEP") {
      return "Click the reviewed non-final Next, Continue, or Review action in the browser, then resume automation from that step.";
    }
    if (request.reviewType === "AMBIGUOUS_QUESTION") {
      return "Review and edit the detected answer before continuing.";
    }
    if (request.reviewType === "ANSWER") {
      return "Review every detected field answer, edit anything uncertain, then approve answers before automation fills the form.";
    }
    if (request.reviewType === "DOCUMENT") {
      return "Review generated documents and keep field answers approved before browser automation continues.";
    }
    if (request.reviewType === "FINAL_SUBMIT") {
      return "Final submission remains blocked until explicitly approved.";
    }
    return "Review the request before allowing automation to continue.";
  };
  const reviewCandidateLabels = (request: ReviewRequest): string[] => {
    const candidateLabels = request.payload["candidate_labels"];
    if (Array.isArray(candidateLabels)) {
      return candidateLabels.filter((label): label is string => typeof label === "string" && label.trim().length > 0).slice(0, 6);
    }
    const attemptedLabels = request.payload["attempted_labels"];
    return Array.isArray(attemptedLabels)
      ? attemptedLabels.filter((label): label is string => typeof label === "string" && label.trim().length > 0).slice(0, 6)
      : [];
  };
  const approveReviewRequest = async (request: { id: string; reviewType: string }): Promise<void> => {
    if (isManualBlockerReview(request.reviewType)) {
      await resolveReviewRequest(request.id, "APPROVED", `${request.reviewType} handled by local user.`);
      return;
    }
    await approveFinalSubmit(approvalTypeForReview(request.reviewType));
  };
  const rejectReviewRequest = async (request: { id: string; reviewType: string }): Promise<void> => {
    if (isManualBlockerReview(request.reviewType)) {
      await resolveReviewRequest(request.id, "REJECTED", `${request.reviewType} rejected by local user.`);
      return;
    }
    await rejectFinalSubmit(form.rejectReason, approvalTypeForReview(request.reviewType));
  };

  const submitProviderKey = (): void => {
    const metadataEntries = {
      defaultModel: form.providerModel.trim(),
      apiBase: form.providerApiBase.trim(),
      apiVersion: form.providerApiVersion.trim(),
      awsAccessKeyId: form.providerAwsAccessKeyId.trim(),
      awsRegion: form.providerAwsRegion.trim()
    };
    void saveProviderApiKey({
      provider: form.provider,
      displayName: form.providerDisplayName || providerOptions.find((option) => option.value === form.provider)?.label || form.provider,
      apiKey: form.providerApiKey,
      metadata: Object.fromEntries(Object.entries(metadataEntries).filter(([, value]) => value.length > 0))
    });
    setForm("providerApiKey", "");
  };

  return (
    <>
      <aside class="nav-rail" aria-label="Applyocalypse navigation">
        <div class="brand-mark" data-gsap="nav-item">
          <span class="brand-core">A</span>
        </div>
        <nav class="nav-list">
          <For each={navItems}>
            {(item) => (
              <button class="nav-item" data-gsap="nav-item" type="button">
                <span>{item}</span>
                <ChevronRight size={14} aria-hidden="true" />
              </button>
            )}
          </For>
        </nav>
      </aside>

      <main class="command-grid">
        <section class="hero-panel" data-gsap="panel">
          <div class="eyebrow">Local-first application control</div>
          <h1>Applyocalypse</h1>
          <p>
            A desktop command center for tailoring truthful documents, supervising browser automation, and stopping before final submission until the user approves.
          </p>
          <div class="hero-actions">
            <button class="primary-action" type="button" onClick={() => void pickAndRegisterResume()}>
              <Upload size={18} aria-hidden="true" />
              <span>Add resume source</span>
            </button>
            <button class="secondary-action" type="button" onClick={() => void window.applyocalypse.folders.openDownloads()}>
              <FolderOpen size={18} aria-hidden="true" />
              <span>Open Downloads</span>
            </button>
          </div>
        </section>

        <section class="theme-panel" data-gsap="panel" aria-label="Theme mode">
          <div>
            <div class="panel-kicker">Native theme</div>
            <h2>Window and renderer stay synced.</h2>
          </div>
          <div class="segmented-control">
            <button classList={{ active: state.theme.preference === "dark" }} type="button" onClick={() => void setThemePreference("dark")}>
              Dark
            </button>
            <button classList={{ active: state.theme.preference === "light" }} type="button" onClick={() => void setThemePreference("light")}>
              Light
            </button>
            <button classList={{ active: state.theme.preference === "system" }} type="button" onClick={() => void setThemePreference("system")}>
              System
            </button>
          </div>
          <p class="fine-print">Active: {state.theme.activeTheme}</p>
        </section>

        <section class="run-console" data-gsap="panel">
          <div class="section-header">
            <div>
              <div class="panel-kicker">Complete Control</div>
              <h2>Live run console</h2>
            </div>
            <div class="run-status">
              <span class="pulse-dot" />
              {state.runDetail ? state.runDetail.run.status : "Waiting for queue"}
            </div>
          </div>

          <div class="console-body">
            <div class="browser-preview">
              <div class="preview-toolbar">
                <span />
                <span />
                <span />
                <strong>Portal preview</strong>
              </div>
              <div class="preview-stage">
                <div class="scanline" />
                <Show
                  when={state.screenshots.at(-1)}
                  fallback={
                    <>
                      <FileText size={42} aria-hidden="true" />
                      <p>Screenshot timeline and live browser view attach here once a worker starts.</p>
                    </>
                  }
                >
                  {(screenshot) => <img class="browser-screenshot" src={artifactUrlForPath(screenshot().localPath)} alt="Latest browser screenshot" />}
                </Show>
              </div>
            </div>

            <div class="control-stack">
              <div class="control-row">
                <button class="icon-button" type="button" aria-label="Pause run" disabled={!state.runDetail} onClick={() => void pauseActiveRun()}>
                  <Pause size={17} aria-hidden="true" />
                </button>
                <button class="icon-button" type="button" aria-label="Resume run" disabled={!state.runDetail} onClick={() => void resumeActiveRun()}>
                  <Play size={17} aria-hidden="true" />
                </button>
                <button class="icon-button" type="button" aria-label="Retry step" disabled={!state.runDetail} onClick={() => void retryCurrentStep()}>
                  <RefreshCcw size={17} aria-hidden="true" />
                </button>
                <button class="icon-button" type="button" aria-label="Skip safe step" disabled={!state.runDetail} onClick={() => void skipCurrentStep()}>
                  <SkipForward size={17} aria-hidden="true" />
                </button>
                <button class="icon-button danger" type="button" aria-label="Cancel run" disabled={!state.runDetail} onClick={() => void cancelActiveRun()}>
                  <Square size={15} aria-hidden="true" />
                </button>
              </div>

              <div class="approval-gate">
                <ShieldCheck size={21} aria-hidden="true" />
                <div>
                  <strong>Final submit gate</strong>
                  <span>Approval required unless auto-submit is explicitly enabled for this run.</span>
                </div>
              </div>

              <div class="material-requirement-panel">
                <div class="panel-kicker">Application materials</div>
                <div class="material-requirement-row">
                  <span>Cover letter</span>
                  <strong classList={{ warning: coverLetterRequirement().status === "MISSING_REQUIRED" }}>
                    {coverLetterRequirement().status.replace("_", " ")}
                  </strong>
                </div>
                <p>{coverLetterRequirement().latestMessage}</p>
                <div class="workflow-flags">
                  <span classList={{ enabled: coverLetterRequirement().source !== "UNKNOWN" }}>{coverLetterRequirement().source.replace("_", " ")}</span>
                  <span classList={{ enabled: coverLetterRequirement().required }}>Required</span>
                  <span classList={{ enabled: coverLetterRequirement().fieldCount > 0 }}>Form fields {coverLetterRequirement().fieldCount}</span>
                  <span classList={{ enabled: coverLetterRequirement().missingRequiredDocuments > 0 }}>
                    Missing {coverLetterRequirement().missingRequiredDocuments}
                  </span>
                </div>
              </div>

              <Show when={portalWorkflow()}>
                {(workflow) => (
                  <div class="portal-workflow-panel">
                    <div class="panel-kicker">Portal workflow</div>
                    <div class="portal-workflow-header">
                      <strong>{workflow().displayName}</strong>
                      <span>{formatWorkflowKind(workflow().workflowKind)}</span>
                    </div>
                    <div class="portal-workflow-grid">
                      <span>Adapter</span>
                      <strong>{workflow().adapter}</strong>
                      <span>Review before fill</span>
                      <strong>{workflow().requiresManualReviewBeforeFill ? "Required" : "Optional"}</strong>
                      <span>Entry action</span>
                      <strong>{workflow().actionStatus}</strong>
                      <span>Page state</span>
                      <strong>{workflow().pageStateStatus}</strong>
                      <span>Expected steps</span>
                      <strong>{workflow().expectedSteps.length}</strong>
                      <span>Checkpoints</span>
                      <strong>{workflow().reviewCheckpoints.length}</strong>
                    </div>
                    <Show when={workflow().entryActionLabels.length > 0}>
                      <div class="workflow-chip-row" aria-label="Configured safe portal actions">
                        <For each={workflow().entryActionLabels}>{(label) => <span>{label}</span>}</For>
                      </div>
                    </Show>
                    <Show when={workflow().expectedSteps.length > 0}>
                      <div class="workflow-chip-row" aria-label="Expected portal workflow steps">
                        <For each={workflow().expectedSteps.slice(0, 4)}>{(step) => <span>{step}</span>}</For>
                      </div>
                    </Show>
                    <Show when={workflow().reviewCheckpoints.length > 0}>
                      <div class="workflow-chip-row" aria-label="Portal review checkpoints">
                        <For each={workflow().reviewCheckpoints.slice(0, 4)}>{(checkpoint) => <span>{checkpoint}</span>}</For>
                      </div>
                    </Show>
                    <p>{workflow().clickedLabel ? `Clicked ${workflow().clickedLabel}` : workflow().actionMessage}</p>
                    <div class="workflow-flags">
                      <span classList={{ enabled: workflow().requiresHighStealth }}>Stealth</span>
                      <span classList={{ enabled: workflow().requiresLoginWatch }}>Login watch</span>
                      <span classList={{ enabled: workflow().requiresExternalRedirectWatch }}>Redirect watch</span>
                      <span classList={{ enabled: workflow().hostChanged || workflow().portalChanged }}>Moved</span>
                      <span classList={{ enabled: workflow().likelyApplicationSurface }}>Application surface</span>
                    </div>
                    <Show when={workflow().stateSignals.length > 0}>
                      <div class="workflow-chip-row" aria-label="Observed portal state signals">
                        <For each={workflow().stateSignals.slice(0, 4)}>{(signal) => <span>{signal}</span>}</For>
                      </div>
                    </Show>
                  </div>
                )}
              </Show>

              <Show when={(state.runDetail?.reviewRequests.filter((request) => request.status === "OPEN").length ?? 0) > 0}>
                <div class="review-actions">
                  <div class="panel-kicker">Open review</div>
                  <For each={state.runDetail?.reviewRequests.filter((request) => request.status === "OPEN") ?? []}>
                    {(request) => (
                      <div class="review-card">
                        <strong>{request.reviewType}</strong>
                        <p>{request.prompt}</p>
                        <small>{reviewInstruction(request)}</small>
                        <Show when={reviewCandidateLabels(request).length > 0}>
                          <div class="workflow-chip-row" aria-label="Review candidate labels">
                            <For each={reviewCandidateLabels(request)}>{(label) => <span>{label}</span>}</For>
                          </div>
                        </Show>
                        <div class="review-card-actions">
                          <button class="secondary-action" type="button" onClick={() => void approveReviewRequest(request)}>
                            <ShieldCheck size={17} aria-hidden="true" />
                            <span>{isManualBlockerReview(request.reviewType) ? "Handled" : "Approve"}</span>
                          </button>
                          <button class="secondary-action danger-text" type="button" onClick={() => void rejectReviewRequest(request)}>
                            <Square size={14} aria-hidden="true" />
                            <span>Reject</span>
                          </button>
                        </div>
                      </div>
                    )}
                  </For>
                </div>
              </Show>

              <Show when={(state.runDetail?.generatedFiles.length ?? 0) > 0}>
                <div class="generated-files">
                  <div class="panel-kicker">Generated artifacts</div>
                  <For each={state.runDetail?.generatedFiles ?? []}>
                    {(file) => (
                      <button class="artifact-row" type="button" onClick={() => void openLocalPath(file.localPath)}>
                        <FileText size={16} aria-hidden="true" />
                        <span>
                          <strong>{file.filename}</strong>
                          <small>
                            {file.fileKind} / {file.format} / {file.uploadStatus}
                          </small>
                        </span>
                        <FolderOpen size={15} aria-hidden="true" />
                      </button>
                    )}
                  </For>
                </div>
              </Show>

              <Show when={(state.runDetail?.browserArtifacts.length ?? 0) > 0}>
                <div class="generated-files">
                  <div class="panel-kicker">Browser diagnostics</div>
                  <For each={state.runDetail?.browserArtifacts ?? []}>
                    {(artifact) => (
                      <button class="artifact-row" type="button" onClick={() => void openLocalPath(artifact.localPath)}>
                        <FileText size={16} aria-hidden="true" />
                        <span>
                          <strong>{artifact.artifactType}</strong>
                          <small>{new Date(artifact.createdAt).toLocaleString()}</small>
                        </span>
                        <FolderOpen size={15} aria-hidden="true" />
                      </button>
                    )}
                  </For>
                </div>
              </Show>

              <div class="answer-drawer">
                <div class="panel-kicker">Detected fields</div>
                <Show
                  when={state.runDetail?.answers.length}
                  fallback={
                    <For each={fieldQueue}>
                      {(field) => (
                        <div class="field-row">
                          <span>{field.label}</span>
                          <strong>{field.value}</strong>
                        </div>
                      )}
                    </For>
                  }
                >
                  <For each={state.runDetail?.answers ?? []}>
                    {(answer) => (
                      <label class="field-row editable-answer">
                        <span class="answer-heading">
                          <span>{answer.fieldLabel}</span>
                          <strong>{answer.status}</strong>
                        </span>
                        <input
                          aria-label={`Reviewed answer for ${answer.fieldLabel}`}
                          value={answer.userValue ?? answer.proposedValue ?? ""}
                          onChange={(event) => void updateAnswer(answer.id, event.currentTarget.value, "EDITED")}
                        />
                        <small class="answer-apply-meta">
                          {answer.fieldType} / {answerApplySummary(answer)}
                        </small>
                      </label>
                    )}
                  </For>
                </Show>
              </div>
            </div>
          </div>
          <div class="event-stream">
            <div class="panel-kicker">Raw event stream</div>
            <Show when={state.screenshots.length > 0}>
              <div class="screenshot-strip">
                <For each={state.screenshots}>
                  {(screenshot) => (
                    <img
                      src={artifactUrlForPath(screenshot.localPath)}
                      alt={`Screenshot ${screenshot.screenshotId}`}
                      title={new Date(screenshot.capturedAt).toLocaleString()}
                    />
                  )}
                </For>
              </div>
            </Show>
            <Show when={state.runDetail}>
              <div class="event-line">
                <span>{state.runDetail?.run.status}</span>
                <p>Current run: {state.runDetail?.run.id.slice(0, 8)}</p>
              </div>
              <Show when={state.runDetail?.run.currentStepId}>
                <div class="event-line">
                  <span>STEP</span>
                  <p>{state.runDetail?.run.currentStepId}</p>
                </div>
              </Show>
              <For each={state.runDetail?.steps ?? []}>
                {(step) => (
                  <div class="event-line">
                    <span>{step.status}</span>
                    <p>{step.stepType}</p>
                  </div>
                )}
              </For>
            </Show>
            <For each={state.runDetail?.events ?? state.events}>
              {(event) => (
                <div class="event-line">
                  <span>{event.severity}</span>
                  <p>{event.message}</p>
                </div>
              )}
            </For>
          </div>
        </section>

        <section class="intake-panel" data-gsap="panel">
          <div class="section-header">
            <div>
              <div class="panel-kicker">Job intake</div>
              <h2>Paste links or descriptions</h2>
            </div>
            <button
              class="icon-button"
              type="button"
              aria-label="Send intake"
              onClick={() => void enqueueJobText(form.jobInput, { autoSubmitEnabled: form.autoSubmitEnabled })}
            >
              <Send size={17} aria-hidden="true" />
            </button>
          </div>
          <textarea
            spellcheck="false"
            value={form.jobInput}
            onInput={(event) => setForm("jobInput", event.currentTarget.value)}
            placeholder="Paste one job link per line, or paste a full job description."
          />
          <label class="automation-option">
            <input
              type="checkbox"
              checked={form.autoSubmitEnabled}
              onChange={(event) => setForm("autoSubmitEnabled", event.currentTarget.checked)}
            />
            <span>
              <strong>Auto-submit after review</strong>
              <small>Confirmation still has to be detected before success is recorded.</small>
            </span>
          </label>
          <p class="fine-print">Queue items start as PENDING. Electron Main claims work with leases and heartbeats.</p>
        </section>

        <section class="queue-panel" data-gsap="panel">
          <div class="section-header">
            <div>
              <div class="panel-kicker">Queue</div>
              <h2>Application runs</h2>
            </div>
            <span class="metric">{state.queueTotal + state.runsTotal}</span>
          </div>
          <Show
            when={state.queueItems.length > 0 || state.applicationRuns.length > 0}
            fallback={
              <div class="empty-state">
                <CheckCircle2 size={24} aria-hidden="true" />
                <strong>No active jobs yet</strong>
                <span>Add source materials and paste job targets to begin.</span>
              </div>
            }
          >
            <div class="queue-list">
              <For each={state.queueItems}>
                {(item) => {
                  const run = runForQueueItem(item.id);
                  return (
                    <button
                      class="queue-row"
                      classList={{ active: state.activeRunId === run?.id }}
                      type="button"
                      disabled={!run}
                      onClick={() => (run ? void loadRunDetail(run.id) : undefined)}
                    >
                      <span>{run?.status ?? item.status}</span>
                      <strong>{run ? run.id.slice(0, 8) : item.jobTargetId.slice(0, 8)}</strong>
                    </button>
                  );
                }}
              </For>
              <For each={state.applicationRuns.filter((run) => !state.queueItems.some((item) => item.id === run.queueItemId)).slice(0, 6)}>
                {(run) => (
                  <button
                    class="queue-row"
                    classList={{ active: state.activeRunId === run.id }}
                    type="button"
                    onClick={() => void loadRunDetail(run.id)}
                  >
                    <span>{run.status}</span>
                    <strong>{run.id.slice(0, 8)}</strong>
                  </button>
                )}
              </For>
            </div>
          </Show>
        </section>

        <section class="diagnostics-panel" data-gsap="panel">
          <div class="section-header">
            <div>
              <div class="panel-kicker">Diagnostics</div>
              <h2>Safety invariants</h2>
            </div>
            <AlertTriangle size={20} aria-hidden="true" />
          </div>
          <For each={diagnostics}>
            {(line) => (
              <div class="diagnostic-line">
                <span />
                <p>{line}</p>
              </div>
            )}
          </For>
          <Show when={state.error}>
            <div class="error-box">{state.error}</div>
          </Show>
        </section>

        <section class="provider-panel" data-gsap="panel">
          <div class="section-header">
            <div>
              <div class="panel-kicker">Provider connections</div>
              <h2>BYOK model routing</h2>
            </div>
            <ShieldCheck size={20} aria-hidden="true" />
          </div>
          <div class="starter-profile">
            <label>
              <span>Provider</span>
              <select
                value={form.provider}
                onChange={(event) => {
                  const provider = event.currentTarget.value as (typeof providerOptions)[number]["value"];
                  setForm("provider", provider);
                  setForm("providerDisplayName", providerOptions.find((option) => option.value === provider)?.label ?? provider);
                }}
              >
                <For each={providerOptions}>
                  {(provider) => <option value={provider.value}>{provider.label}</option>}
                </For>
              </select>
            </label>
            <label>
              <span>Display name</span>
              <input value={form.providerDisplayName} onInput={(event) => setForm("providerDisplayName", event.currentTarget.value)} />
            </label>
            <label>
              <span>API key</span>
              <input
                type="password"
                value={form.providerApiKey}
                autocomplete="off"
                onInput={(event) => setForm("providerApiKey", event.currentTarget.value)}
              />
            </label>
            <label>
              <span>Model</span>
              <input
                value={form.providerModel}
                placeholder="provider/model"
                onInput={(event) => setForm("providerModel", event.currentTarget.value)}
              />
            </label>
            <label>
              <span>API base</span>
              <input
                value={form.providerApiBase}
                placeholder="https://"
                onInput={(event) => setForm("providerApiBase", event.currentTarget.value)}
              />
            </label>
            <Show when={form.provider === "azure_openai"}>
              <label>
                <span>API version</span>
                <input
                  value={form.providerApiVersion}
                  placeholder="2025-01-01-preview"
                  onInput={(event) => setForm("providerApiVersion", event.currentTarget.value)}
                />
              </label>
            </Show>
            <Show when={form.provider === "aws_bedrock"}>
              <label>
                <span>AWS access key ID</span>
                <input
                  value={form.providerAwsAccessKeyId}
                  autocomplete="off"
                  onInput={(event) => setForm("providerAwsAccessKeyId", event.currentTarget.value)}
                />
              </label>
              <label>
                <span>AWS region</span>
                <input
                  value={form.providerAwsRegion}
                  placeholder="us-east-1"
                  onInput={(event) => setForm("providerAwsRegion", event.currentTarget.value)}
                />
              </label>
            </Show>
            <button class="secondary-action" type="button" onClick={submitProviderKey}>
              <ShieldCheck size={17} aria-hidden="true" />
              <span>Save key reference</span>
            </button>
          </div>
          <div class="queue-list">
            <For each={state.providerConnections}>
              {(connection) => (
                <div class="queue-row static-row">
                  <span>{connection.status}</span>
                  <strong>{connection.displayName}</strong>
                </div>
              )}
            </For>
          </div>
        </section>

        <section class="uploads-panel" data-gsap="panel">
          <div class="section-header">
            <div>
              <div class="panel-kicker">Source materials</div>
              <h2>Editable master verification</h2>
            </div>
            <Upload size={20} aria-hidden="true" />
          </div>
          <div class="source-actions">
            <button class="secondary-action" type="button" onClick={() => void pickAndRegisterResume()}>
              <Upload size={16} aria-hidden="true" />
              <span>Resume</span>
            </button>
            <button class="secondary-action" type="button" onClick={() => void pickAndRegisterSupportingDetails()}>
              <FileText size={16} aria-hidden="true" />
              <span>Details</span>
            </button>
            <button class="secondary-action" type="button" onClick={() => void pickAndRegisterCoverLetter()}>
              <FileText size={16} aria-hidden="true" />
              <span>Cover sample</span>
            </button>
          </div>
          <Show
            when={state.uploadedFiles.length > 0}
            fallback={
              <div class="empty-state">
                <FileText size={22} aria-hidden="true" />
                <strong>No source files in this session</strong>
                <span>PDF sources require converted DOCX review before automated tailoring.</span>
              </div>
            }
          >
            <div class="queue-list">
              <For each={state.uploadedFiles}>
                {(file) => (
                  <div class="upload-row">
                    <div class="upload-summary">
                      <span>{file.status}</span>
                      <strong>{file.originalName}</strong>
                      <Show when={parsedDocumentForFile(file.id)}>
                        {(parsedDocument) => (
                          (() => {
                            const diagnostics = buildEditableMasterDiagnostics(parsedDocument());
                            const repairModel = buildAnchorRepairEditorModel(parsedDocument());
                            return (
                              <div class="document-parse-meta">
                                <div class="confidence-meter" aria-label={`Parser confidence ${Math.round(parsedDocument().confidence * 100)} percent`}>
                                  <span style={{ width: `${Math.round(parsedDocument().confidence * 100)}%` }} />
                                </div>
                                <small>
                                  {parsedDocument().canonical.sections.length} sections / {diagnostics.structuralAnchorCount} structural anchors /{" "}
                                  {diagnostics.warningCount} warnings
                                </small>
                                <div class={`anchor-diagnostics anchor-diagnostics-${diagnostics.mutationReadiness}`}>
                                  <span>{diagnostics.summary}</span>
                                  <Show when={diagnostics.placeholderPreview.length > 0}>
                                    <code>{diagnostics.placeholderPreview.join(", ")}</code>
                                  </Show>
                                </div>
                                <div class="anchor-repair-editor" aria-label="Editable master anchor map">
                                  <div class="anchor-repair-header">
                                    <strong>{repairModel.actionLabel}</strong>
                                    <span>{repairModel.sourceFormat}</span>
                                  </div>
                                  <div class="anchor-zone-grid">
                                    <For each={repairModel.zones.slice(0, 5)}>
                                      {(zone) => (
                                        <div class={`anchor-zone anchor-zone-${zone.status}`}>
                                          <span>{zone.label}</span>
                                          <strong>{Math.round(zone.confidence * 100)}%</strong>
                                          <small>{zone.placeholder ?? zone.sourceHint}</small>
                                        </div>
                                      )}
                                    </For>
                                  </div>
                                </div>
                              </div>
                            );
                          })()
                        )}
                      </Show>
                    </div>
                    <div class="control-row">
                      <button class="icon-button" type="button" aria-label="Open local file" onClick={() => void openLocalPath(file.localPath)}>
                        <FolderOpen size={16} aria-hidden="true" />
                      </button>
                      <Show when={file.status === "UNVERIFIED_EDITABLE_MASTER"}>
                        <button class="icon-button" type="button" aria-label="Confirm editable master" onClick={() => void confirmEditableMaster(file.id)}>
                          <ShieldCheck size={16} aria-hidden="true" />
                        </button>
                      </Show>
                      <Show
                        when={
                          file.fileKind === "RESUME" &&
                          (file.sourceFormat === "DOCX" || file.sourceFormat === "TEX") &&
                          parsedDocumentForFile(file.id) &&
                          buildEditableMasterDiagnostics(parsedDocumentForFile(file.id)!).mutationReadiness === "needs_anchor_repair"
                        }
                      >
                        <button class="icon-button" type="button" aria-label="Create anchor repair candidate" onClick={() => void repairEditableMasterAnchors(file.id)}>
                          <Wrench size={16} aria-hidden="true" />
                        </button>
                      </Show>
                    </div>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </section>

        <section class="settings-panel" data-gsap="panel">
          <Settings size={20} aria-hidden="true" />
          <div>
            <div class="panel-kicker">Profile workspace</div>
            <Show
              when={state.profile}
              fallback={
                <div class="starter-profile">
                  <h2>Create master profile</h2>
                  <label>
                    <span>Legal name</span>
                    <input value={form.legalName} onInput={(event) => setForm("legalName", event.currentTarget.value)} />
                  </label>
                  <label>
                    <span>Email</span>
                    <input value={form.email} onInput={(event) => setForm("email", event.currentTarget.value)} />
                  </label>
                  <label>
                    <span>Application email</span>
                    <input
                      type="email"
                      value={form.applicationEmail}
                      autocomplete="username"
                      onInput={(event) => setForm("applicationEmail", event.currentTarget.value)}
                    />
                  </label>
                  <label>
                    <span>Application password</span>
                    <input
                      type="password"
                      value={form.applicationPassword}
                      autocomplete="new-password"
                      onInput={(event) => setForm("applicationPassword", event.currentTarget.value)}
                    />
                  </label>
                  <label class="toggle-row">
                    <input
                      type="checkbox"
                      checked={form.gmailOtpEnabled}
                      onChange={(event) => setForm("gmailOtpEnabled", event.currentTarget.checked)}
                    />
                    <span>Use Gmail OTP extraction for this inbox</span>
                  </label>
                  <p class="fine-print">Password policy: 12 or more characters with lowercase, uppercase, number, and symbol.</p>
                  <label>
                    <span>Location</span>
                    <input value={form.location} onInput={(event) => setForm("location", event.currentTarget.value)} />
                  </label>
                  <button
                    class="secondary-action"
                    type="button"
                    disabled={!form.legalName.trim() || !form.applicationEmail.trim() || !applicationPasswordIsValid(form.applicationPassword)}
                    onClick={submitStarterProfile}
                  >
                    <ShieldCheck size={17} aria-hidden="true" />
                    <span>Save profile</span>
                  </button>
                </div>
              }
            >
              <h2>{state.profile?.displayName}</h2>
              <p>{state.profile?.email ?? "No email saved"} - {state.profile?.location ?? "No location saved"}</p>
              <div class="starter-profile profile-editor">
                <label>
                  <span>Display name</span>
                  <input
                    value={form.profileDisplayName}
                    onInput={(event) => setForm("profileDisplayName", event.currentTarget.value)}
                  />
                </label>
                <label>
                  <span>Legal name</span>
                  <input
                    value={form.profileLegalName}
                    onInput={(event) => setForm("profileLegalName", event.currentTarget.value)}
                  />
                </label>
                <label>
                  <span>Email</span>
                  <input
                    value={form.profileEmail}
                    onInput={(event) => setForm("profileEmail", event.currentTarget.value)}
                  />
                </label>
                <label>
                  <span>Phone</span>
                  <input
                    value={form.profilePhone}
                    onInput={(event) => setForm("profilePhone", event.currentTarget.value)}
                  />
                </label>
                <label>
                  <span>Location</span>
                  <input
                    value={form.profileLocation}
                    onInput={(event) => setForm("profileLocation", event.currentTarget.value)}
                  />
                </label>
                <label>
                  <span>Work authorization note</span>
                  <input
                    value={form.profileWorkAuthorization}
                    onInput={(event) => setForm("profileWorkAuthorization", event.currentTarget.value)}
                  />
                </label>
                <button class="secondary-action" type="button" onClick={submitProfileEdits}>
                  <Save size={17} aria-hidden="true" />
                  <span>Save profile</span>
                </button>
              </div>
              <div class="starter-profile profile-editor credential-editor">
                <div class="section-header">
                  <div>
                    <div class="panel-kicker">Application identity</div>
                    <h2>Portal login defaults</h2>
                  </div>
                  <KeyRound size={20} aria-hidden="true" />
                </div>
                <p class="fine-print">
                  Passwords are encrypted by Electron Main and never exposed back to the renderer.
                  {state.profile?.applicationPasswordConfigured ? " A password is configured." : " No password is configured."}
                </p>
                <label>
                  <span>Application email</span>
                  <input
                    type="email"
                    value={form.profileApplicationEmail}
                    autocomplete="username"
                    onInput={(event) => setForm("profileApplicationEmail", event.currentTarget.value)}
                  />
                </label>
                <label>
                  <span>Application password</span>
                  <input
                    type="password"
                    value={form.profileApplicationPassword}
                    autocomplete="new-password"
                    onInput={(event) => setForm("profileApplicationPassword", event.currentTarget.value)}
                  />
                </label>
                <label class="toggle-row">
                  <input
                    type="checkbox"
                    checked={form.profileGmailOtpEnabled}
                    onChange={(event) => setForm("profileGmailOtpEnabled", event.currentTarget.checked)}
                  />
                  <span>Use Gmail OTP extraction for this inbox</span>
                </label>
                <p class="fine-print">Password policy: 12 or more characters with lowercase, uppercase, number, and symbol.</p>
                <button
                  class="secondary-action"
                  type="button"
                  disabled={!form.profileApplicationEmail.trim() || !applicationPasswordIsValid(form.profileApplicationPassword)}
                  onClick={submitApplicationCredentials}
                >
                  <ShieldCheck size={17} aria-hidden="true" />
                  <span>Save application identity</span>
                </button>
              </div>
              <Show when={state.canonicalProfile}>
                {(canonicalProfile) => (
                  <div class="structured-profile">
                    <div class="panel-kicker">Structured facts</div>
                    <div class="portal-workflow-grid">
                      <span>Experience</span>
                      <strong>{canonicalProfile().experience.length}</strong>
                      <span>Projects</span>
                      <strong>{canonicalProfile().projects.length}</strong>
                      <span>Education</span>
                      <strong>{canonicalProfile().education.length}</strong>
                      <span>Certifications</span>
                      <strong>{canonicalProfile().certifications.length}</strong>
                    </div>
                    <Show when={canonicalProfile().experience[0]}>
                      {(experience) => (
                        <div class="diagnostic-line">
                          <span />
                          <p>
                            {experience().title} at {experience().company}
                          </p>
                        </div>
                      )}
                    </Show>
                    <Show when={canonicalProfile().projects[0]}>
                      {(project) => (
                        <div class="diagnostic-line">
                          <span />
                          <p>{project().name}</p>
                        </div>
                      )}
                    </Show>
                    <Show when={canonicalProfile().skillGroups.length > 0}>
                      <div class="workflow-chip-row" aria-label="Verified profile skills">
                        <For each={canonicalProfile().skillGroups.flatMap((group) => group.skills).slice(0, 10)}>
                          {(skill) => <span>{skill}</span>}
                        </For>
                      </div>
                    </Show>
                  </div>
                )}
              </Show>
              <div class="settings-actions">
                <div class="panel-kicker">Automation concurrency</div>
                <div class="segmented-control" aria-label="Maximum concurrent application runs">
                  <button
                    classList={{ active: Number(state.settings["automation.maxConcurrentApplications"] ?? 2) === 1 }}
                    type="button"
                    onClick={() => void setMaxConcurrentApplications(1)}
                  >
                    1
                  </button>
                  <button
                    classList={{ active: Number(state.settings["automation.maxConcurrentApplications"] ?? 2) === 2 }}
                    type="button"
                    onClick={() => void setMaxConcurrentApplications(2)}
                  >
                    2
                  </button>
                  <button
                    classList={{ active: Number(state.settings["automation.maxConcurrentApplications"] ?? 2) === 3 }}
                    type="button"
                    onClick={() => void setMaxConcurrentApplications(3)}
                  >
                    3
                  </button>
                </div>
                <p class="fine-print">Hard cap: 3 concurrent browser runs.</p>
                <button class="secondary-action" type="button" onClick={() => void chooseOutputDir()}>
                  <FolderOpen size={17} aria-hidden="true" />
                  <span>Choose output folder</span>
                </button>
                <p class="fine-print">Output: {String(state.settings["files.outputDir"] ?? "Downloads")}</p>
              </div>
            </Show>
          </div>
        </section>
      </main>
    </>
  );
};
