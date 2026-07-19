import React, { useRef, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function TabScrollContainer({ children }) {
  const { t } = useTranslation();
  const scrollRef = useRef(null);
  const [showLeftArrow, setShowLeftArrow] = useState(false);
  const [showRightArrow, setShowRightArrow] = useState(false);

  const checkScroll = () => {
    if (!scrollRef.current) return;
    const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current;
    setShowLeftArrow(scrollLeft > 2);
    // Use a small tolerance for subpixel rendering issues
    setShowRightArrow(scrollLeft + clientWidth < scrollWidth - 2);
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    checkScroll();

    // Add event listeners
    el.addEventListener('scroll', checkScroll);
    window.addEventListener('resize', checkScroll);

    // Watch for children changes using ResizeObserver
    const observer = new ResizeObserver(() => checkScroll());
    observer.observe(el);

    return () => {
      el.removeEventListener('scroll', checkScroll);
      window.removeEventListener('resize', checkScroll);
      observer.disconnect();
    };
  }, [children]);

  const scroll = (direction) => {
    if (!scrollRef.current) return;
    const { clientWidth } = scrollRef.current;
    const scrollAmount = clientWidth * 0.75; // Scroll 75% of container width
    scrollRef.current.scrollBy({
      left: direction === 'left' ? -scrollAmount : scrollAmount,
      behavior: 'smooth',
    });
  };

  return (
    <div className="relative flex items-center w-full group">
      {/* Left scroll arrow */}
      {showLeftArrow && (
        <button
          type="button"
          onClick={() => scroll('left')}
          className="absolute left-0 z-10 flex items-center justify-center w-7 h-7 bg-slate-900/90 border border-slate-800 rounded-full text-slate-400 hover:text-white shadow-lg backdrop-blur-sm hover:border-slate-700 cursor-pointer transition-all -ml-3"
          title={t('common.scroll_left')}
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      )}

      {/* Scrollable area */}
      <div
        ref={scrollRef}
        className="w-full flex gap-2 overflow-x-auto scroll-smooth no-scrollbar"
        style={{
          scrollbarWidth: 'none' /* Firefox */,
          msOverflowStyle: 'none' /* IE 10+ */,
        }}
      >
        {/* Hide scrollbar for Webkit */}
        <style
          dangerouslySetInnerHTML={{
            __html: `
          div::-webkit-scrollbar {
            display: none !important;
          }
        `,
          }}
        />
        {children}
      </div>

      {/* Right scroll arrow */}
      {showRightArrow && (
        <button
          type="button"
          onClick={() => scroll('right')}
          className="absolute right-0 z-10 flex items-center justify-center w-7 h-7 bg-slate-900/90 border border-slate-800 rounded-full text-slate-400 hover:text-white shadow-lg backdrop-blur-sm hover:border-slate-700 cursor-pointer transition-all -mr-3"
          title={t('common.scroll_right')}
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
