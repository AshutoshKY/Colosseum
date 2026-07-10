import { describe, expect, it } from 'vitest'
import { verdictFor } from './JsonDiffTree'

describe('JSON verdict colors', () => {
  it('maps booleans and semantic verdicts to stable classes', () => {
    expect(verdictFor('a',{a:true})).toBe('match')
    expect(verdictFor('a',{a:false})).toBe('mismatch')
    expect(verdictFor('a',{a:'missing'})).toBe('missing')
    expect(verdictFor('b',{a:true})).toBe('neutral')
  })
})
