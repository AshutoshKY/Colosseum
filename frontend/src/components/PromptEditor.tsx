import type { Prompt } from '../types'

export function PromptEditor({baseline, value, onChange}: {baseline?: Prompt; value?: {system_prompt: string; instruction_template: string}; onChange: (value?: {system_prompt: string; instruction_template: string}) => void}) {
  const current = value ?? {system_prompt: baseline?.system_prompt ?? '', instruction_template: baseline?.instruction_template ?? ''}
  return <div className="prompt-editor">
    <div className="row between"><p className="muted">Run-only override. Permanent versions live in Prompts.</p>{value && <button type="button" className="ghost" onClick={() => onChange(undefined)}>Reset baseline</button>}</div>
    <div className="split">
      <label>Baseline system<textarea readOnly value={baseline?.system_prompt ?? ''} /></label>
      <label>Run system<textarea value={current.system_prompt} onChange={event => onChange({...current, system_prompt: event.target.value})} /></label>
      <label>Baseline instruction<textarea readOnly value={baseline?.instruction_template ?? ''} /></label>
      <label>Run instruction<textarea value={current.instruction_template} onChange={event => onChange({...current, instruction_template: event.target.value})} /></label>
    </div>
  </div>
}
