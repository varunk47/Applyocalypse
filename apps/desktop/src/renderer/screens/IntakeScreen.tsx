import { createMemo, createSignal } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { Send } from 'lucide-solid'
import { useProfileStore } from '../contexts/ProfileStore'
import { useQueueStore } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'
import { parseJobIntake } from '../features/intake/parseJobIntake'

export default function IntakeScreen() {
  const { state: profileState } = useProfileStore()
  const { enqueueJobText } = useQueueStore()
  const { loadRunDetail } = useRunStore()
  const navigate = useNavigate()

  const [jobInput, setJobInput] = createSignal('')
  const [autoSubmit, setAutoSubmit] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)

  const detectedUrls = createMemo(() =>
    parseJobIntake(jobInput())
      .filter((item) => item.sourceKind === 'URL')
      .map((item) => item.sourceValue)
  )

  const lineCount = createMemo(() => jobInput().split('\n').filter((l) => l.trim()).length)

  const handleSubmit = async () => {
    const profileId = profileState.profile?.id
    if (!profileId) {
      setError('Create a profile before adding job targets.')
      return
    }
    setError(null)
    await enqueueJobText(jobInput(), profileId, {
      autoSubmitEnabled: autoSubmit(),
      onRunReady: async (runId) => {
        await loadRunDetail(runId)
        setJobInput('')
        navigate('/run')
      },
    })
  }

  return (
    <section class="intake-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      <div class="section-header">
        <div>
          <div class="panel-kicker">Job intake</div>
          <h2>Paste links or descriptions</h2>
        </div>
        <button
          class="icon-button"
          type="button"
          aria-label="Send intake"
          disabled={!jobInput().trim()}
          onClick={() => void handleSubmit()}
        >
          <Send size={17} aria-hidden="true" />
        </button>
      </div>

      <textarea
        spellcheck={false}
        value={jobInput()}
        onInput={(e) => setJobInput(e.currentTarget.value)}
        placeholder={
          'Paste one job link per line, or paste a full job description.\n' +
          'Example:\nhttps://jobs.company.com/apply/12345\nhttps://boards.greenhouse.io/company/jobs/98765'
        }
        style={{ 'min-height': '160px' }}
      />

      <div class="intake-meta">
        <span class="metric" style={{ 'font-size': '0.72rem' }}>
          {lineCount()} {lineCount() === 1 ? 'entry' : 'entries'}
        </span>
      </div>

      {detectedUrls().length > 0 && (
        <div class="workflow-chip-row" aria-label="Detected URLs">
          {detectedUrls().map((url) => (
            <span title={url}>{new URL(url).hostname}</span>
          ))}
        </div>
      )}

      {error() && <div class="error-box">{error()}</div>}

      <label class="automation-option">
        <input
          type="checkbox"
          checked={autoSubmit()}
          onChange={(e) => setAutoSubmit(e.currentTarget.checked)}
        />
        <span>
          <strong>Auto-submit after review</strong>
          <small>Confirmation still has to be detected before success is recorded.</small>
        </span>
      </label>
    </section>
  )
}
