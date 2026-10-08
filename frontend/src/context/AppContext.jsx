import React, { useMemo } from 'react';
import { ThemeProvider } from './ThemeContext';
import { NotificationsProvider } from './NotificationsContext';
import { ChallengesProvider } from './ChallengesContext';
import { useTheme } from './ThemeContext';
import { useNotifications } from './NotificationsContext';
import { useChallenges } from './ChallengesContext';
import { useAuth } from '../AuthContext';

export const AppProvider = ({ children }) => {
  const { currentUser } = useAuth();

  return (
    <ThemeProvider>
      <NotificationsProvider>
        <ChallengesProvider userId={currentUser?.id}>{children}</ChallengesProvider>
      </NotificationsProvider>
    </ThemeProvider>
  );
};

// Toast state is intentionally excluded; read it with useToast() from NotificationsContext
export const useApp = () => {
  const theme = useTheme();
  const notifications = useNotifications();
  const challenges = useChallenges();
  return useMemo(
    () => ({ ...theme, ...notifications, ...challenges }),
    [theme, notifications, challenges],
  );
};
