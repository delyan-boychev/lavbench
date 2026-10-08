import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useChallengesQuery } from '../hooks/useChallengesQuery';

const MAX_TIMEOUT_MS = 2 ** 31 - 1;

// The backend only returns tasks of started challenges/stages, so the list must
// be refetched when the next start or end time passes
function nextBoundaryMs(challenges, now) {
  let next = Infinity;
  for (const c of Array.isArray(challenges) ? challenges : []) {
    const times = [c.start_time, c.end_time];
    for (const st of c.stages || []) times.push(st.start_time, st.end_time);
    for (const time of times) {
      const ms = time ? new Date(time).getTime() : NaN;
      if (ms > now && ms < next) next = ms;
    }
  }
  return next;
}

const ChallengesContext = createContext(null);

// TanStack Query handles refetching; kept for API compatibility
const noop = () => {};

export const ChallengesProvider = ({ children, userId }) => {
  const { data: challenges = [], isLoading } = useChallengesQuery(userId);
  const [selectedChallenge, setSelectedChallengeState] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    const delay = nextBoundaryMs(challenges, Date.now()) - Date.now();
    if (!Number.isFinite(delay) || delay > MAX_TIMEOUT_MS) return;
    // Jitter spreads the refetch so every open tab does not hit the API at once
    const jitter = 500 + Math.random() * 2500;
    const timer = setTimeout(
      () => queryClient.invalidateQueries({ queryKey: ['challenges'] }),
      delay + jitter,
    );
    return () => clearTimeout(timer);
  }, [challenges, queryClient]);

  // Auto-select first challenge when data loads
  useEffect(() => {
    if (challenges.length > 0) {
      setSelectedChallengeState(
        (prev) => challenges.find((c) => c.id === prev?.id) || challenges[0],
      );
    } else if (!isLoading) {
      setSelectedChallengeState(null);
      setSelectedTask(null);
    }
  }, [challenges, isLoading]);

  useEffect(() => {
    if (selectedChallenge) {
      setSelectedTask((t) => {
        if (!t) return selectedChallenge.tasks?.[0] || null;
        const found = selectedChallenge.tasks?.find((tk) => tk.id === t.id);
        return found || selectedChallenge.tasks?.[0] || null;
      });
    }
  }, [selectedChallenge]);

  const setSelectedChallengeById = useCallback(
    (id) => {
      if (!id) {
        setSelectedChallengeState(null);
        setSelectedTask(null);
        return;
      }
      const c = challenges.find((ch) => ch.id === id);
      if (c) {
        setSelectedChallengeState(c);
        setSelectedTask(c.tasks?.[0] || null);
      }
    },
    [challenges],
  );

  const value = useMemo(
    () => ({
      challenges,
      selectedChallenge,
      setSelectedChallengeById,
      setSelectedChallenge: setSelectedChallengeState,
      selectedTask,
      setSelectedTask,
      fetchChallenges: noop,
    }),
    [challenges, selectedChallenge, setSelectedChallengeById, selectedTask],
  );

  return <ChallengesContext.Provider value={value}>{children}</ChallengesContext.Provider>;
};

export const useChallenges = () => {
  const ctx = useContext(ChallengesContext);
  if (!ctx) throw new Error('useChallenges must be used within ChallengesProvider');
  return ctx;
};
