import { useState, useMemo, useEffect } from 'react'
import { cx } from './common'

export type Verdict = 'match' | 'mismatch' | 'missing' | 'neutral'
export function verdictFor(path: string, metrics?: Record<string, unknown>): Verdict {
  const raw = metrics?.[path]
  if (raw === true || raw === 'match' || (raw && typeof raw === 'object' && (raw as Record<string, unknown>).match === true)) return 'match'
  if (raw === false || raw === 'mismatch' || (raw && typeof raw === 'object' && (raw as Record<string, unknown>).match === false)) return 'mismatch'
  if (raw === 'missing') return 'missing'
  return 'neutral'
}

function escapeRegExp(string: string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function HighlightedText({ text, highlight }: { text: string; highlight: string }) {
  if (!highlight) return <>{text}</>;
  const parts = text.split(new RegExp(`(${escapeRegExp(highlight)})`, 'gi'));
  return (
    <>
      {parts.map((part, i) => 
        part.toLowerCase() === highlight.toLowerCase() ? (
          <mark key={i} className="json-search-match">{part}</mark>
        ) : (
          part
        )
      )}
    </>
  );
}

function tryParseJsonString(val: unknown): { isJson: boolean; parsed: unknown } {
  if (typeof val === 'string') {
    const trimmed = val.trim();
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        return { isJson: true, parsed: JSON.parse(trimmed) };
      } catch {
        /* not valid JSON — treat as a plain string */
      }
    }
  }
  return { isJson: false, parsed: null };
}

function hasMatchInObject(obj: unknown, queryLower: string): boolean {
  if (obj === null || typeof obj !== 'object') {
    const { isJson, parsed } = tryParseJsonString(obj);
    if (isJson) {
      return hasMatchInObject(parsed, queryLower);
    }
    return String(obj).toLowerCase().includes(queryLower);
  }
  for (const [k, v] of Object.entries(obj)) {
    if (k.toLowerCase().includes(queryLower)) return true;
    if (v === null) {
      if ('null'.includes(queryLower)) return true;
    } else if (typeof v !== 'object') {
      const { isJson, parsed } = tryParseJsonString(v);
      if (isJson) {
        if (hasMatchInObject(parsed, queryLower)) return true;
      } else {
        if (String(v).toLowerCase().includes(queryLower)) return true;
      }
    } else {
      if (hasMatchInObject(v, queryLower)) return true;
    }
  }
  return false;
}

function countMatches(val: unknown, queryLower: string): number {
  if (!queryLower) return 0;
  let count = 0;
  if (val === null) {
    return 'null'.includes(queryLower) ? 1 : 0;
  }
  if (typeof val !== 'object') {
    const { isJson, parsed } = tryParseJsonString(val);
    if (isJson) {
      return countMatches(parsed, queryLower);
    }
    return String(val).toLowerCase().includes(queryLower) ? 1 : 0;
  }
  for (const [k, v] of Object.entries(val)) {
    if (k.toLowerCase().includes(queryLower)) {
      count++;
    }
    if (v === null) {
      if ('null'.includes(queryLower)) count++;
    } else if (typeof v !== 'object') {
      const { isJson, parsed } = tryParseJsonString(v);
      if (isJson) {
        count += countMatches(parsed, queryLower);
      } else {
        if (String(v).toLowerCase().includes(queryLower)) count++;
      }
    } else {
      count += countMatches(v, queryLower);
    }
  }
  return count;
}

function JsonNode({
  name,
  value,
  metrics,
  path,
  searchQuery,
  expandAllTrigger,
  collapseAllTrigger
}: {
  name: string;
  value: unknown;
  metrics?: Record<string, unknown>;
  path: string;
  searchQuery: string;
  expandAllTrigger: number;
  collapseAllTrigger: number;
}) {
  const { isJson: isNestedJson, parsed: resolvedValue } = useMemo(() => {
    return tryParseJsonString(value);
  }, [value]);

  const targetValue = isNestedJson ? resolvedValue : value;
  const nested = targetValue !== null && typeof targetValue === 'object';
  const isArray = Array.isArray(targetValue);
  
  const containsMatch = useMemo(() => {
    if (!searchQuery) return false;
    const q = searchQuery.toLowerCase();
    if (name.toLowerCase().includes(q)) return true;
    return hasMatchInObject(targetValue, q);
  }, [targetValue, name, searchQuery]);

  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (expandAllTrigger > 0) {
      setOpen(true);
    }
  }, [expandAllTrigger]);

  useEffect(() => {
    if (collapseAllTrigger > 0) {
      setOpen(false);
    }
  }, [collapseAllTrigger]);

  useEffect(() => {
    if (containsMatch) {
      setOpen(true);
    }
  }, [containsMatch]);

  const verdict = verdictFor(path, metrics);

  if (!nested) {
    let valElement;
    if (targetValue === null) {
      valElement = <span className="json-val-null"><HighlightedText text="null" highlight={searchQuery} /></span>;
    } else if (typeof targetValue === 'boolean') {
      valElement = <span className="json-val-boolean"><HighlightedText text={String(targetValue)} highlight={searchQuery} /></span>;
    } else if (typeof targetValue === 'number') {
      valElement = <span className="json-val-number"><HighlightedText text={String(targetValue)} highlight={searchQuery} /></span>;
    } else {
      valElement = <span className="json-val-string">"<HighlightedText text={String(targetValue)} highlight={searchQuery} />"</span>;
    }

    return (
      <div className={cx('json-row', verdict)}>
        <span className="json-key-bullet">·</span>
        <span className="json-key-name">
          {name}:
        </span>{' '}
        {valElement}
      </div>
    );
  }

  const keys = Object.keys(targetValue as Record<string, unknown>);
  const size = keys.length;

  return (
    <div className={cx('json-node', verdict)}>
      <div className="json-node-header">
        <button
          type="button"
          className="json-key-toggle"
          onClick={() => setOpen(!open)}
        >
          {open ? '▾' : '▸'}
        </button>
        <span className="json-key-name" onClick={() => setOpen(!open)} style={{ cursor: 'pointer' }}>
          <HighlightedText text={name} highlight={searchQuery} />
        </span>
        {isNestedJson && <span className="json-string-badge">JSON String</span>}
        {!open && (
          <span className="json-collapsed-preview" onClick={() => setOpen(!open)}>
            {isArray ? `[...] (${size} items)` : `{...} (${size} keys)`}
          </span>
        )}
      </div>

      {open && (
        <div className="json-tree-nested">
          <span className="json-bracket">{isArray ? '[' : '{'}</span>
          <div className="json-tree-body">
            {keys.map((key) => {
              const childVal = (targetValue as Record<string, unknown>)[key];
              return (
                <JsonNode
                  key={key}
                  name={key}
                  value={childVal}
                  metrics={metrics}
                  path={path ? `${path}.${key}` : key}
                  searchQuery={searchQuery}
                  expandAllTrigger={expandAllTrigger}
                  collapseAllTrigger={collapseAllTrigger}
                />
              );
            })}
          </div>
          <span className="json-bracket">{isArray ? ']' : '}'}</span>
        </div>
      )}
    </div>
  );
}

export function JsonDiffTree({
  value,
  metrics,
  path = '',
  searchable = true
}: {
  value: unknown;
  metrics?: Record<string, unknown>;
  path?: string;
  searchable?: boolean;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [expandAllTrigger, setExpandAllTrigger] = useState(0);
  const [collapseAllTrigger, setCollapseAllTrigger] = useState(0);

  const isRoot = path === '';

  const { isJson: isNestedJson, parsed: resolvedValue } = useMemo(() => {
    return tryParseJsonString(value);
  }, [value]);

  const targetValue = isNestedJson ? resolvedValue : value;

  const totalMatches = useMemo(() => {
    if (!searchQuery) return 0;
    return countMatches(targetValue, searchQuery.toLowerCase());
  }, [targetValue, searchQuery]);

  const treeContent = useMemo(() => {
    if (targetValue === null || typeof targetValue !== 'object') {
      let valElement;
      if (targetValue === null) {
        valElement = <span className="json-val-null">null</span>;
      } else if (typeof targetValue === 'boolean') {
        valElement = <span className="json-val-boolean">{String(targetValue)}</span>;
      } else if (typeof targetValue === 'number') {
        valElement = <span className="json-val-number">{String(targetValue)}</span>;
      } else {
        valElement = <span className="json-val-string">"{String(targetValue)}"</span>;
      }
      return <code className={cx('json-value', verdictFor(path, metrics))}>{valElement}</code>;
    }

    const isArray = Array.isArray(targetValue);
    const keys = Object.keys(targetValue as Record<string, unknown>);

    return (
      <div className="json-tree-root">
        {isNestedJson && <div style={{ marginBottom: '0.4rem' }}><span className="json-string-badge">JSON String payload</span></div>}
        <span className="json-bracket">{isArray ? '[' : '{'}</span>
        <div className="json-tree-body">
          {keys.map((key) => {
            const childVal = (targetValue as Record<string, unknown>)[key];
            return (
              <JsonNode
                key={key}
                name={key}
                value={childVal}
                metrics={metrics}
                path={path ? `${path}.${key}` : key}
                searchQuery={searchQuery}
                expandAllTrigger={expandAllTrigger}
                collapseAllTrigger={collapseAllTrigger}
              />
            );
          })}
        </div>
        <span className="json-bracket">{isArray ? ']' : '}'}</span>
      </div>
    );
  }, [targetValue, isNestedJson, metrics, path, searchQuery, expandAllTrigger, collapseAllTrigger]);

  if (!isRoot) {
    return treeContent;
  }

  return (
    <div className="json-viewer-container">
      {searchable && (
        <div className="json-viewer-header">
          <div className="json-search-box">
            <input
              type="text"
              placeholder="Search JSON..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="json-search-input"
            />
            {searchQuery && (
              <span className="json-search-count">
                {totalMatches} match{totalMatches !== 1 ? 'es' : ''}
              </span>
            )}
          </div>
          <div className="json-viewer-actions">
            <button
              type="button"
              className="small"
              onClick={() => setExpandAllTrigger((prev) => prev + 1)}
            >
              Expand All
            </button>
            <button
              type="button"
              className="small"
              onClick={() => setCollapseAllTrigger((prev) => prev + 1)}
            >
              Collapse All
            </button>
          </div>
        </div>
      )}
      <div className="json-viewer-content">{treeContent}</div>
    </div>
  );
}
