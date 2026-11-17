import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SidebarNav from '../SidebarNav';

const ADMIN_TABS = [
  'Manage Competitions & Tasks',
  'Create Competition',
  'Competitor Registrations',
  'Database Backup',
  'User Management',
  'Audit Logs',
  'Workers and queues',
  'Submission Queue',
];

function tabNames() {
  return screen.getAllByRole('button').map((button) => button.textContent);
}

describe('SidebarNav', () => {
  it('shows every tab to an admin', () => {
    render(
      <SidebarNav
        adminSubTab="competition-mgmt"
        onSelectTab={vi.fn()}
        currentUser={{ role: 'admin' }}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Jury Control Hub' })).toBeInTheDocument();
    expect(tabNames()).toEqual(ADMIN_TABS);
  });

  it('shows the jury its tabs only', () => {
    render(
      <SidebarNav
        adminSubTab="competition-mgmt"
        onSelectTab={vi.fn()}
        currentUser={{ role: 'jury' }}
      />,
    );
    expect(tabNames()).toEqual([
      'Manage Competitions & Tasks',
      'Competitor Registrations',
      'Workers and queues',
      'Submission Queue',
    ]);
  });

  it('shows any other role the registrations tab only', () => {
    render(
      <SidebarNav
        adminSubTab="competitor-reg"
        onSelectTab={vi.fn()}
        currentUser={{ role: 'competitor' }}
      />,
    );
    expect(tabNames()).toEqual(['Competitor Registrations']);
  });

  it('marks the active tab with aria-current', () => {
    render(
      <SidebarNav adminSubTab="backups" onSelectTab={vi.fn()} currentUser={{ role: 'admin' }} />,
    );
    expect(screen.getByRole('button', { name: 'Database Backup' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('button', { name: 'User Management' })).not.toHaveAttribute(
      'aria-current',
    );
  });

  it('selects a tab by its id', () => {
    const onSelectTab = vi.fn();
    render(
      <SidebarNav
        adminSubTab="competition-mgmt"
        onSelectTab={onSelectTab}
        currentUser={{ role: 'admin' }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Audit Logs' }));
    expect(onSelectTab).toHaveBeenCalledWith('audit-logs');
    fireEvent.click(screen.getByRole('button', { name: 'Submission Queue' }));
    expect(onSelectTab).toHaveBeenLastCalledWith('submission-queue');
  });
});
