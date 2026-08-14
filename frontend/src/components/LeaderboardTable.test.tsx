import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { AccuracyCostChart, LeaderboardTable } from './LeaderboardTable'

describe('LeaderboardTable and AccuracyCostChart', () => {
  const mockRows = [
    {
      task: 'segregation',
      model: 'openrouter/qwen/qwen3.6-plus',
      accuracy: 37.5,
      valid_percent: 100.0,
      win_rate: 0,
      cost_per_doc: 0.0240,
      median_latency_ms: 87485,
      composite: 0.63,
    },
  ]

  it('renders leaderboard table correctly', () => {
    const { getByText } = render(<LeaderboardTable rows={mockRows} />)
    expect(getByText('openrouter/qwen/qwen3.6-plus')).toBeDefined()
    expect(getByText('37.5%')).toBeDefined()
  })

  it('renders scatter chart without text overflow and with SVG axes', () => {
    const { getByRole, getByText } = render(<AccuracyCostChart rows={mockRows} />)
    const svg = getByRole('img', { name: /Accuracy versus cost scatter chart/i })
    expect(svg).toBeDefined()
    expect(getByText('openrouter/qwen/qwen3.6-plus')).toBeDefined()
    expect(getByText('Accuracy ↑')).toBeDefined()
    expect(getByText('Cost / doc ($) →')).toBeDefined()
  })
})
