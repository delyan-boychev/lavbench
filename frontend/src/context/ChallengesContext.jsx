import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useChallengesQuery } from '../hooks/useChallengesQuery';

const ChallengesContext = createContext(null);

export const ChallengesProvider = ({ children }) => {
  const { data: challenges = [], isLoading } = useChallengesQuery();
  const [selectedChallenge, setSelectedChallengeState] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);

  // Auto-select first challenge when data loads
  useEffect(() => {
    if (challenges.length > 0) {
      setSelectedChallengeState((prev) => {
        if (prev && challenges.find((c) => c.id === prev.id)) return prev;
        return challenges[0];
      });
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

  return (
    <ChallengesContext.Provider
      value={{
        challenges,
        selectedChallenge,
        setSelectedChallengeById,
        setSelectedChallenge: setSelectedChallengeState,
        selectedTask,
        setSelectedTask,
        fetchChallenges: () => {
          /* no-op: TanStack Query handles refetching */
        },
      }}
    >
      {children}
    </ChallengesContext.Provider>
  );
};

export const useChallenges = () => {
  const ctx = useContext(ChallengesContext);
  if (!ctx) throw new Error('useChallenges must be used within ChallengesProvider');
  return ctx;
};
