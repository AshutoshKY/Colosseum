import { useState } from 'react'
import type { LeaderboardRow } from '../types'
import { money, percent } from './common'

export function LeaderboardTable({rows}: {rows: LeaderboardRow[]}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Accuracy</th>
            <th>Valid</th>
            <th>Judge</th>
            <th>Win rate</th>
            <th>Cost/doc</th>
            <th>Median latency</th>
            <th>Composite</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.model_id ?? row.model}>
              <th>{row.model_id ?? row.model}</th>
              <td>{percent(row.accuracy)}</td>
              <td>{percent(row.valid_percent ?? row.valid_rate)}</td>
              <td>{row.judge_score?.toFixed(2) ?? '—'}</td>
              <td>{percent(row.win_rate)}</td>
              <td>{money(row.cost_per_doc ?? row.cost_usd)}</td>
              <td>{Math.round(row.median_latency_ms ?? row.latency_ms ?? 0).toLocaleString()} ms</td>
              <td><strong>{row.composite?.toFixed(2) ?? '—'}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const PALETTE = [
  '#a8f22d', // brand green
  '#4fd766', // success green
  '#64abf5', // info blue
  '#f0b350', // warning amber
  '#ec4899', // pink
  '#a855f7', // purple
  '#06b6d4', // cyan
  '#f97316', // orange
]

export function AccuracyCostChart({ rows }: { rows: LeaderboardRow[] }) {
  const [hovered, setHovered] = useState<LeaderboardRow | null>(null)

  if (!rows || rows.length === 0) {
    return <div className="scatter-empty">No data available for chart.</div>
  }

  const rawMaxCost = Math.max(...rows.map(r => r.cost_per_doc ?? r.cost_usd ?? 0), 0)
  const maxCost = rawMaxCost > 0 ? Math.max(0.005, rawMaxCost * 1.35) : 0.01

  const width = 800
  const height = 300
  const margin = { top: 35, right: 70, bottom: 50, left: 65 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom

  const yTicks = [0, 0.25, 0.50, 0.75, 1.0]
  const xTicks = [0, maxCost * 0.25, maxCost * 0.5, maxCost * 0.75, maxCost]

  return (
    <div className="scatter-container" style={{ position: 'relative', width: '100%', margin: '1rem 0 0.5rem' }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        role="img"
        aria-label="Accuracy versus cost scatter chart"
      >
        {/* Background plot area */}
        <rect
          x={margin.left}
          y={margin.top}
          width={plotWidth}
          height={plotHeight}
          fill="var(--surface-2, rgba(255, 255, 255, 0.02))"
          rx="6"
        />

        {/* Y Grid lines & Y Labels */}
        {yTicks.map(tick => {
          const y = margin.top + (1 - tick) * plotHeight
          return (
            <g key={`y-${tick}`}>
              <line
                x1={margin.left}
                y1={y}
                x2={margin.left + plotWidth}
                y2={y}
                stroke="var(--line, rgba(255, 255, 255, 0.08))"
                strokeDasharray={tick === 0 ? undefined : '3 3'}
                strokeWidth={tick === 0 ? '1.5' : '1'}
              />
              <text
                x={margin.left - 10}
                y={y + 4}
                textAnchor="end"
                fill="var(--muted, #93a198)"
                fontSize="11"
                fontFamily="inherit"
              >
                {`${Math.round(tick * 100)}%`}
              </text>
            </g>
          )
        })}

        {/* X Grid lines & X Labels */}
        {xTicks.map((tick, i) => {
          const x = margin.left + (tick / maxCost) * plotWidth
          return (
            <g key={`x-${i}`}>
              <line
                x1={x}
                y1={margin.top}
                x2={x}
                y2={margin.top + plotHeight}
                stroke="var(--line, rgba(255, 255, 255, 0.08))"
                strokeDasharray="3 3"
                strokeWidth="1"
                opacity="0.5"
              />
              <text
                x={x}
                y={margin.top + plotHeight + 22}
                textAnchor="middle"
                fill="var(--muted, #93a198)"
                fontSize="11"
                fontFamily="inherit"
              >
                {money(tick)}
              </text>
            </g>
          )
        })}

        {/* Axis Border Lines */}
        <line
          x1={margin.left}
          y1={margin.top}
          x2={margin.left}
          y2={margin.top + plotHeight}
          stroke="var(--line-strong, #364139)"
          strokeWidth="1.5"
        />
        <line
          x1={margin.left}
          y1={margin.top + plotHeight}
          x2={margin.left + plotWidth}
          y2={margin.top + plotHeight}
          stroke="var(--line-strong, #364139)"
          strokeWidth="1.5"
        />

        {/* Axis Titles */}
        <text
          x={margin.left}
          y={margin.top - 12}
          textAnchor="start"
          fill="var(--text, #e9f1ea)"
          fontSize="12"
          fontWeight="600"
          fontFamily="inherit"
        >
          Accuracy ↑
        </text>
        <text
          x={margin.left + plotWidth}
          y={margin.top + plotHeight + 42}
          textAnchor="end"
          fill="var(--muted, #93a198)"
          fontSize="11"
          fontWeight="500"
          fontFamily="inherit"
        >
          Cost / doc ($) →
        </text>

        {/* Data Points and Labels */}
        {rows.map((row, idx) => {
          const rawAcc = row.accuracy ?? 0
          const acc = rawAcc <= 1 ? rawAcc : rawAcc / 100
          const clampedAcc = Math.min(1, Math.max(0, acc))
          const cost = row.cost_per_doc ?? row.cost_usd ?? 0
          const clampedCostRatio = Math.min(1, Math.max(0, cost / maxCost))

          const cx = margin.left + clampedCostRatio * plotWidth
          const cy = margin.top + (1 - clampedAcc) * plotHeight
          const color = PALETTE[idx % PALETTE.length]
          const isHovered = hovered === row
          const modelName = row.model_id ?? row.model

          const isRightSide = clampedCostRatio > 0.6
          const textX = isRightSide ? cx - 12 : cx + 12
          const textAnchor = isRightSide ? 'end' : 'start'

          return (
            <g
              key={modelName}
              onMouseEnter={() => setHovered(row)}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: 'pointer' }}
            >
              <circle
                cx={cx}
                cy={cy}
                r={isHovered ? 14 : 8}
                fill={color}
                opacity={isHovered ? 0.35 : 0.15}
                style={{ transition: 'all 0.15s ease' }}
              />

              <circle
                cx={cx}
                cy={cy}
                r={isHovered ? 6.5 : 5}
                fill={color}
                stroke="var(--surface, #151b18)"
                strokeWidth="2"
                style={{ transition: 'all 0.15s ease' }}
              />

              <text
                x={textX}
                y={cy + 4}
                textAnchor={textAnchor}
                fill={isHovered ? 'var(--brand, #a8f22d)' : 'var(--text, #e9f1ea)'}
                fontSize="11"
                fontWeight={isHovered ? '700' : '500'}
                fontFamily="inherit"
                style={{ transition: 'fill 0.15s ease', pointerEvents: 'none' }}
              >
                {modelName}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Floating Hover Tooltip Card */}
      {hovered && (
        <div
          className="scatter-tooltip"
          style={{
            position: 'absolute',
            top: '0.75rem',
            right: '0.75rem',
            background: 'var(--surface-2, #1c2420)',
            border: '1px solid var(--line-strong, #364139)',
            borderRadius: 'var(--radius-sm, 7px)',
            padding: '0.6rem 0.85rem',
            boxShadow: 'var(--shadow, 0 6px 24px rgba(0,0,0,0.32))',
            fontSize: '0.78rem',
            pointerEvents: 'none',
            zIndex: 10,
            display: 'flex',
            flexDirection: 'column',
            gap: '0.25rem',
            minWidth: '210px',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--brand, #a8f22d)', borderBottom: '1px solid var(--line, #27312b)', paddingBottom: '0.25rem', wordBreak: 'break-all' }}>
            {hovered.model_id ?? hovered.model}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
            <span style={{ color: 'var(--muted)' }}>Accuracy:</span>
            <strong>{percent(hovered.accuracy)}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
            <span style={{ color: 'var(--muted)' }}>Cost / Doc:</span>
            <strong>{money(hovered.cost_per_doc ?? hovered.cost_usd)}</strong>
          </div>
          {hovered.composite != null && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
              <span style={{ color: 'var(--muted)' }}>Composite:</span>
              <strong>{hovered.composite.toFixed(2)}</strong>
            </div>
          )}
          {hovered.win_rate != null && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
              <span style={{ color: 'var(--muted)' }}>Win Rate:</span>
              <strong>{percent(hovered.win_rate)}</strong>
            </div>
          )}
          {(hovered.median_latency_ms ?? hovered.latency_ms) != null && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
              <span style={{ color: 'var(--muted)' }}>Median Latency:</span>
              <strong>{Math.round(hovered.median_latency_ms ?? hovered.latency_ms ?? 0).toLocaleString()} ms</strong>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

