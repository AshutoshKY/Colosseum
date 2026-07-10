import { describe, expect, it, vi } from 'vitest'
import { subscribeToRun } from './sse'

class FakeSource {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  static instance: FakeSource
  constructor(public url: string) { FakeSource.instance = this }
  addEventListener() {}
  close = vi.fn()
}

describe('SSE progress', () => {
  it('closes and requests polling fallback when EventSource errors', () => {
    const fallback = vi.fn(); subscribeToRun('12',vi.fn(),fallback,FakeSource as unknown as typeof EventSource)
    expect(FakeSource.instance.url).toBe('/api/runs/12/events')
    FakeSource.instance.onerror?.()
    expect(FakeSource.instance.close).toHaveBeenCalledOnce()
    expect(fallback).toHaveBeenCalledOnce()
  })
})
