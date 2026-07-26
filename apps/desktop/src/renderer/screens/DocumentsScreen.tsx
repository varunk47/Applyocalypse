import { createMemo, createResource, For, Show } from 'solid-js'
import type { GeneratedFile } from '@applyocalypse/shared-types'
import { useProfileStore } from '../contexts/ProfileStore'
import { jobLabel, useQueueStore } from '../contexts/QueueStore'
import { buildAnchorRepairEditorModel } from '../features/documents/anchorRepairEditor'
import { buildEditableMasterDiagnostics } from '../features/documents/documentDiagnostics'

const statusTag = (status: string): { text: string; ok: boolean } => {
  if (status === 'VERIFIED_EDITABLE_MASTER') return { text: 'MASTER ✓', ok: true }
  if (status === 'UNVERIFIED_EDITABLE_MASTER') return { text: 'NEEDS CONFIRM', ok: false }
  if (status === 'IMMUTABLE_SOURCE') return { text: 'SOURCE', ok: true }
  return { text: status.replace(/_/g, ' '), ok: false }
}

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
  const { state: queueState } = useQueueStore()

  const [generated, { refetch: refetchGenerated }] = createResource(
    async () => (await window.applyocalypse.documents.listGenerated(50)).items,
    { initialValue: [] as GeneratedFile[] }
  )

  const parsedDocumentForFile = (uploadedFileId: string) =>
    state.parsedDocuments.find((d) => d.uploadedFileId === uploadedFileId) ?? null

  const coverLetterFiles = createMemo(() => state.uploadedFiles.filter((f) => f.fileKind === 'COVER_LETTER'))
  const masterFiles = createMemo(() => state.uploadedFiles.filter((f) => f.fileKind !== 'COVER_LETTER'))

  const generatedJobLabel = (file: GeneratedFile) => jobLabel(queueState.jobTargetMap[file.jobTargetId], file.jobTargetId)

  return (
    <section class="screen screen-scroll" data-gsap="panel" data-view-panel>
      <div class="screen-pad">
        <h1 class="screen-headline" style={{ 'font-size': '30px' }}>Documents</h1>
        <p class="screen-sub">Masters stay yours, byte for byte. Tailored copies do the traveling.</p>

        <div class="docs-grid">
          {/* Left: master sources */}
          <div class="docs-col">
            <div class="rule-row">
              <span class="kicker">MASTER SOURCES</span>
              <span class="rule" />
              <button class="btn-mono" type="button" onClick={() => void pickAndRegisterResume()}>+ RESUME</button>
              <button class="btn-mono" type="button" onClick={() => void pickAndRegisterSupportingDetails()}>+ DETAILS</button>
              <button class="btn-mono" type="button" onClick={() => void pickAndRegisterCoverLetter()}>+ COVER SAMPLE</button>
            </div>

            <Show
              when={masterFiles().length > 0}
              fallback={
                <button class="dropzone" type="button" onClick={() => void pickAndRegisterResume()}>
                  <span class="serif-title">Hand over the master copy</span>
                  <span style={{ 'font-size': '11.5px', color: 'var(--ink-2)' }}>
                    Upload your résumé (DOCX preferred). It never leaves this machine.
                  </span>
                </button>
              }
            >
              <For each={masterFiles()}>
                {(file) => {
                  const parsed = () => parsedDocumentForFile(file.id)
                  return (
                    <div class="paper-card section-card">
                      <div style={{ display: 'flex', 'align-items': 'center', gap: '10px' }}>
                        <span class="doc-glyph" aria-hidden="true" />
                        <button
                          type="button"
                          style={{ font: '500 12px var(--mono)', overflow: 'hidden', 'text-overflow': 'ellipsis', 'white-space': 'nowrap' }}
                          onClick={() => void openLocalPath(file.localPath)}
                          title="Open local file"
                        >
                          {file.originalName}
                        </button>
                        <span
                          class="field-state"
                          classList={{ applied: statusTag(file.status).ok, yours: !statusTag(file.status).ok }}
                          style={{ 'margin-left': 'auto' }}
                        >
                          <Show when={parsed()} fallback={statusTag(file.status).text}>
                            {(doc) => `PARSED · ${Math.round(doc().confidence * 100)}% CONF`}
                          </Show>
                        </span>
                      </div>

                      <Show when={parsed()}>
                        {(doc) => {
                          const diagnostics = () => buildEditableMasterDiagnostics(doc())
                          const repairModel = () => buildAnchorRepairEditorModel(doc())
                          return (
                            <>
                              <div class="kicker">ANCHOR MAP</div>
                              <div class="anchor-map">
                                <For each={repairModel().zones.slice(0, 5)}>
                                  {(zone) => (
                                    <div
                                      class="anchor-zone"
                                      classList={{
                                        ready: zone.status === 'ready',
                                        repairable: zone.status === 'repairable',
                                        review: zone.status === 'review_only',
                                      }}
                                      style={{ flex: String(1 + zone.confidence) }}
                                      title={zone.placeholder ?? zone.sourceHint ?? zone.label}
                                    >
                                      {zone.label.toUpperCase().slice(0, 12)}
                                    </div>
                                  )}
                                </For>
                              </div>
                              <div class="anchor-legend">
                                <span><span class="legend-swatch ready" />READY</span>
                                <span><span class="legend-swatch repairable" />REPAIRABLE</span>
                                <span><span class="legend-swatch review" />REVIEW-ONLY</span>
                              </div>
                              <div style={{ 'font-size': '11px', color: 'var(--ink-2)' }}>{diagnostics().summary}</div>
                              <div style={{ display: 'flex', gap: '8px', 'align-items': 'center', 'flex-wrap': 'wrap' }}>
                                <Show when={file.status === 'UNVERIFIED_EDITABLE_MASTER'}>
                                  <button class="btn-outline-wax" type="button" onClick={() => void confirmEditableMaster(file.id)}>
                                    Confirm as master
                                  </button>
                                </Show>
                                <Show when={diagnostics().mutationReadiness === 'needs_anchor_repair'}>
                                  <button class="btn-outline-wax" type="button" onClick={() => void repairEditableMasterAnchors(file.id)}>
                                    Create anchored candidate
                                  </button>
                                  <span style={{ 'font-size': '10.5px', color: 'var(--ink-3)' }}>
                                    the original is never modified
                                  </span>
                                </Show>
                              </div>
                            </>
                          )
                        }}
                      </Show>
                    </div>
                  )
                }}
              </For>
            </Show>

            <For each={coverLetterFiles()}>
              {(file) => (
                <div class="paper-card section-card">
                  <div style={{ display: 'flex', 'align-items': 'center', gap: '10px' }}>
                    <span class="doc-glyph" aria-hidden="true" />
                    <button
                      type="button"
                      style={{ font: '500 12px var(--mono)' }}
                      onClick={() => void openLocalPath(file.localPath)}
                      title="Open local file"
                    >
                      {file.originalName}
                    </button>
                    <span class="field-state applied" style={{ 'margin-left': 'auto' }}>VOICE LOCKED ✓</span>
                  </div>
                  <div style={{ 'font-size': '10.5px', color: 'var(--ink-3)' }}>
                    Every letter is measured against this. Sounds like you, or it doesn't ship.
                  </div>
                </div>
              )}
            </For>

            <div class="validators-note">
              HOUSE VALIDATORS: ONE PAGE · BANNED WORDS · EM-DASH GATE — ALL BLOCKING
            </div>
          </div>

          {/* Right: tailored output */}
          <div class="docs-col">
            <div class="rule-row">
              <span class="kicker">TAILORED OUTPUT</span>
              <span class="rule" />
              <button class="btn-mono" type="button" onClick={() => void refetchGenerated()}>REFRESH</button>
              <span class="provenance-tag">EXPORT: PDF VIA LOCAL CONVERTER</span>
            </div>
            <Show
              when={generated().length > 0}
              fallback={
                <div class="empty-state">
                  <span>{generated.loading ? 'Loading tailored documents...' : 'Tailored copies appear here as missions run. Paste a job link on Missions to start one.'}</span>
                </div>
              }
            >
              <div class="paper-card" style={{ overflow: 'hidden' }}>
                <For each={generated()}>
                  {(file, index) => (
                    <button
                      class="tailored-row"
                      type="button"
                      style={{ 'animation-delay': `${index() * 0.06}s` }}
                      onClick={() => void openLocalPath(file.localPath)}
                    >
                      <span class="doc-glyph" aria-hidden="true" />
                      <span style={{ flex: '1', 'min-width': '0', 'text-align': 'left' }}>
                        <span style={{ display: 'block', font: '500 11.5px var(--mono)', overflow: 'hidden', 'text-overflow': 'ellipsis', 'white-space': 'nowrap' }}>
                          {file.filename}
                        </span>
                        <span style={{ display: 'block', font: '500 12px var(--sans)', color: 'var(--ink-2)' }}>
                          {generatedJobLabel(file)}
                        </span>
                      </span>
                      <span class="mono-chip">{file.format}</span>
                      <span class="artifact-check">{file.fileKind === 'RESUME' ? '1 PAGE ✓' : 'VOICE ✓'}</span>
                    </button>
                  )}
                </For>
              </div>
            </Show>
          </div>
        </div>
      </div>
    </section>
  )
}
