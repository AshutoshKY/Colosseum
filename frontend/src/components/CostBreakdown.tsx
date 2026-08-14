import { useMemo, useState } from 'react'
import type { Cell, RunDetail } from '../types'
import { Badge, badgeHue, Card, formatDuration } from './common'

export interface CostBreakdownProps {
  runDetail?: RunDetail
  cells?: Cell[]
}

type SegregationView = 'model' | 'agent' | 'doc' | 'calls'

export function formatCost(
  usdAmount: number | null | undefined,
  currency: 'USD' | 'INR' = 'USD',
  exchangeRate: number = 87.5,
  precision = 4,
): string {
  const val = Number(usdAmount ?? 0)
  if (currency === 'INR') {
    const inr = val * exchangeRate
    if (inr === 0) return '₹0.00'
    if (inr < 0.01) return `₹${inr.toFixed(4)}`
    if (inr < 1) return `₹${inr.toFixed(3)}`
    return `₹${inr.toFixed(2)}`
  }
  if (val === 0) return '$0.00'
  if (val < 0.001) return `$${val.toFixed(5)}`
  if (val < 1) return `$${val.toFixed(precision)}`
  return `$${val.toFixed(2)}`
}

export function formatTokens(count: number | null | undefined): string {
  const val = Math.round(Number(count ?? 0))
  return val.toLocaleString()
}

export function CostBreakdown({ runDetail, cells: propCells }: CostBreakdownProps) {
  const [currency, setCurrency] = useState<'USD' | 'INR'>('USD')
  const [exchangeRate, setExchangeRate] = useState<number>(87.5)
  const [isEditingRate, setIsEditingRate] = useState(false)
  const [tempRate, setTempRate] = useState('87.50')
  const [view, setView] = useState<SegregationView>('model')

  // Filters for individual calls view
  const [searchQuery, setSearchQuery] = useState('')
  const [filterModel, setFilterModel] = useState<string>('all')
  const [filterAgent, setFilterAgent] = useState<string>('all')
  const [filterDoc, setFilterDoc] = useState<string>('all')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [sortField, setSortField] = useState<'cost' | 'tokens' | 'latency' | 'doc' | 'agent'>('cost')
  const [sortAsc, setSortAsc] = useState(false)

  // Expandable state for Document view
  const [expandedDocs, setExpandedDocs] = useState<Record<string, boolean>>({})

  const cells: Cell[] = useMemo(() => {
    return propCells ?? runDetail?.cells ?? []
  }, [propCells, runDetail?.cells])

  // Extract unique options for filters
  const models = useMemo(() => Array.from(new Set(cells.map(c => c.model_id).filter(Boolean))).sort(), [cells])
  const agents = useMemo(() => Array.from(new Set(cells.map(c => c.task).filter(Boolean))).sort(), [cells])
  const documents = useMemo(() => {
    const map = new Map<number, string>()
    cells.forEach(c => {
      if (c.document_id) {
        map.set(c.document_id, c.document_name ?? c.document ?? `Document ${c.document_id}`)
      }
    })
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }))
  }, [cells])

  // Whole Run Summaries
  const totals = useMemo(() => {
    let costTotal = 0
    let costInput = 0
    let costOutput = 0
    let costCache = 0
    let costThinking = 0

    let tokensTotal = 0
    let tokensInput = 0
    let tokensOutput = 0
    let tokensCache = 0
    let tokensThinking = 0

    let succeeded = 0
    let failed = 0
    let skipped = 0

    cells.forEach(c => {
      const cb = c.cost_breakdown
      const u = c.usage
      const cellTotalCost = cb?.total_usd ?? c.cost_usd ?? 0

      costTotal += cellTotalCost
      costInput += cb?.input_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.4 : 0)
      costOutput += cb?.output_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.6 : 0)
      costCache += cb?.cache_usd ?? 0
      costThinking += cb?.thinking_usd ?? 0

      const inTok = u?.input_tokens ?? 0
      const outTok = u?.output_tokens ?? 0
      const cacheTok = u?.cached_tokens ?? 0
      const thinkTok = u?.thinking_tokens ?? 0
      const totTok = u?.total_tokens ?? (inTok + outTok + thinkTok)

      tokensInput += inTok
      tokensOutput += outTok
      tokensCache += cacheTok
      tokensThinking += thinkTok
      tokensTotal += totTok

      if (c.status === 'succeeded') succeeded++
      else if (c.status === 'failed') failed++
      else if (c.status === 'skipped') skipped++
    })

    const docCount = documents.length || 1
    const costPerDoc = costTotal / docCount
    const costPerCall = cells.length ? costTotal / cells.length : 0

    return {
      costTotal,
      costInput,
      costOutput,
      costCache,
      costThinking,
      tokensTotal,
      tokensInput,
      tokensOutput,
      tokensCache,
      tokensThinking,
      succeeded,
      failed,
      skipped,
      totalCalls: cells.length,
      docCount: documents.length,
      costPerDoc,
      costPerCall,
    }
  }, [cells, documents.length])

  // Model Segregation
  const modelStats = useMemo(() => {
    const map = new Map<string, {
      model_id: string
      total_cost_usd: number
      input_cost_usd: number
      output_cost_usd: number
      cache_cost_usd: number
      thinking_cost_usd: number
      total_tokens: number
      input_tokens: number
      output_tokens: number
      cached_tokens: number
      thinking_tokens: number
      call_count: number
      succeeded: number
      failed: number
      skipped: number
      latencies: number[]
      documents: Set<number>
    }>()

    cells.forEach(c => {
      const model = c.model_id
      if (!model) return
      let entry = map.get(model)
      if (!entry) {
        entry = {
          model_id: model,
          total_cost_usd: 0,
          input_cost_usd: 0,
          output_cost_usd: 0,
          cache_cost_usd: 0,
          thinking_cost_usd: 0,
          total_tokens: 0,
          input_tokens: 0,
          output_tokens: 0,
          cached_tokens: 0,
          thinking_tokens: 0,
          call_count: 0,
          succeeded: 0,
          failed: 0,
          skipped: 0,
          latencies: [],
          documents: new Set<number>(),
        }
        map.set(model, entry)
      }

      const cb = c.cost_breakdown
      const u = c.usage
      const cellTotalCost = cb?.total_usd ?? c.cost_usd ?? 0

      entry.total_cost_usd += cellTotalCost
      entry.input_cost_usd += cb?.input_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.4 : 0)
      entry.output_cost_usd += cb?.output_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.6 : 0)
      entry.cache_cost_usd += cb?.cache_usd ?? 0
      entry.thinking_cost_usd += cb?.thinking_usd ?? 0

      const inTok = u?.input_tokens ?? 0
      const outTok = u?.output_tokens ?? 0
      const cacheTok = u?.cached_tokens ?? 0
      const thinkTok = u?.thinking_tokens ?? 0
      const totTok = u?.total_tokens ?? (inTok + outTok + thinkTok)

      entry.input_tokens += inTok
      entry.output_tokens += outTok
      entry.cached_tokens += cacheTok
      entry.thinking_tokens += thinkTok
      entry.total_tokens += totTok

      entry.call_count++
      if (c.status === 'succeeded') {
        entry.succeeded++
        if (typeof c.latency_ms === 'number' && c.latency_ms > 0) {
          entry.latencies.push(c.latency_ms)
        }
      } else if (c.status === 'failed') {
        entry.failed++
      } else if (c.status === 'skipped') {
        entry.skipped++
      }

      if (c.document_id) entry.documents.add(c.document_id)
    })

    return Array.from(map.values()).map(entry => {
      const docCount = entry.documents.size || 1
      const sortedLat = [...entry.latencies].sort((a, b) => a - b)
      const medianLat = sortedLat.length ? sortedLat[Math.floor(sortedLat.length / 2)] : 0
      return {
        ...entry,
        doc_count: entry.documents.size,
        cost_per_doc: entry.total_cost_usd / docCount,
        cost_per_call: entry.call_count ? entry.total_cost_usd / entry.call_count : 0,
        median_latency_ms: medianLat,
      }
    }).sort((a, b) => b.total_cost_usd - a.total_cost_usd)
  }, [cells])

  // Agent (Task) Segregation
  const agentStats = useMemo(() => {
    const map = new Map<string, {
      task: string
      total_cost_usd: number
      input_cost_usd: number
      output_cost_usd: number
      cache_cost_usd: number
      thinking_cost_usd: number
      total_tokens: number
      input_tokens: number
      output_tokens: number
      cached_tokens: number
      thinking_tokens: number
      call_count: number
      succeeded: number
      failed: number
      skipped: number
      latencies: number[]
      documents: Set<number>
    }>()

    cells.forEach(c => {
      const task = c.task
      if (!task) return
      let entry = map.get(task)
      if (!entry) {
        entry = {
          task,
          total_cost_usd: 0,
          input_cost_usd: 0,
          output_cost_usd: 0,
          cache_cost_usd: 0,
          thinking_cost_usd: 0,
          total_tokens: 0,
          input_tokens: 0,
          output_tokens: 0,
          cached_tokens: 0,
          thinking_tokens: 0,
          call_count: 0,
          succeeded: 0,
          failed: 0,
          skipped: 0,
          latencies: [],
          documents: new Set<number>(),
        }
        map.set(task, entry)
      }

      const cb = c.cost_breakdown
      const u = c.usage
      const cellTotalCost = cb?.total_usd ?? c.cost_usd ?? 0

      entry.total_cost_usd += cellTotalCost
      entry.input_cost_usd += cb?.input_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.4 : 0)
      entry.output_cost_usd += cb?.output_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.6 : 0)
      entry.cache_cost_usd += cb?.cache_usd ?? 0
      entry.thinking_cost_usd += cb?.thinking_usd ?? 0

      const inTok = u?.input_tokens ?? 0
      const outTok = u?.output_tokens ?? 0
      const cacheTok = u?.cached_tokens ?? 0
      const thinkTok = u?.thinking_tokens ?? 0
      const totTok = u?.total_tokens ?? (inTok + outTok + thinkTok)

      entry.input_tokens += inTok
      entry.output_tokens += outTok
      entry.cached_tokens += cacheTok
      entry.thinking_tokens += thinkTok
      entry.total_tokens += totTok

      entry.call_count++
      if (c.status === 'succeeded') {
        entry.succeeded++
        if (typeof c.latency_ms === 'number' && c.latency_ms > 0) {
          entry.latencies.push(c.latency_ms)
        }
      } else if (c.status === 'failed') {
        entry.failed++
      } else if (c.status === 'skipped') {
        entry.skipped++
      }

      if (c.document_id) entry.documents.add(c.document_id)
    })

    return Array.from(map.values()).map(entry => {
      const docCount = entry.documents.size || 1
      const avgLat = entry.latencies.length
        ? Math.round(entry.latencies.reduce((a, b) => a + b, 0) / entry.latencies.length)
        : 0
      return {
        ...entry,
        doc_count: entry.documents.size,
        cost_per_doc: entry.total_cost_usd / docCount,
        cost_per_call: entry.call_count ? entry.total_cost_usd / entry.call_count : 0,
        avg_latency_ms: avgLat,
      }
    }).sort((a, b) => b.total_cost_usd - a.total_cost_usd)
  }, [cells])

  // Document (Claim) Segregation
  const docStats = useMemo(() => {
    const map = new Map<number, {
      document_id: number
      document_name: string
      total_cost_usd: number
      input_cost_usd: number
      output_cost_usd: number
      cache_cost_usd: number
      thinking_cost_usd: number
      total_tokens: number
      input_tokens: number
      output_tokens: number
      cached_tokens: number
      thinking_tokens: number
      call_count: number
      models: Map<string, {
        model_id: string
        total_cost_usd: number
        total_tokens: number
        input_tokens: number
        output_tokens: number
        cached_tokens: number
        thinking_tokens: number
        call_count: number
      }>
    }>()

    cells.forEach(c => {
      const docId = c.document_id ?? 0
      if (!docId) return
      let entry = map.get(docId)
      if (!entry) {
        entry = {
          document_id: docId,
          document_name: c.document_name ?? c.document ?? `Claim #${docId}`,
          total_cost_usd: 0,
          input_cost_usd: 0,
          output_cost_usd: 0,
          cache_cost_usd: 0,
          thinking_cost_usd: 0,
          total_tokens: 0,
          input_tokens: 0,
          output_tokens: 0,
          cached_tokens: 0,
          thinking_tokens: 0,
          call_count: 0,
          models: new Map(),
        }
        map.set(docId, entry)
      }

      const cb = c.cost_breakdown
      const u = c.usage
      const cellTotalCost = cb?.total_usd ?? c.cost_usd ?? 0

      entry.total_cost_usd += cellTotalCost
      entry.input_cost_usd += cb?.input_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.4 : 0)
      entry.output_cost_usd += cb?.output_usd ?? (c.cost_usd && !cb ? cellTotalCost * 0.6 : 0)
      entry.cache_cost_usd += cb?.cache_usd ?? 0
      entry.thinking_cost_usd += cb?.thinking_usd ?? 0

      const inTok = u?.input_tokens ?? 0
      const outTok = u?.output_tokens ?? 0
      const cacheTok = u?.cached_tokens ?? 0
      const thinkTok = u?.thinking_tokens ?? 0
      const totTok = u?.total_tokens ?? (inTok + outTok + thinkTok)

      entry.input_tokens += inTok
      entry.output_tokens += outTok
      entry.cached_tokens += cacheTok
      entry.thinking_tokens += thinkTok
      entry.total_tokens += totTok
      entry.call_count++

      // Model breakdown inside document
      if (c.model_id) {
        let mEntry = entry.models.get(c.model_id)
        if (!mEntry) {
          mEntry = {
            model_id: c.model_id,
            total_cost_usd: 0,
            total_tokens: 0,
            input_tokens: 0,
            output_tokens: 0,
            cached_tokens: 0,
            thinking_tokens: 0,
            call_count: 0,
          }
          entry.models.set(c.model_id, mEntry)
        }
        mEntry.total_cost_usd += cellTotalCost
        mEntry.total_tokens += totTok
        mEntry.input_tokens += inTok
        mEntry.output_tokens += outTok
        mEntry.cached_tokens += cacheTok
        mEntry.thinking_tokens += thinkTok
        mEntry.call_count++
      }
    })

    return Array.from(map.values()).map(entry => {
      const modelList = Array.from(entry.models.values()).sort((a, b) => b.total_cost_usd - a.total_cost_usd)
      const avgCostPerModel = modelList.length ? entry.total_cost_usd / modelList.length : 0
      return {
        ...entry,
        models_list: modelList,
        avg_cost_per_model: avgCostPerModel,
      }
    }).sort((a, b) => b.total_cost_usd - a.total_cost_usd)
  }, [cells])

  // Filtered & Sorted Calls
  const filteredCalls = useMemo(() => {
    return cells.filter(c => {
      if (filterModel !== 'all' && c.model_id !== filterModel) return false
      if (filterAgent !== 'all' && c.task !== filterAgent) return false
      if (filterDoc !== 'all' && String(c.document_id) !== filterDoc) return false
      if (filterStatus !== 'all' && c.status !== filterStatus) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchName = (c.document_name ?? c.document ?? '').toLowerCase().includes(q)
        const matchModel = (c.model_id ?? '').toLowerCase().includes(q)
        const matchTask = (c.task ?? '').toLowerCase().includes(q)
        if (!matchName && !matchModel && !matchTask) return false
      }
      return true
    }).sort((a, b) => {
      const costA = a.cost_breakdown?.total_usd ?? a.cost_usd ?? 0
      const costB = b.cost_breakdown?.total_usd ?? b.cost_usd ?? 0
      const tokA = a.usage?.total_tokens ?? ((a.usage?.input_tokens ?? 0) + (a.usage?.output_tokens ?? 0) + (a.usage?.thinking_tokens ?? 0))
      const tokB = b.usage?.total_tokens ?? ((b.usage?.input_tokens ?? 0) + (b.usage?.output_tokens ?? 0) + (b.usage?.thinking_tokens ?? 0))
      const latA = a.latency_ms ?? 0
      const latB = b.latency_ms ?? 0

      let diff = 0
      if (sortField === 'cost') diff = costA - costB
      else if (sortField === 'tokens') diff = tokA - tokB
      else if (sortField === 'latency') diff = latA - latB
      else if (sortField === 'doc') diff = (a.document_name ?? '').localeCompare(b.document_name ?? '')
      else if (sortField === 'agent') diff = (a.task ?? '').localeCompare(b.task ?? '')

      return sortAsc ? diff : -diff
    })
  }, [cells, filterModel, filterAgent, filterDoc, filterStatus, searchQuery, sortField, sortAsc])

  const toggleDocExpand = (id: number) => {
    setExpandedDocs(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const handleSaveRate = () => {
    const parsed = parseFloat(tempRate)
    if (!isNaN(parsed) && parsed > 0) {
      setExchangeRate(parsed)
    }
    setIsEditingRate(false)
  }

  // Export full CSV
  const handleExportCostReport = () => {
    const header = [
      'Document ID',
      'Document Name',
      'Agent (Task)',
      'Model',
      'Status',
      'Input Tokens',
      'Output Tokens',
      'Cached Tokens',
      'Thinking Tokens',
      'Total Tokens',
      'Input Cost (USD)',
      'Output Cost (USD)',
      'Cache Cost (USD)',
      'Thinking Cost (USD)',
      'Total Cost (USD)',
      `Total Cost (INR @ ₹${exchangeRate})`,
      'Latency (ms)',
      'Retries',
      'Error',
    ]

    const rows = cells.map(c => {
      const cb = c.cost_breakdown
      const u = c.usage
      const totalUsd = cb?.total_usd ?? c.cost_usd ?? 0
      const totalInr = totalUsd * exchangeRate
      return [
        c.document_id ?? '',
        `"${(c.document_name ?? c.document ?? '').replaceAll('"', '""')}"`,
        `"${c.task}"`,
        `"${c.model_id}"`,
        c.status,
        u?.input_tokens ?? 0,
        u?.output_tokens ?? 0,
        u?.cached_tokens ?? 0,
        u?.thinking_tokens ?? 0,
        u?.total_tokens ?? ((u?.input_tokens ?? 0) + (u?.output_tokens ?? 0) + (u?.thinking_tokens ?? 0)),
        cb?.input_usd ?? (c.cost_usd && !cb ? totalUsd * 0.4 : 0),
        cb?.output_usd ?? (c.cost_usd && !cb ? totalUsd * 0.6 : 0),
        cb?.cache_usd ?? 0,
        cb?.thinking_usd ?? 0,
        totalUsd,
        totalInr.toFixed(4),
        c.latency_ms ?? '',
        c.retries ?? 0,
        `"${(c.error ?? '').replaceAll('"', '""')}"`,
      ].join(',')
    })

    const csvContent = [header.join(','), ...rows].join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', `colosseum-cost-tokens-report.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Token percentage calculations for whole run
  const tokenPercentages = useMemo(() => {
    const total = totals.tokensTotal || 1
    return {
      input: ((totals.tokensInput / total) * 100).toFixed(1),
      output: ((totals.tokensOutput / total) * 100).toFixed(1),
      cache: ((totals.tokensCache / total) * 100).toFixed(1),
      thinking: ((totals.tokensThinking / total) * 100).toFixed(1),
    }
  }, [totals])

  // Cost percentage calculations for whole run
  const costPercentages = useMemo(() => {
    const total = totals.costTotal || 1
    return {
      input: ((totals.costInput / total) * 100).toFixed(1),
      output: ((totals.costOutput / total) * 100).toFixed(1),
      cache: ((totals.costCache / total) * 100).toFixed(1),
      thinking: ((totals.costThinking / total) * 100).toFixed(1),
    }
  }, [totals])

  return (
    <div className="cost-breakdown-dashboard">
      {/* Header bar with Currency Controls and Export */}
      <div className="cost-header-bar row between" style={{ marginBottom: '1.25rem', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div className="row gap-md" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Currency Toggle */}
          <div className="segmented currency-toggle">
            <button
              type="button"
              className={currency === 'USD' ? 'active' : ''}
              onClick={() => setCurrency('USD')}
            >
              🇺🇸 USD ($)
            </button>
            <button
              type="button"
              className={currency === 'INR' ? 'active' : ''}
              onClick={() => setCurrency('INR')}
            >
              🇮🇳 INR (₹)
            </button>
          </div>

          {/* Exchange rate indicator & inline editor */}
          <div className="exchange-rate-pill row gap-xs" style={{ alignItems: 'center' }}>
            <span className="muted" style={{ fontSize: '0.8rem' }}>1 USD =</span>
            {isEditingRate ? (
              <div className="row gap-xs" style={{ alignItems: 'center' }}>
                <input
                  type="number"
                  step="0.1"
                  value={tempRate}
                  onChange={e => setTempRate(e.target.value)}
                  style={{ width: '80px', padding: '0.2rem 0.4rem', fontSize: '0.82rem', height: '26px' }}
                  autoFocus
                  onKeyDown={e => e.key === 'Enter' && handleSaveRate()}
                />
                <button type="button" className="sm primary" onClick={handleSaveRate} style={{ padding: '0.2rem 0.5rem', height: '26px' }}>
                  ✓
                </button>
                <button type="button" className="sm ghost" onClick={() => setIsEditingRate(false)} style={{ padding: '0.2rem 0.5rem', height: '26px' }}>
                  ✕
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="ghost sm"
                onClick={() => { setTempRate(String(exchangeRate)); setIsEditingRate(true) }}
                title="Click to customize conversion rate"
                style={{ padding: '0.15rem 0.4rem', fontWeight: 600, color: 'var(--accent)' }}
              >
                ₹{exchangeRate.toFixed(2)} ✎
              </button>
            )}
          </div>
        </div>

        <div className="row gap-sm">
          <button type="button" className="secondary sm" onClick={handleExportCostReport}>
            📥 Export Cost CSV
          </button>
        </div>
      </div>

      {/* KPI Cards: Whole Cost & Tokens Overview */}
      <div className="cost-kpi-grid">
        {/* Total Cost Card */}
        <Card className="cost-kpi-card">
          <div className="kpi-header">
            <span className="kpi-title">Total Run Cost</span>
            <Badge tone="good">
              {totals.totalCalls} calls
            </Badge>
          </div>
          <div className="kpi-primary-val">
            {formatCost(totals.costTotal, currency, exchangeRate)}
          </div>
          <div className="kpi-sub-val muted">
            {currency === 'USD' ? (
              <span>≈ {formatCost(totals.costTotal, 'INR', exchangeRate)} INR</span>
            ) : (
              <span>≈ {formatCost(totals.costTotal, 'USD', exchangeRate)} USD</span>
            )}
          </div>
          <div className="kpi-footer row between" style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid var(--line)' }}>
            <span><strong>{formatCost(totals.costPerDoc, currency, exchangeRate)}</strong> / doc</span>
            <span><strong>{formatCost(totals.costPerCall, currency, exchangeRate, 5)}</strong> / call</span>
          </div>
        </Card>

        {/* Total Tokens Card */}
        <Card className="cost-kpi-card">
          <div className="kpi-header">
            <span className="kpi-title">Total Tokens</span>
            <Badge tone="info">
              {totals.docCount} claims
            </Badge>
          </div>
          <div className="kpi-primary-val">
            {formatTokens(totals.tokensTotal)}
          </div>
          <div className="kpi-sub-val muted">
            <span>In: {formatTokens(totals.tokensInput)} · Out: {formatTokens(totals.tokensOutput)}</span>
          </div>
          <div className="kpi-footer row between" style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid var(--line)' }}>
            <span>Cache: <strong>{formatTokens(totals.tokensCache)}</strong></span>
            <span>Thinking: <strong>{formatTokens(totals.tokensThinking)}</strong></span>
          </div>
        </Card>

        {/* Token Composition Breakdown */}
        <Card className="cost-kpi-card token-dist-card">
          <div className="kpi-header">
            <span className="kpi-title">Token Distribution</span>
            <span className="muted" style={{ fontSize: '0.75rem' }}>{formatTokens(totals.tokensTotal)} total</span>
          </div>
          {/* Stacked visual progress bar */}
          <div className="stacked-composition-bar" style={{ margin: '0.6rem 0' }}>
            <div className="segment input-seg" style={{ width: `${tokenPercentages.input}%` }} title={`Input: ${formatTokens(totals.tokensInput)} (${tokenPercentages.input}%)`} />
            <div className="segment output-seg" style={{ width: `${tokenPercentages.output}%` }} title={`Output: ${formatTokens(totals.tokensOutput)} (${tokenPercentages.output}%)`} />
            <div className="segment cache-seg" style={{ width: `${tokenPercentages.cache}%` }} title={`Cache: ${formatTokens(totals.tokensCache)} (${tokenPercentages.cache}%)`} />
            <div className="segment thinking-seg" style={{ width: `${tokenPercentages.thinking}%` }} title={`Thinking: ${formatTokens(totals.tokensThinking)} (${tokenPercentages.thinking}%)`} />
          </div>
          <div className="composition-legend">
            <div className="legend-item"><span className="dot input-dot" /> Input: <strong>{tokenPercentages.input}%</strong> ({formatTokens(totals.tokensInput)})</div>
            <div className="legend-item"><span className="dot output-dot" /> Output: <strong>{tokenPercentages.output}%</strong> ({formatTokens(totals.tokensOutput)})</div>
            {totals.tokensCache > 0 && <div className="legend-item"><span className="dot cache-dot" /> Cache: <strong>{tokenPercentages.cache}%</strong> ({formatTokens(totals.tokensCache)})</div>}
            {totals.tokensThinking > 0 && <div className="legend-item"><span className="dot thinking-dot" /> Thinking: <strong>{tokenPercentages.thinking}%</strong> ({formatTokens(totals.tokensThinking)})</div>}
          </div>
        </Card>

        {/* Cost Composition Breakdown */}
        <Card className="cost-kpi-card cost-dist-card">
          <div className="kpi-header">
            <span className="kpi-title">Cost Composition</span>
            <span className="muted" style={{ fontSize: '0.75rem' }}>{formatCost(totals.costTotal, currency, exchangeRate)} total</span>
          </div>
          {/* Stacked visual progress bar */}
          <div className="stacked-composition-bar" style={{ margin: '0.6rem 0' }}>
            <div className="segment input-seg" style={{ width: `${costPercentages.input}%` }} title={`Input Cost: ${formatCost(totals.costInput, currency, exchangeRate)} (${costPercentages.input}%)`} />
            <div className="segment output-seg" style={{ width: `${costPercentages.output}%` }} title={`Output Cost: ${formatCost(totals.costOutput, currency, exchangeRate)} (${costPercentages.output}%)`} />
            <div className="segment cache-seg" style={{ width: `${costPercentages.cache}%` }} title={`Cache Cost: ${formatCost(totals.costCache, currency, exchangeRate)} (${costPercentages.cache}%)`} />
            <div className="segment thinking-seg" style={{ width: `${costPercentages.thinking}%` }} title={`Thinking Cost: ${formatCost(totals.costThinking, currency, exchangeRate)} (${costPercentages.thinking}%)`} />
          </div>
          <div className="composition-legend">
            <div className="legend-item"><span className="dot input-dot" /> Input: <strong>{formatCost(totals.costInput, currency, exchangeRate)}</strong> ({costPercentages.input}%)</div>
            <div className="legend-item"><span className="dot output-dot" /> Output: <strong>{formatCost(totals.costOutput, currency, exchangeRate)}</strong> ({costPercentages.output}%)</div>
            {totals.costCache > 0 && <div className="legend-item"><span className="dot cache-dot" /> Cache: <strong>{formatCost(totals.costCache, currency, exchangeRate)}</strong> ({costPercentages.cache}%)</div>}
            {totals.costThinking > 0 && <div className="legend-item"><span className="dot thinking-dot" /> Thinking: <strong>{formatCost(totals.costThinking, currency, exchangeRate)}</strong> ({costPercentages.thinking}%)</div>}
          </div>
        </Card>
      </div>

      {/* Segregation Navigation Sub-tabs */}
      <div className="cost-segregation-nav" style={{ margin: '1.75rem 0 1rem' }}>
        <div className="segmented">
          <button
            type="button"
            className={view === 'model' ? 'active' : ''}
            onClick={() => setView('model')}
          >
            🤖 By Model ({modelStats.length})
          </button>
          <button
            type="button"
            className={view === 'agent' ? 'active' : ''}
            onClick={() => setView('agent')}
          >
            ⚡ By Agent ({agentStats.length})
          </button>
          <button
            type="button"
            className={view === 'doc' ? 'active' : ''}
            onClick={() => setView('doc')}
          >
            📄 By Document ({docStats.length})
          </button>
          <button
            type="button"
            className={view === 'calls' ? 'active' : ''}
            onClick={() => setView('calls')}
          >
            🔍 By Individual Call ({cells.length})
          </button>
        </div>
      </div>

      {/* VIEW 1: BY MODEL */}
      {view === 'model' && (
        <Card className="cost-table-card">
          <div className="row between" style={{ marginBottom: '1rem', alignItems: 'center' }}>
            <div>
              <h2>Model Cost Segregation</h2>
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                Itemized token usage and cost per model across all processed documents and agents.
              </p>
            </div>
          </div>

          <div className="table-scroll">
            <table className="cost-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Total Cost ({currency})</th>
                  <th>Cost / Doc</th>
                  <th>Input Tokens</th>
                  <th>Output Tokens</th>
                  <th>Cache Read</th>
                  <th>Thinking</th>
                  <th>Total Tokens</th>
                  <th>Calls (OK/Fail)</th>
                  <th>Median Latency</th>
                </tr>
              </thead>
              <tbody>
                {modelStats.map(m => (
                  <tr key={m.model_id}>
                    <th>
                      <div className="row gap-xs" style={{ alignItems: 'center' }}>
                        <span className={`badge ${badgeHue(m.model_id, 'model')}`}>
                          {m.model_id.split('/').pop()}
                        </span>
                        <span className="muted" style={{ fontSize: '0.72rem' }}>{m.model_id}</span>
                      </div>
                    </th>
                    <td>
                      <strong>{formatCost(m.total_cost_usd, currency, exchangeRate)}</strong>
                      <div className="muted" style={{ fontSize: '0.72rem' }}>
                        {currency === 'USD' ? formatCost(m.total_cost_usd, 'INR', exchangeRate) : formatCost(m.total_cost_usd, 'USD', exchangeRate)}
                      </div>
                    </td>
                    <td>{formatCost(m.cost_per_doc, currency, exchangeRate)}</td>
                    <td>
                      <div>{formatTokens(m.input_tokens)}</div>
                      <small className="muted">{formatCost(m.input_cost_usd, currency, exchangeRate)}</small>
                    </td>
                    <td>
                      <div>{formatTokens(m.output_tokens)}</div>
                      <small className="muted">{formatCost(m.output_cost_usd, currency, exchangeRate)}</small>
                    </td>
                    <td>
                      {m.cached_tokens > 0 ? (
                        <>
                          <div style={{ color: 'var(--success, #4fd766)' }}>{formatTokens(m.cached_tokens)}</div>
                          <small className="muted">{formatCost(m.cache_cost_usd, currency, exchangeRate)}</small>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {m.thinking_tokens > 0 ? (
                        <>
                          <div style={{ color: 'var(--warn, #f0b350)' }}>{formatTokens(m.thinking_tokens)}</div>
                          <small className="muted">{formatCost(m.thinking_cost_usd, currency, exchangeRate)}</small>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td><strong>{formatTokens(m.total_tokens)}</strong></td>
                    <td>
                      <span className="badge good">{m.succeeded}</span>
                      {m.failed > 0 && <span className="badge bad" style={{ marginLeft: '4px' }}>{m.failed}</span>}
                    </td>
                    <td>{formatDuration(m.median_latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Total ({modelStats.length} models)</th>
                  <td><strong>{formatCost(totals.costTotal, currency, exchangeRate)}</strong></td>
                  <td><strong>{formatCost(totals.costPerDoc, currency, exchangeRate)}</strong></td>
                  <td>{formatTokens(totals.tokensInput)}</td>
                  <td>{formatTokens(totals.tokensOutput)}</td>
                  <td>{formatTokens(totals.tokensCache)}</td>
                  <td>{formatTokens(totals.tokensThinking)}</td>
                  <td><strong>{formatTokens(totals.tokensTotal)}</strong></td>
                  <td><strong>{totals.totalCalls}</strong></td>
                  <td>—</td>
                </tr>
              </tfoot>
            </table>
          </div>

          {/* Model Relative Cost Comparison Chart */}
          <div className="model-chart-section" style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--line)' }}>
            <h3>Model Cost Share</h3>
            <div className="chart-bar-list" style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              {modelStats.map(m => {
                const pct = totals.costTotal > 0 ? (m.total_cost_usd / totals.costTotal) * 100 : 0
                return (
                  <div key={m.model_id} className="chart-bar-row">
                    <div className="row between" style={{ fontSize: '0.82rem', marginBottom: '0.2rem' }}>
                      <span className="chart-model-label"><strong>{m.model_id}</strong></span>
                      <span>{formatCost(m.total_cost_usd, currency, exchangeRate)} ({pct.toFixed(1)}%)</span>
                    </div>
                    <div className="chart-bar-track" style={{ height: '8px', background: 'var(--surface-3)', borderRadius: '4px', overflow: 'hidden' }}>
                      <div className="chart-bar-fill" style={{ width: `${Math.max(pct, 1)}%`, height: '100%', background: 'var(--accent)', borderRadius: '4px' }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </Card>
      )}

      {/* VIEW 2: BY AGENT (TASK) */}
      {view === 'agent' && (
        <Card className="cost-table-card">
          <div className="row between" style={{ marginBottom: '1rem', alignItems: 'center' }}>
            <div>
              <h2>Agent Cost Segregation</h2>
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                Cost and token consumption across each agent/task in the claim processing pipeline.
              </p>
            </div>
          </div>

          <div className="table-scroll">
            <table className="cost-table">
              <thead>
                <tr>
                  <th>Agent (Task)</th>
                  <th>Total Cost ({currency})</th>
                  <th>Cost / Doc</th>
                  <th>Input Tokens</th>
                  <th>Output Tokens</th>
                  <th>Cache Read</th>
                  <th>Thinking</th>
                  <th>Total Tokens</th>
                  <th>Calls</th>
                  <th>Avg Latency</th>
                </tr>
              </thead>
              <tbody>
                {agentStats.map(a => (
                  <tr key={a.task}>
                    <th>
                      <div className="row gap-xs" style={{ alignItems: 'center' }}>
                        <span className={`badge ${badgeHue(a.task, 'agent')}`}>
                          {a.task.replaceAll('_', ' ')}
                        </span>
                      </div>
                    </th>
                    <td>
                      <strong>{formatCost(a.total_cost_usd, currency, exchangeRate)}</strong>
                      <div className="muted" style={{ fontSize: '0.72rem' }}>
                        {currency === 'USD' ? formatCost(a.total_cost_usd, 'INR', exchangeRate) : formatCost(a.total_cost_usd, 'USD', exchangeRate)}
                      </div>
                    </td>
                    <td>{formatCost(a.cost_per_doc, currency, exchangeRate)}</td>
                    <td>
                      <div>{formatTokens(a.input_tokens)}</div>
                      <small className="muted">{formatCost(a.input_cost_usd, currency, exchangeRate)}</small>
                    </td>
                    <td>
                      <div>{formatTokens(a.output_tokens)}</div>
                      <small className="muted">{formatCost(a.output_cost_usd, currency, exchangeRate)}</small>
                    </td>
                    <td>
                      {a.cached_tokens > 0 ? (
                        <>
                          <div style={{ color: 'var(--success, #4fd766)' }}>{formatTokens(a.cached_tokens)}</div>
                          <small className="muted">{formatCost(a.cache_cost_usd, currency, exchangeRate)}</small>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {a.thinking_tokens > 0 ? (
                        <>
                          <div style={{ color: 'var(--warn, #f0b350)' }}>{formatTokens(a.thinking_tokens)}</div>
                          <small className="muted">{formatCost(a.thinking_cost_usd, currency, exchangeRate)}</small>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td><strong>{formatTokens(a.total_tokens)}</strong></td>
                    <td>{a.call_count}</td>
                    <td>{formatDuration(a.avg_latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Total ({agentStats.length} agents)</th>
                  <td><strong>{formatCost(totals.costTotal, currency, exchangeRate)}</strong></td>
                  <td><strong>{formatCost(totals.costPerDoc, currency, exchangeRate)}</strong></td>
                  <td>{formatTokens(totals.tokensInput)}</td>
                  <td>{formatTokens(totals.tokensOutput)}</td>
                  <td>{formatTokens(totals.tokensCache)}</td>
                  <td>{formatTokens(totals.tokensThinking)}</td>
                  <td><strong>{formatTokens(totals.tokensTotal)}</strong></td>
                  <td><strong>{totals.totalCalls}</strong></td>
                  <td>—</td>
                </tr>
              </tfoot>
            </table>
          </div>

          {/* Agent Cost Share Chart */}
          <div className="agent-chart-section" style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--line)' }}>
            <h3>Agent Pipeline Cost Share</h3>
            <div className="chart-bar-list" style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              {agentStats.map(a => {
                const pct = totals.costTotal > 0 ? (a.total_cost_usd / totals.costTotal) * 100 : 0
                return (
                  <div key={a.task} className="chart-bar-row">
                    <div className="row between" style={{ fontSize: '0.82rem', marginBottom: '0.2rem' }}>
                      <span className="chart-agent-label"><strong>{a.task.replaceAll('_', ' ')}</strong></span>
                      <span>{formatCost(a.total_cost_usd, currency, exchangeRate)} ({pct.toFixed(1)}%)</span>
                    </div>
                    <div className="chart-bar-track" style={{ height: '8px', background: 'var(--surface-3)', borderRadius: '4px', overflow: 'hidden' }}>
                      <div className="chart-bar-fill" style={{ width: `${Math.max(pct, 1)}%`, height: '100%', background: 'var(--brand, #4fd766)', borderRadius: '4px' }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </Card>
      )}

      {/* VIEW 3: BY DOCUMENT (CLAIM) */}
      {view === 'doc' && (
        <Card className="cost-table-card">
          <div className="row between" style={{ marginBottom: '1rem', alignItems: 'center' }}>
            <div>
              <h2>Document Cost Segregation</h2>
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                Cost and token consumption for each benchmarked document/claim. Click any row to expand model breakdown.
              </p>
            </div>
          </div>

          <div className="table-scroll">
            <table className="cost-table">
              <thead>
                <tr>
                  <th style={{ width: '32px' }} />
                  <th>Document / Claim</th>
                  <th>Total Cost ({currency})</th>
                  <th>Avg Cost / Model</th>
                  <th>Input Tokens</th>
                  <th>Output Tokens</th>
                  <th>Cache Read</th>
                  <th>Thinking</th>
                  <th>Total Tokens</th>
                  <th>Calls</th>
                </tr>
              </thead>
              <tbody>
                {docStats.map(doc => {
                  const isExpanded = expandedDocs[doc.document_id]
                  return (
                    <DocumentRow
                      key={doc.document_id}
                      doc={doc}
                      isExpanded={isExpanded}
                      onToggle={() => toggleDocExpand(doc.document_id)}
                      currency={currency}
                      exchangeRate={exchangeRate}
                    />
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th />
                  <th>Total ({docStats.length} documents)</th>
                  <td><strong>{formatCost(totals.costTotal, currency, exchangeRate)}</strong></td>
                  <td><strong>{formatCost(totals.costPerDoc, currency, exchangeRate)}</strong></td>
                  <td>{formatTokens(totals.tokensInput)}</td>
                  <td>{formatTokens(totals.tokensOutput)}</td>
                  <td>{formatTokens(totals.tokensCache)}</td>
                  <td>{formatTokens(totals.tokensThinking)}</td>
                  <td><strong>{formatTokens(totals.tokensTotal)}</strong></td>
                  <td><strong>{totals.totalCalls}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </Card>
      )}

      {/* VIEW 4: BY INDIVIDUAL CALL (MATRIX) */}
      {view === 'calls' && (
        <Card className="cost-table-card">
          <div className="calls-filter-bar row between" style={{ marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'flex-end' }}>
            {/* Search input */}
            <div className="search-box">
              <label style={{ fontSize: '0.78rem', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                Search Calls
                <input
                  type="text"
                  placeholder="Filter by doc, model, agent..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  style={{ width: '220px', padding: '0.35rem 0.6rem', fontSize: '0.85rem' }}
                />
              </label>
            </div>

            {/* Dropdown Filters */}
            <div className="row gap-xs" style={{ flexWrap: 'wrap' }}>
              <label style={{ fontSize: '0.78rem' }}>
                Model
                <select value={filterModel} onChange={e => setFilterModel(e.target.value)}>
                  <option value="all">All Models ({models.length})</option>
                  {models.map(m => <option key={m} value={m}>{m.split('/').pop()}</option>)}
                </select>
              </label>

              <label style={{ fontSize: '0.78rem' }}>
                Agent
                <select value={filterAgent} onChange={e => setFilterAgent(e.target.value)}>
                  <option value="all">All Agents ({agents.length})</option>
                  {agents.map(a => <option key={a} value={a}>{a.replaceAll('_', ' ')}</option>)}
                </select>
              </label>

              <label style={{ fontSize: '0.78rem' }}>
                Document
                <select value={filterDoc} onChange={e => setFilterDoc(e.target.value)}>
                  <option value="all">All Documents ({documents.length})</option>
                  {documents.map(d => <option key={d.id} value={String(d.id)}>{d.name}</option>)}
                </select>
              </label>

              <label style={{ fontSize: '0.78rem' }}>
                Status
                <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                  <option value="all">All Statuses</option>
                  <option value="succeeded">Succeeded</option>
                  <option value="failed">Failed</option>
                  <option value="skipped">Skipped</option>
                </select>
              </label>
            </div>

            {/* Sort Dropdown */}
            <div className="row gap-xs" style={{ alignItems: 'center' }}>
              <label style={{ fontSize: '0.78rem' }}>
                Sort By
                <select value={sortField} onChange={e => setSortField(e.target.value as any)}>
                  <option value="cost">Cost (Highest)</option>
                  <option value="tokens">Tokens (Highest)</option>
                  <option value="latency">Latency</option>
                  <option value="doc">Document Name</option>
                  <option value="agent">Agent Name</option>
                </select>
              </label>
              <button
                type="button"
                className="ghost sm"
                onClick={() => setSortAsc(!sortAsc)}
                title={sortAsc ? 'Ascending' : 'Descending'}
                style={{ marginTop: '1.2rem', padding: '0.35rem 0.5rem' }}
              >
                {sortAsc ? '↑' : '↓'}
              </button>
            </div>
          </div>

          <div className="row between" style={{ marginBottom: '0.5rem', fontSize: '0.8rem', color: 'var(--muted)' }}>
            <span>Showing {filteredCalls.length} of {cells.length} calls</span>
            {(filterModel !== 'all' || filterAgent !== 'all' || filterDoc !== 'all' || filterStatus !== 'all' || searchQuery) && (
              <button
                type="button"
                className="ghost sm"
                onClick={() => {
                  setFilterModel('all')
                  setFilterAgent('all')
                  setFilterDoc('all')
                  setFilterStatus('all')
                  setSearchQuery('')
                }}
                style={{ color: 'var(--accent)' }}
              >
                Reset Filters
              </button>
            )}
          </div>

          <div className="table-scroll" style={{ maxHeight: '600px', overflowY: 'auto' }}>
            <table className="cost-table call-matrix-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Agent (Task)</th>
                  <th>Model</th>
                  <th>Status</th>
                  <th>Input</th>
                  <th>Output</th>
                  <th>Cache</th>
                  <th>Thinking</th>
                  <th>Total Tokens</th>
                  <th>Total Cost ({currency})</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {filteredCalls.map((c, idx) => {
                  const cb = c.cost_breakdown
                  const u = c.usage
                  const cellCost = cb?.total_usd ?? c.cost_usd ?? 0
                  const inTok = u?.input_tokens ?? 0
                  const outTok = u?.output_tokens ?? 0
                  const cacheTok = u?.cached_tokens ?? 0
                  const thinkTok = u?.thinking_tokens ?? 0
                  const totTok = u?.total_tokens ?? (inTok + outTok + thinkTok)

                  return (
                    <tr key={`${c.document_id}-${c.task}-${c.model_id}-${idx}`}>
                      <td>
                        <strong>{c.document_name ?? c.document ?? `Doc ${c.document_id}`}</strong>
                        <div className="muted" style={{ fontSize: '0.7rem' }}>#{c.document_id}</div>
                      </td>
                      <td>
                        <span className={`badge ${badgeHue(c.task, 'agent')}`}>
                          {c.task.replaceAll('_', ' ')}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${badgeHue(c.model_id, 'model')}`}>
                          {c.model_id.split('/').pop()}
                        </span>
                      </td>
                      <td>
                        <Badge tone={c.status === 'succeeded' ? 'good' : c.status === 'failed' ? 'bad' : 'warn'}>
                          {c.status}
                        </Badge>
                      </td>
                      <td>
                        <div>{formatTokens(inTok)}</div>
                        <small className="muted">{formatCost(cb?.input_usd ?? (c.cost_usd && !cb ? cellCost * 0.4 : 0), currency, exchangeRate, 5)}</small>
                      </td>
                      <td>
                        <div>{formatTokens(outTok)}</div>
                        <small className="muted">{formatCost(cb?.output_usd ?? (c.cost_usd && !cb ? cellCost * 0.6 : 0), currency, exchangeRate, 5)}</small>
                      </td>
                      <td>
                        {cacheTok > 0 ? (
                          <>
                            <div style={{ color: 'var(--success, #4fd766)' }}>{formatTokens(cacheTok)}</div>
                            <small className="muted">{formatCost(cb?.cache_usd, currency, exchangeRate, 5)}</small>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        {thinkTok > 0 ? (
                          <>
                            <div style={{ color: 'var(--warn, #f0b350)' }}>{formatTokens(thinkTok)}</div>
                            <small className="muted">{formatCost(cb?.thinking_usd, currency, exchangeRate, 5)}</small>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td><strong>{formatTokens(totTok)}</strong></td>
                      <td>
                        <strong>{formatCost(cellCost, currency, exchangeRate, 5)}</strong>
                        <div className="muted" style={{ fontSize: '0.7rem' }}>
                          {currency === 'USD' ? formatCost(cellCost, 'INR', exchangeRate, 4) : formatCost(cellCost, 'USD', exchangeRate, 5)}
                        </div>
                      </td>
                      <td>{formatDuration(c.latency_ms)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

function DocumentRow({
  doc,
  isExpanded,
  onToggle,
  currency,
  exchangeRate,
}: {
  doc: {
    document_id: number
    document_name: string
    total_cost_usd: number
    avg_cost_per_model: number
    input_cost_usd: number
    output_cost_usd: number
    cache_cost_usd: number
    thinking_cost_usd: number
    total_tokens: number
    input_tokens: number
    output_tokens: number
    cached_tokens: number
    thinking_tokens: number
    call_count: number
    models_list: Array<{
      model_id: string
      total_cost_usd: number
      total_tokens: number
      input_tokens: number
      output_tokens: number
      cached_tokens: number
      thinking_tokens: number
      call_count: number
    }>
  }
  isExpanded?: boolean
  onToggle: () => void
  currency: 'USD' | 'INR'
  exchangeRate: number
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={isExpanded ? 'expanded-row-parent' : ''}
        style={{ cursor: 'pointer' }}
      >
        <td style={{ textAlign: 'center', color: 'var(--accent)' }}>
          {isExpanded ? '▼' : '▶'}
        </td>
        <th>
          <div className="row gap-xs" style={{ alignItems: 'center' }}>
            <span>{doc.document_name}</span>
            <span className="muted" style={{ fontSize: '0.72rem' }}>#{doc.document_id}</span>
          </div>
        </th>
        <td>
          <strong>{formatCost(doc.total_cost_usd, currency, exchangeRate)}</strong>
          <div className="muted" style={{ fontSize: '0.72rem' }}>
            {currency === 'USD' ? formatCost(doc.total_cost_usd, 'INR', exchangeRate) : formatCost(doc.total_cost_usd, 'USD', exchangeRate)}
          </div>
        </td>
        <td>{formatCost(doc.avg_cost_per_model, currency, exchangeRate)}</td>
        <td>
          <div>{formatTokens(doc.input_tokens)}</div>
          <small className="muted">{formatCost(doc.input_cost_usd, currency, exchangeRate)}</small>
        </td>
        <td>
          <div>{formatTokens(doc.output_tokens)}</div>
          <small className="muted">{formatCost(doc.output_cost_usd, currency, exchangeRate)}</small>
        </td>
        <td>
          {doc.cached_tokens > 0 ? (
            <>
              <div style={{ color: 'var(--success, #4fd766)' }}>{formatTokens(doc.cached_tokens)}</div>
              <small className="muted">{formatCost(doc.cache_cost_usd, currency, exchangeRate)}</small>
            </>
          ) : (
            <span className="muted">—</span>
          )}
        </td>
        <td>
          {doc.thinking_tokens > 0 ? (
            <>
              <div style={{ color: 'var(--warn, #f0b350)' }}>{formatTokens(doc.thinking_tokens)}</div>
              <small className="muted">{formatCost(doc.thinking_cost_usd, currency, exchangeRate)}</small>
            </>
          ) : (
            <span className="muted">—</span>
          )}
        </td>
        <td><strong>{formatTokens(doc.total_tokens)}</strong></td>
        <td>{doc.call_count}</td>
      </tr>

      {/* Expanded Per-Model Rows for this Document */}
      {isExpanded && (
        <tr className="expanded-row-details">
          <td colSpan={10} style={{ padding: '0.5rem 1.5rem 1rem', background: 'var(--surface-2)' }}>
            <div style={{ padding: '0.5rem', background: 'var(--surface)', borderRadius: '6px', border: '1px solid var(--line)' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                Model breakdown for {doc.document_name}:
              </div>
              <table style={{ width: '100%', fontSize: '0.8rem' }}>
                <thead>
                  <tr style={{ background: 'transparent', borderBottom: '1px solid var(--line)' }}>
                    <th style={{ textAlign: 'left' }}>Model</th>
                    <th style={{ textAlign: 'right' }}>Cost ({currency})</th>
                    <th style={{ textAlign: 'right' }}>Input Tokens</th>
                    <th style={{ textAlign: 'right' }}>Output Tokens</th>
                    <th style={{ textAlign: 'right' }}>Cache Tokens</th>
                    <th style={{ textAlign: 'right' }}>Thinking Tokens</th>
                    <th style={{ textAlign: 'right' }}>Total Tokens</th>
                    <th style={{ textAlign: 'right' }}>Calls</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.models_list.map(m => (
                    <tr key={m.model_id}>
                      <td style={{ textAlign: 'left' }}>
                        <span className={`badge ${badgeHue(m.model_id, 'model')}`}>
                          {m.model_id.split('/').pop()}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{formatCost(m.total_cost_usd, currency, exchangeRate)}</td>
                      <td style={{ textAlign: 'right' }}>{formatTokens(m.input_tokens)}</td>
                      <td style={{ textAlign: 'right' }}>{formatTokens(m.output_tokens)}</td>
                      <td style={{ textAlign: 'right' }}>{formatTokens(m.cached_tokens)}</td>
                      <td style={{ textAlign: 'right' }}>{formatTokens(m.thinking_tokens)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{formatTokens(m.total_tokens)}</td>
                      <td style={{ textAlign: 'right' }}>{m.call_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
