import { useCallback, useEffect, useRef, useState } from 'react';
import { revealElement } from '../utils/reveal';

/**
 * A ref and a `reveal()` that brings the referenced element into view after the next
 * render, for content that appears away from the control that chose it.
 * @param {{ focus?: 'field' | 'heading' | 'self' | null, singleColumnOnly?: boolean }} [options]
 * @returns {[import('react').RefObject<any>, () => void]}
 */
export function useReveal(options = {}) {
  const ref = useRef(null);
  const optionsRef = useRef(options);
  const [request, setRequest] = useState(0);

  useEffect(() => {
    optionsRef.current = options;
  });

  useEffect(() => {
    if (request) revealElement(ref.current, optionsRef.current);
  }, [request]);

  const reveal = useCallback(() => setRequest((n) => n + 1), []);
  return [ref, reveal];
}
