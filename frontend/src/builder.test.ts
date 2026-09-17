import { describe, expect, it, vi } from 'vitest'
import { goldDependencies, includeDependencies, initialRunSpec, resizeBuilderColumns } from './builder'
import type { PackMeta, RunSpec } from './types'

const runtime = {model_id:null,thinking_budget:null,thinking_level:null,max_output_tokens:null,timeout_s:null}
const pack: PackMeta = {name:'OPD',order:['segregation','nme_analysis','audit'],tasks:[
  {name:'segregation',deterministic:false,depends_on:[],reference_runtime:runtime,gold_feed_keys:[]},
  {name:'nme_analysis',deterministic:false,depends_on:['segregation'],reference_runtime:runtime,gold_feed_keys:['segregation']},
  {name:'audit',deterministic:false,depends_on:['segregation','nme_analysis'],reference_runtime:runtime,gold_feed_keys:['segregation','nme_analysis']},
]}

describe('Run Builder assembly', () => {
  it('derives unselected dependency gold chips and recursively includes model dependencies', () => {
    expect(goldDependencies(pack.tasks,['segregation','audit'])).toEqual({audit:['segregation','nme_analysis']})
    expect(goldDependencies([{...pack.tasks[0],gold_context_keys:['policy']}],['segregation'])).toEqual({segregation:['policy']})
    expect(includeDependencies(pack,['audit'])).toEqual(['segregation','nme_analysis','audit'])
  })
  it('assembles the pinned RunSpec shape without extra fields', () => {
    vi.setSystemTime(new Date('2026-07-10T10:00:00Z'))
    const actual: RunSpec = {...initialRunSpec(),name:'seg-audit-bulk-2026-07-10',selected_tasks:['segregation','audit'],document_ids:[1,2,3],model_ids:['gemini-2.5-flash','bedrock-claude-sonnet-4-5','qwen3-vl-8b'],prompt_overrides:{audit:{system_prompt:'system',instruction_template:'instruction'}},runtime_overrides:{audit:{model_id:null,thinking_budget:4096,thinking_level:null,max_output_tokens:16000,timeout_s:300}}}
    expect(JSON.stringify(actual)).toBe(JSON.stringify({name:'seg-audit-bulk-2026-07-10',pack:'OPD',variant:null,selected_tasks:['segregation','audit'],document_ids:[1,2,3],model_ids:['gemini-2.5-flash','bedrock-claude-sonnet-4-5','qwen3-vl-8b'],upstream_mode:'gold',prompt_overrides:{audit:{system_prompt:'system',instruction_template:'instruction'}},runtime_overrides:{audit:{model_id:null,thinking_budget:4096,thinking_level:null,max_output_tokens:16000,timeout_s:300}},concurrency:{global:16,per_provider:{vertex_ai:4,vertex_partner:4,openai_compatible:8,openrouter:8,bedrock:4,xai:2}},judge:{enabled:true,model_id:'gemini-3.1-pro',modes:['gold_grade','head_to_head']},compression:{enabled:false,max_megapixels:4,max_image_mb:null},confirm_large:false}))
  })
  it('resizes adjacent builder panes without shrinking either below its usable minimum', () => {
    expect(resizeBuilderColumns([1, 1, 1, 1], 0, 100, 400)).toEqual([1.25, 0.75, 1, 1])
  })
})
