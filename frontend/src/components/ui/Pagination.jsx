import React from 'react';
import { useTranslation } from 'react-i18next';
import Button from './Button';
import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function Pagination({
  page,
  pages,
  total = 0,
  perPage = 10,
  onPageChange,
  itemName = 'items',
  className = ''
}) {
  const { t } = useTranslation();
  if (pages <= 1 && total === 0) return null;

  const startIdx = total === 0 ? 0 : (page - 1) * perPage + 1;
  const endIdx = Math.min(page * perPage, total);

  // Generate page numbers array with ellipses
  const getPageNumbers = () => {
    const list = [];
    if (pages <= 5) {
      for (let i = 1; i <= pages; i++) list.push(i);
    } else {
      list.push(1);
      
      if (page > 3) {
        list.push('ellipsis-start');
      }

      const start = Math.max(2, page - 1);
      const end = Math.min(pages - 1, page + 1);

      for (let i = start; i <= end; i++) {
        list.push(i);
      }

      if (page < pages - 2) {
        list.push('ellipsis-end');
      }

      list.push(pages);
    }
    return list;
  };

  const pageNumbers = getPageNumbers();

  return (
    <div className={`flex flex-col sm:flex-row justify-between items-center gap-4 mt-4 pt-4 border-t border-slate-800 text-xs text-slate-400 ${className}`}>
      {/* Item Range Label */}
      <div>
        {total > 0 ? (
          <span>
            {t('common.showing')} <strong className="text-slate-200">{startIdx}-{endIdx}</strong> {t('common.of')} <strong className="text-slate-200">{total}</strong> {itemName}
          </span>
        ) : (
          <span>{t('common.page_of', { page, pages })}</span>
        )}
      </div>

      {/* Navigation Controls */}
      <div className="flex items-center gap-1.5">
        {/* Previous Button */}
        <Button
          variant="secondary"
          className="btn-sm px-2.5 py-1.5"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          title={t('common.prev_page')}
        >
          <ChevronLeft size={14} />
        </Button>

        {/* Page Buttons */}
        <div className="flex items-center gap-1">
          {pageNumbers.map((p, idx) => {
            if (p === 'ellipsis-start' || p === 'ellipsis-end') {
              return (
                <span key={`ellipse-${idx}`} className="px-2 text-slate-500 font-bold select-none">
                  ...
                </span>
              );
            }

            const isCurrent = p === page;
            return (
              <button
                key={`page-${p}`}
                type="button"
                onClick={() => onPageChange(p)}
                className={`w-7 h-7 flex items-center justify-center rounded-lg font-semibold border text-[11px] transition-all cursor-pointer ${
                  isCurrent
                    ? 'bg-indigo-600 border-indigo-500/30 text-white font-bold'
                    : 'bg-slate-900/60 hover:bg-slate-800 border-slate-800 text-slate-300 hover:text-slate-100'
                }`}
              >
                {p}
              </button>
            );
          })}
        </div>

        {/* Next Button */}
        <Button
          variant="secondary"
          className="btn-sm px-2.5 py-1.5"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
          title={t('common.next_page')}
        >
          <ChevronRight size={14} />
        </Button>
      </div>
    </div>
  );
}
