import { useState } from 'react'
import { useCatalog } from '../api/hooks'
import type { JudgeMode } from '../types'
import { ErrorBox } from './common'
import { JudgeModelPicker } from './JudgeModelPicker'

export function JudgePanel({onRun, busy, error}: {onRun: (model: string, modes: JudgeMode[]) => void; busy?: boolean; error?: Error | null}) {
  const catalog = useCatalog()
  const [model, setModel] = useState('gemini-3.1-pro'); const [modes, setModes] = useState<JudgeMode[]>(['gold_grade'])
  const toggle = (mode: JudgeMode) => setModes(modes.includes(mode) ? modes.filter(value => value !== mode) : [...modes, mode])
  return <div className="judge-controls"><div className="form-grid"><JudgeModelPicker models={catalog.data ?? []} value={model} onChange={setModel}/><fieldset><legend>Evaluation modes</legend>{(['gold_grade','doc_grade','head_to_head'] as JudgeMode[]).map(mode => <label key={mode}><input type="checkbox" checked={modes.includes(mode)} onChange={() => toggle(mode)}/><span><strong>{mode === 'gold_grade' ? 'Gold standard' : mode === 'doc_grade' ? 'Document grade' : 'Head to head'}</strong><small>{mode === 'gold_grade' ? 'Compare each result with the approved answer.' : mode === 'doc_grade' ? 'Assess each result against the source document.' : 'Rank the models anonymously for this document.'}</small></span></label>)}</fieldset></div><button className="primary" disabled={busy || !modes.length} onClick={() => onRun(model, modes)}>{busy ? 'Starting judge…' : 'Run judge'}</button><ErrorBox error={error}/></div>
}
