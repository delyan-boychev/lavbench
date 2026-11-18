import React from 'react';

/**
 * Key facts as label and value rows, the summary list pattern.
 * @param {{
 *   items: { key?: string, label: React.ReactNode, value: React.ReactNode }[],
 *   className?: string,
 * }} props
 */
export default function SummaryList({
  items,
  className = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3',
}) {
  return (
    <dl className={className}>
      {items.map((item, index) => (
        <div
          key={item.key || (typeof item.label === 'string' ? item.label : index)}
          className="flex flex-col gap-0.5 min-w-0"
        >
          <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            {item.label}
          </dt>
          <dd className="text-xs text-slate-200 break-words">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
