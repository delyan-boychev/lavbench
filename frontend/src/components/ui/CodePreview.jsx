import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import CodeHighlight from './CodeHighlight';
import { ChevronDown, ChevronRight } from 'lucide-react';

const EMPTY_SELECTION = new Set();

/**
 * @param {{
 *   cells: any[],
 *   defaultCollapsed?: boolean,
 *   maxHeight?: string,
 *   selectable?: boolean,
 *   selectedIds?: Set<any>,
 *   onToggleSelect?: ((id: any) => void) | null,
 * }} props
 */
export default function CodePreview({
  cells,
  defaultCollapsed = true,
  maxHeight = '300px',
  selectable = false,
  selectedIds = EMPTY_SELECTION,
  onToggleSelect = null,
}) {
  if (!cells || cells.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {cells.map((cell, idx) => {
        const id = cell.id ?? idx;
        return (
          <CodeCell
            key={id}
            id={id}
            cell={cell}
            idx={idx}
            defaultCollapsed={defaultCollapsed}
            maxHeight={maxHeight}
            selectable={selectable}
            selected={selectedIds.has(id)}
            onToggleSelect={onToggleSelect}
          />
        );
      })}
    </div>
  );
}

/**
 * @param {{
 *   id: any,
 *   cell: any,
 *   idx: number,
 *   defaultCollapsed: boolean,
 *   maxHeight: string,
 *   selectable: boolean,
 *   selected: boolean,
 *   onToggleSelect: ((id: any) => void) | null,
 * }} props
 */
function CodeCellView({
  id,
  cell,
  idx,
  defaultCollapsed,
  maxHeight,
  selectable,
  selected,
  onToggleSelect,
}) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const source = cell.source || '';
  const cellType = cell.type || 'code';
  const isCode = cellType === 'code';

  const totalLines = useMemo(() => source.split('\n').length, [source]);
  const hasMore = totalLines > 3 && collapsed;

  return (
    <div
      className="relative"
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
              onChange={() => onToggleSelect?.(id)}
              aria-label={t('submissions.select_cell', { id: idx })}
              className="sr-only peer"
            />
            <div className="relative w-7 h-4 bg-slate-700 rounded-full peer peer-checked:after:translate-x-[12px] peer-checked:bg-indigo-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-400 peer-checked:after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all" />
          </label>
        )}
        {selectable && !isCode && <div style={{ width: 7, flexShrink: 0 }} />}
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          aria-expanded={!collapsed}
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
          <span>{t('submissions.cell_label', { id: idx, type: cellType })}</span>
        </button>
        {hasMore && (
          <span style={{ color: 'var(--text-muted)', marginLeft: 'auto', fontSize: '10px' }}>
            {t('submissions.cell_lines', { count: totalLines })}
          </span>
        )}
      </div>
      {!collapsed && (
        <CodeHighlight
          code={source}
          language={isCode ? 'python' : 'markdown'}
          wrap={true}
          maxHeight={maxHeight}
        />
      )}
    </div>
  );
}

// Memoized so toggling one cell's selection does not re-highlight every other cell
const CodeCell = React.memo(CodeCellView);
