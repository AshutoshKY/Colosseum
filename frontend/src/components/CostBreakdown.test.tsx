import { describe, expect, it } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import { CostBreakdown, formatCost, formatTokens } from './CostBreakdown'
import type { Cell, RunDetail } from '../types'

describe('CostBreakdown Component', () => {
  const mockCells: Cell[] = [
    {
      document_id: 1,
      document_name: 'claim_123.pdf',
      model_id: 'openrouter/openai/gpt-5.6-luna-pro',
      task: 'cheque_bank',
      status: 'succeeded',
      cost_usd: 0.0125,
      cost_breakdown: {
        input_usd: 0.005,
        output_usd: 0.006,
        cache_usd: 0.0005,
        thinking_usd: 0.001,
        total_usd: 0.0125,
      },
      usage: {
        input_tokens: 15000,
        output_tokens: 2000,
        cached_tokens: 5000,
        thinking_tokens: 1000,
        total_tokens: 18000,
      },
      latency_ms: 3200,
    },
    {
      document_id: 1,
      document_name: 'claim_123.pdf',
      model_id: 'openrouter/xiaomi/mimo-v2.5',
      task: 'cheque_bank',
      status: 'succeeded',
      cost_usd: 0.0035,
      cost_breakdown: {
        input_usd: 0.0015,
        output_usd: 0.002,
        cache_usd: 0.0,
        thinking_usd: 0.0,
        total_usd: 0.0035,
      },
      usage: {
        input_tokens: 12000,
        output_tokens: 1800,
        cached_tokens: 0,
        thinking_tokens: 0,
        total_tokens: 13800,
      },
      latency_ms: 1800,
    },
    {
      document_id: 2,
      document_name: 'claim_456.pdf',
      model_id: 'openrouter/openai/gpt-5.6-luna-pro',
      task: 'opd_bill',
      status: 'succeeded',
      cost_usd: 0.0240,
      cost_breakdown: {
        input_usd: 0.010,
        output_usd: 0.012,
        cache_usd: 0.001,
        thinking_usd: 0.001,
        total_usd: 0.0240,
      },
      usage: {
        input_tokens: 30000,
        output_tokens: 4000,
        cached_tokens: 8000,
        thinking_tokens: 2000,
        total_tokens: 36000,
      },
      latency_ms: 5400,
    },
  ]

  const mockRunDetail: RunDetail = {
    run: {
      run_id: 58,
      name: 'opd-gpt-5.6-luna-pro+2-cheque-bank-08-13',
      pack: 'OPD',
      status: 'completed',
      created_at: '2026-08-13T10:00:00Z',
      counts: { total: 3, succeeded: 3, failed: 0, skipped: 0, pending: 0 },
      spec: {
        name: 'test-run',
        pack: 'OPD',
        variant: null,
        selected_tasks: ['cheque_bank', 'opd_bill'],
        document_ids: [1, 2],
        model_ids: ['openrouter/openai/gpt-5.6-luna-pro', 'openrouter/xiaomi/mimo-v2.5'],
        upstream_mode: 'gold',
        prompt_overrides: {},
        runtime_overrides: {},
        concurrency: { global: 4, per_provider: {} },
        judge: { enabled: false, model_id: '', modes: [] },
        compression: { enabled: false, max_megapixels: 4, max_image_mb: null },
        confirm_large: false,
      },
      cost_usd: 0.0400,
    },
    cells: mockCells,
  }

  it('formats currency correctly for USD and INR', () => {
    expect(formatCost(0.0125, 'USD')).toBe('$0.0125')
    expect(formatCost(1.5, 'USD')).toBe('$1.50')
    expect(formatCost(0.0125, 'INR', 87.5)).toBe('₹1.09')
    expect(formatCost(0.001, 'INR', 87.5)).toBe('₹0.088')
    expect(formatCost(0, 'USD')).toBe('$0.00')
    expect(formatCost(0, 'INR')).toBe('₹0.00')
  })

  it('formats token counts with thousand separators', () => {
    expect(formatTokens(18000)).toBe('18,000')
    expect(formatTokens(1248500)).toBe('1,248,500')
    expect(formatTokens(0)).toBe('0')
  })

  it('renders KPI summary cards and model segregation table', () => {
    const { getByText, getAllByText } = render(
      <CostBreakdown runDetail={mockRunDetail} cells={mockCells} />
    )

    // Total Cost KPI card
    expect(getByText('Total Run Cost')).toBeDefined()
    expect(getAllByText('$0.0400').length).toBeGreaterThan(0)

    // Total Tokens KPI card (18000 + 13800 + 36000 = 67800)
    expect(getAllByText('Total Tokens').length).toBeGreaterThan(0)
    expect(getAllByText('67,800').length).toBeGreaterThan(0)

    // Model names in segregation table
    expect(getAllByText('gpt-5.6-luna-pro').length).toBeGreaterThan(0)
    expect(getAllByText('mimo-v2.5').length).toBeGreaterThan(0)
  })

  it('switches currency to INR and updates display values', () => {
    const { getByText, getAllByText } = render(
      <CostBreakdown runDetail={mockRunDetail} cells={mockCells} />
    )

    const inrButton = getByText(/INR \(₹\)/i)
    fireEvent.click(inrButton)

    // Total cost in INR: 0.04 * 87.5 = 3.50
    expect(getAllByText(/₹3.50/i).length).toBeGreaterThan(0)
  })

  it('switches between segregation tabs', () => {
    const { getByText, getAllByText } = render(
      <CostBreakdown runDetail={mockRunDetail} cells={mockCells} />
    )

    // Switch to By Agent view
    const agentBtn = getByText(/By Agent/i)
    fireEvent.click(agentBtn)
    expect(getByText('Agent Cost Segregation')).toBeDefined()
    expect(getAllByText('cheque bank').length).toBeGreaterThan(0)
    expect(getAllByText('opd bill').length).toBeGreaterThan(0)

    // Switch to By Document view
    const docBtn = getByText(/By Document/i)
    fireEvent.click(docBtn)
    expect(getByText('Document Cost Segregation')).toBeDefined()
    expect(getAllByText('claim_123.pdf').length).toBeGreaterThan(0)
    expect(getAllByText('claim_456.pdf').length).toBeGreaterThan(0)

    // Switch to By Individual Call view
    const callBtn = getByText(/By Individual Call/i)
    fireEvent.click(callBtn)
    expect(getByText('Search Calls')).toBeDefined()
  })
})
