import { useRunBuilder } from '../context/RunBuilderContext'
import { useTheme, type ThemePreference } from '../theme'
import type { JudgeMode } from '../types'
import { Card } from '../components/common'

const JUDGE_MODES: JudgeMode[] = ['gold_grade', 'doc_grade', 'head_to_head']
const THEMES: Array<{ value: ThemePreference; label: string }> = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]

export default function Settings() {
  const { spec, setSpec } = useRunBuilder()
  const { preference, setPreference } = useTheme()

  const compression = spec.compression
  const concurrency = spec.concurrency
  const judge = spec.judge

  const update = <K extends 'compression' | 'concurrency' | 'judge'>(key: K, value: typeof spec[K]) =>
    setSpec(current => ({ ...current, [key]: value }))

  return (
    <div className="settings-layout">
      <header className="page-title">
        <div>
          <span className="eyebrow">Preferences</span>
          <h1>Settings</h1>
          <p>Run defaults apply to the current draft in the builder and are remembered for future runs on this browser.</p>
        </div>
      </header>

      <Card>
        <h2>Appearance</h2>
        <div className="setting-row">
          <div>
            <strong>Theme</strong>
            <p>System follows your operating system preference.</p>
          </div>
          <div className="segmented">
            {THEMES.map(({ value, label }) => (
              <button key={value} className={preference === value ? 'active' : ''} onClick={() => setPreference(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <h2>Image compression</h2>
        <div className="setting-row">
          <div>
            <strong>Compress rasterized pages</strong>
            <p>
              Downscales each PDF page image for vision models before sending, so large scans fit small context
              windows (e.g. self-deployed Qwen3-VL, 26k tokens). Per-model catalog caps still apply — the smaller cap wins.
            </p>
          </div>
          <span className="switch">
            <input
              type="checkbox"
              checked={compression.enabled}
              aria-label="Enable image compression"
              onChange={event => update('compression', { ...compression, enabled: event.target.checked })}
            />
            <i />
          </span>
        </div>
        {compression.enabled && (
          <div className="setting-row">
            <div>
              <strong>Limits</strong>
              <p>Maximum megapixels per page and optional hard cap on the encoded image size.</p>
            </div>
            <div className="form-grid">
              <label>
                Max megapixels / page
                <input
                  type="number"
                  min="0.5"
                  step="0.5"
                  value={compression.max_megapixels}
                  onChange={event => update('compression', { ...compression, max_megapixels: Number(event.target.value) })}
                />
              </label>
              <label>
                Max image size (MB)
                <input
                  type="number"
                  min="0.5"
                  step="0.5"
                  placeholder="model default"
                  value={compression.max_image_mb ?? ''}
                  onChange={event =>
                    update('compression', { ...compression, max_image_mb: event.target.value ? Number(event.target.value) : null })
                  }
                />
              </label>
            </div>
          </div>
        )}
      </Card>

      <Card>
        <h2>Concurrency</h2>
        <div className="setting-row">
          <div>
            <strong>Parallel requests</strong>
            <p>Global ceiling plus per-provider limits. Lower these if a provider rate-limits your account.</p>
          </div>
          <div className="form-grid">
            <label>
              Global
              <input
                type="number"
                min="1"
                value={concurrency.global}
                onChange={event => update('concurrency', { ...concurrency, global: Number(event.target.value) })}
              />
            </label>
            {Object.entries(concurrency.per_provider).map(([provider, value]) => (
              <label key={provider}>
                {provider.replaceAll('_', ' ')}
                <input
                  type="number"
                  min="1"
                  value={value}
                  onChange={event =>
                    update('concurrency', {
                      ...concurrency,
                      per_provider: { ...concurrency.per_provider, [provider]: Number(event.target.value) },
                    })
                  }
                />
              </label>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <h2>LLM judge</h2>
        <div className="setting-row">
          <div>
            <strong>Judge results after each run</strong>
            <p>Grades model outputs against gold and each other once the run completes.</p>
          </div>
          <span className="switch">
            <input
              type="checkbox"
              checked={judge.enabled}
              aria-label="Enable LLM judge"
              onChange={event => update('judge', { ...judge, enabled: event.target.checked })}
            />
            <i />
          </span>
        </div>
        {judge.enabled && (
          <div className="setting-row">
            <div>
              <strong>Judge model & modes</strong>
              <p>gold grade scores against gold answers; doc grade against the document; head-to-head ranks models.</p>
            </div>
            <div>
              <label>
                Judge model
                <input value={judge.model_id} onChange={event => update('judge', { ...judge, model_id: event.target.value })} />
              </label>
              {JUDGE_MODES.map(mode => (
                <label key={mode}>
                  <input
                    type="checkbox"
                    checked={judge.modes.includes(mode)}
                    onChange={event =>
                      update('judge', {
                        ...judge,
                        modes: event.target.checked ? [...judge.modes, mode] : judge.modes.filter(item => item !== mode),
                      })
                    }
                  />
                  {mode.replaceAll('_', ' ')}
                </label>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
