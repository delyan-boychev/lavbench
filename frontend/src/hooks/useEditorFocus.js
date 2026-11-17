import { useEffect, useState } from 'react';
import { returnToTrigger, revealElement } from '../utils/reveal';

// The data-return-id of the last clicked trigger, read by the editor that click opens
let lastTriggerId = /** @type {string | null} */ (null);

if (typeof document !== 'undefined') {
  document.addEventListener(
    'click',
    (event) => {
      const target = /** @type {Element | null} */ (event.target);
      lastTriggerId = target?.closest?.('[data-return-id]')?.getAttribute('data-return-id') ?? null;
    },
    true,
  );
}

/**
 * Show an editor or sub-view from its top when it opens, and send the focus back to the
 * button that opened it (marked with `data-return-id`) when it closes.
 * @param {import('react').RefObject<HTMLElement | null>} ref
 * @param {{ focus?: 'field' | 'heading' | null }} [options]
 */
export function useEditorFocus(ref, { focus = 'field' } = {}) {
  const [returnId] = useState(() => lastTriggerId);
  const [initialFocus] = useState(focus);

  useEffect(() => {
    if (initialFocus) revealElement(ref.current, { focus: initialFocus });
    return () => {
      // The list that holds the trigger renders in the same commit as this unmount
      if (returnId) setTimeout(() => returnToTrigger(returnId), 0);
    };
  }, [ref, returnId, initialFocus]);
}
