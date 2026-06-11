import { For, Show, onMount } from 'solid-js'
import { FileText, FolderOpen, ShieldCheck, Upload, Wrench } from 'lucide-solid'
import { EmptyState } from '../components/EmptyState'
import { useProfileStore } from '../contexts/ProfileStore'
import { buildAnchorRepairEditorModel } from '../features/documents/anchorRepairEditor'
import { buildEditableMasterDiagnostics } from '../features/documents/documentDiagnostics'
import { gsap } from '../animations/gsap'

export default function DocumentsScreen() {
  const {
    state,
    pickAndRegisterResume,
    pickAndRegisterSupportingDetails,
    pickAndRegisterCoverLetter,
    confirmEditableMaster,
    repairEditableMasterAnchors,
    openLocalPath,
  } = useProfileStore()
  let listRef: HTMLDivElement | undefined

  onMount(() => {
    if (listRef) {
      gsap.from(listRef.querySelectorAll('[data-list-item]'), {
        y: 12, opacity: 0, duration: 0.35, stagger: 0.04, ease: 'expo.out',
      })
    }
  })

  const parsedDocumentForFile = (uploadedFileId: string) =>
    state.parsedDocuments.find((d) => d.uploadedFileId === uploadedFileId) ?? null

  return (
    <section class="uploads-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
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
          <EmptyState
            icon={FileText}
            title="No source files yet"
            description="PDF sources require converted DOCX review before automated tailoring."
            action={{ label: 'Upload resume', onClick: () => void pickAndRegisterResume() }}
          />
        }
      >
        <div class="queue-list" ref={listRef}>
          <For each={state.uploadedFiles}>
            {(file) => {
              const parsed = parsedDocumentForFile(file.id)
              return (
                <div class="upload-row" data-list-item>
                  <div class="upload-summary">
                    <span>{file.status}</span>
                    <strong>{file.originalName}</strong>
                    <Show when={parsed}>
                      {(parsedDoc) => {
                        const diagnostics = buildEditableMasterDiagnostics(parsedDoc())
                        const repairModel = buildAnchorRepairEditorModel(parsedDoc())
                        return (
                          <div class="document-parse-meta">
                            <div
                              class="confidence-meter"
                              aria-label={`Parser confidence ${Math.round(parsedDoc().confidence * 100)} percent`}
                            >
                              <span style={{ width: `${Math.round(parsedDoc().confidence * 100)}%` }} />
                            </div>
                            <small>
                              {parsedDoc().canonical.sections.length} sections / {diagnostics.structuralAnchorCount} structural anchors /{' '}
                              {diagnostics.warningCount} warnings
                            </small>
                            <div class={`anchor-diagnostics anchor-diagnostics-${diagnostics.mutationReadiness}`}>
                              <span>{diagnostics.summary}</span>
                              <Show when={diagnostics.placeholderPreview.length > 0}>
                                <code>{diagnostics.placeholderPreview.join(', ')}</code>
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
                        )
                      }}
                    </Show>
                  </div>
                  <div class="control-row">
                    <button
                      class="icon-button"
                      type="button"
                      aria-label="Open local file"
                      onClick={() => void openLocalPath(file.localPath)}
                    >
                      <FolderOpen size={16} aria-hidden="true" />
                    </button>
                    <Show when={file.status === 'UNVERIFIED_EDITABLE_MASTER'}>
                      <button
                        class="icon-button"
                        type="button"
                        aria-label="Confirm editable master"
                        onClick={() => void confirmEditableMaster(file.id)}
                      >
                        <ShieldCheck size={16} aria-hidden="true" />
                      </button>
                    </Show>
                    <Show
                      when={
                        file.fileKind === 'RESUME' &&
                        (file.sourceFormat === 'DOCX' || file.sourceFormat === 'TEX') &&
                        parsed &&
                        buildEditableMasterDiagnostics(parsed).mutationReadiness === 'needs_anchor_repair'
                      }
                    >
                      <button
                        class="icon-button"
                        type="button"
                        aria-label="Create anchor repair candidate"
                        onClick={() => void repairEditableMasterAnchors(file.id)}
                      >
                        <Wrench size={16} aria-hidden="true" />
                      </button>
                    </Show>
                  </div>
                </div>
              )
            }}
          </For>
        </div>
      </Show>
    </section>
  )
}
