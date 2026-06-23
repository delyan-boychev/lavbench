import React, { useState } from 'react';
import CodeHighlight from './CodeHighlight';
import { ChevronDown, ChevronRight } from 'lucide-react';

export default function CodePreview({
  cells,
  defaultCollapsed = true,
  maxHeight = '300px',
  selectable = false,
  selectedIds = [],
  onSelectionChange,
}) {
  if (!cells || cells.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {cells.map((cell, idx) => (
        <CodeCell
          key={idx}
          cell={cell}
          idx={idx}
          defaultCollapsed={defaultCollapsed}
          maxHeight={maxHeight}
          selectable={selectable}
          selected={selectedIds.includes(cell.id ?? idx)}
          onToggleSelect={
            onSelectionChange
              ? () => {
                  const id = cell.id ?? idx;
                  onSelectionChange(
                    selectedIds.includes(id)
                      ? selectedIds.filter((sid) => sid !== id)
                      : [...selectedIds, id],
                  );
                }
              : undefined
          }
        />
      ))}
    </div>
  );
}

function CodeCell({
  cell,
  idx,
  defaultCollapsed,
  maxHeight,
  selectable,
  selected,
  onToggleSelect,
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const source = cell.source || '';
  const cellType = cell.type || 'code';
  const isCode = cellType === 'code';

  const previewLines = collapsed ? source.split('\n').slice(0, 3).join('\n') : source;
  const totalLines = source.split('\n').length;
  const hasMore = totalLines > 3 && collapsed;

  return (
    <div
      style={{
        border: `1px solid ${selected ? 'var(--accent-border)' : 'var(--border)'}`,
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
        background: selected ? 'var(--accent-soft)' : 'transparent',
        transition: 'all 0.12s ease',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 10px',
          background: 'var(--bg-elevated)',
          borderBottom: collapsed ? 'none' : '1px solid var(--border)',
        }}
      >
        {selectable && isCode && (
          <label
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggleSelect}
              className="sr-only peer"
            />
            <div className="relative w-7 h-4 bg-slate-700 rounded-full peer peer-checked:after:translate-x-[12px] peer-checked:bg-indigo-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-400 peer-checked:after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all" />
          </label>
        )}
        {selectable && !isCode && <div style={{ width: 7, flexShrink: 0 }} />}
        <button
          onClick={() => setCollapsed(!collapsed)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            fontSize: '11px',
            fontWeight: 600,
            color: isCode ? 'var(--accent)' : 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            padding: 0,
          }}
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          <span>
            Cell [{idx}] — {cellType}
          </span>
        </button>
        {hasMore && (
          <span style={{ color: 'var(--text-muted)', marginLeft: 'auto', fontSize: '10px' }}>
            {totalLines} lines
          </span>
        )}
      </div>
      <div style={{ display: collapsed ? 'none' : 'block' }}>
        <CodeHighlight
          code={collapsed ? previewLines : source}
          language={isCode ? 'python' : 'markdown'}
          wrap={true}
          maxHeight={maxHeight}
        />
      </div>
    </div>
  );
}
