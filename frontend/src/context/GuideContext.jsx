import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

const GuideContext = createContext(null);

const CLOSED = { isOpen: false, tab: 'competitor', section: null };

/**
 * Which in-app guide is open, and the numbered section to scroll to (for "Learn more" links).
 * The state starts over when the signed-in user changes, so no one inherits another's guide.
 * @param {{ userId?: string | number | null, children: React.ReactNode }} props
 */
export function GuideProvider({ userId = null, children }) {
  const [state, setState] = useState(CLOSED);
  const [stateUser, setStateUser] = useState(userId);
  if (userId !== stateUser) {
    setStateUser(userId);
    setState(CLOSED);
  }

  /** Open the guide, optionally on a tab and at a numbered section ("10" is "## 10. ..."). */
  const openGuide = useCallback(
    (tab = null, section = null) =>
      setState((prev) => ({ isOpen: true, tab: tab || prev.tab, section })),
    [],
  );
  const closeGuide = useCallback(
    () => setState((prev) => ({ ...prev, isOpen: false, section: null })),
    [],
  );
  const selectTab = useCallback((tab) => setState((prev) => ({ ...prev, tab, section: null })), []);

  const value = useMemo(
    () => ({ ...state, openGuide, closeGuide, selectTab }),
    [state, openGuide, closeGuide, selectTab],
  );
  return <GuideContext.Provider value={value}>{children}</GuideContext.Provider>;
}

export const useGuide = () => {
  const ctx = useContext(GuideContext);
  if (!ctx) throw new Error('useGuide must be used within GuideProvider');
  return ctx;
};
