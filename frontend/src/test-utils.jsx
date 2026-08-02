import React from 'react';
import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './context/ThemeContext';
import { NotificationsProvider } from './context/NotificationsContext';
import { ChallengesProvider } from './context/ChallengesContext';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
}

function AllProviders({ children }) {
  const queryClient = createTestQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NotificationsProvider>
          <ChallengesProvider>{children}</ChallengesProvider>
        </NotificationsProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(ui, options = {}) {
  return render(ui, { wrapper: AllProviders, ...options });
}

export { createTestQueryClient, AllProviders };
