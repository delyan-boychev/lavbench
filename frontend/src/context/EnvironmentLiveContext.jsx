import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import useSSEInvalidation from '../hooks/useSSEInvalidation';
import { environmentKeys } from '../hooks/useEnvironmentQuery';
import EnvironmentService from '../services/EnvironmentService';

const EnvironmentLiveContext = createContext(null);

function LiveStream({ challengeId, onInterval }) {
  const { refetchInterval } = useSSEInvalidation(
    EnvironmentService.liveUrl(challengeId),
    environmentKeys.challenge(challengeId),
  );
  useEffect(() => {
    onInterval(challengeId, refetchInterval);
  }, [challengeId, refetchInterval, onInterval]);
  useEffect(() => () => onInterval(challengeId, undefined), [challengeId, onInterval]);
  return null;
}

/** Holds one environment stream per competition, shared by every panel and card on the page. */
export function EnvironmentLiveProvider({ children }) {
  const [subscribers, setSubscribers] = useState(/** @type {Record<string, number>} */ ({}));
  const [intervals, setIntervals] = useState(/** @type {Record<string, number | false>} */ ({}));

  const subscribe = useCallback((id) => {
    setSubscribers((prev) => ({ ...prev, [id]: (prev[id] || 0) + 1 }));
    return () =>
      setSubscribers((prev) => {
        const next = { ...prev };
        if (next[id] > 1) next[id] -= 1;
        else delete next[id];
        return next;
      });
  }, []);

  const report = useCallback((id, interval) => {
    setIntervals((prev) => {
      if (prev[id] === interval) return prev;
      const next = { ...prev };
      if (interval === undefined) delete next[id];
      else next[id] = interval;
      return next;
    });
  }, []);

  const value = useMemo(() => ({ subscribe, intervals }), [subscribe, intervals]);

  return (
    <EnvironmentLiveContext.Provider value={value}>
      {children}
      {Object.keys(subscribers).map((id) => (
        <LiveStream key={id} challengeId={id} onInterval={report} />
      ))}
    </EnvironmentLiveContext.Provider>
  );
}

/**
 * Fallback poll interval while the competition's stream is down; false while it is live.
 * @param {string | number | null | undefined} challengeId
 * @returns {number | false}
 */
export function useEnvironmentLiveInterval(challengeId) {
  const context = useContext(EnvironmentLiveContext);
  return context?.intervals[String(challengeId)] ?? false;
}

/**
 * Keep the competition's shared stream open while `active`.
 * @param {string | number | null | undefined} challengeId
 * @param {boolean} active
 */
export function useEnvironmentLiveSubscription(challengeId, active) {
  const subscribe = useContext(EnvironmentLiveContext)?.subscribe;
  useEffect(() => {
    if (!subscribe || !active || !challengeId) return undefined;
    return subscribe(String(challengeId));
  }, [subscribe, active, challengeId]);
}
