import React from 'react';
import { ThemeProvider } from './ThemeContext';
import { NotificationsProvider } from './NotificationsContext';
import { ChallengesProvider } from './ChallengesContext';
import { useTheme } from './ThemeContext';
import { useNotifications } from './NotificationsContext';
import { useChallenges } from './ChallengesContext';

export const AppProvider = ({ children }) => {
  return (
    <ThemeProvider>
      <NotificationsProvider>
        <ChallengesProvider>{children}</ChallengesProvider>
      </NotificationsProvider>
    </ThemeProvider>
  );
};

export const useApp = () => {
  const theme = useTheme();
  const notifications = useNotifications();
  const challenges = useChallenges();
  return { ...theme, ...notifications, ...challenges };
};
