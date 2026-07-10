import { useState } from 'react'
import type { JudgeMode } from '../types'
import { ErrorBox } from './common'

export function JudgePanel({onRun, busy, error}: {onRun: (model: string, modes: JudgeMode[]) => void; busy?: boolean; error?: Error | null}) {
  const [model, setModel] = useState('gemini-3.1-pro'); const [modes, setModes] = useState<JudgeMode[]>(['gold_grade'])
  const toggle = (mode: JudgeMode) => setModes(modes.includes(mode) ? modes.filter(value => value !== mode) : [...modes, mode])
  return <div><div className="form-grid"><label>Judge model<input value={model} onChange={event => setModel(event.target.value)}/></label><fieldset><legend>Modes</legend>{(['gold_grade','doc_grade','head_to_head'] as JudgeMode[]).map(mode => <label key={mode}><input type="checkbox" checked={modes.includes(mode)} onChange={() => toggle(mode)}/>{mode.replaceAll('_',' ')}</label>)}</fieldset></div><button disabled={busy || !modes.length} onClick={() => onRun(model, modes)}>Run judge</button><ErrorBox error={error}/></div>
}
