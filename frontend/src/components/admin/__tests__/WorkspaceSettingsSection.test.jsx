import React, { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import WorkspaceSettingsSection from '../WorkspaceSettingsSection';
import { workspacesOffered } from '../../../hooks/useEnvironmentQuery';
import { workspaceDraft } from '../../../utils/workspaceSetting';

const CATALOG = {
  images: [
    { image_id: 'python-ml', name: 'Python ML (CPU)', packages: [], default: true },
    { image_id: 'python-base', name: 'Python', packages: [], default: false },
  ],
  profiles: [
    { id: 'cpu-compact', name: 'CPU Compact', cpu_cores: 2, memory_gib: 8 },
    { id: 'cpu-standard', name: 'CPU Standard', cpu_cores: 2, memory_gib: 12 },
  ],
  workspace_gib: { min: 10, max: 98, default: 10 },
};
const loaded = { data: CATALOG, isError: false, error: null };

function Harness({ initial, catalog = loaded, onDraft = vi.fn(), ...props }) {
  const [draft, setDraft] = useState(initial);
  return (
    <WorkspaceSettingsSection
      draft={draft}
      onChange={(next) => {
        onDraft(next);
        setDraft(next);
      }}
      catalog={catalog}
      timezone="Europe/Sofia"
      {...props}
    />
  );
}

describe('WorkspaceSettingsSection', () => {
  it('is hidden when the platform has no workspaces', () => {
    const off = { isError: true, error: { status: 404 } };
    expect(workspacesOffered(off)).toBe(false);
    expect(workspacesOffered({ isError: true, error: { status: 503 } })).toBe(true);
    const { container } = render(<Harness initial={workspaceDraft(null)} catalog={off} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows only the switch while off, then fills the catalog defaults', () => {
    const onDraft = vi.fn();
    render(<Harness initial={workspaceDraft(null)} onDraft={onDraft} />);
    expect(screen.getByText('Student workspaces')).toBeInTheDocument();
    expect(screen.queryByText('CPU profile')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Give students a nanoColab workspace'));
    expect(onDraft).toHaveBeenLastCalledWith(
      expect.objectContaining({
        enabled: true,
        image_id: 'python-ml',
        profile_id: 'cpu-compact',
        workspace_gib: 10,
      }),
    );
    expect(screen.getByRole('combobox', { name: /CPU profile/ })).toHaveTextContent(
      'CPU Compact (2 vCPU, 8 GiB memory)',
    );
  });

  it('explains the setting, the profiles, the disk and the schedule', () => {
    render(
      <Harness
        initial={{ ...workspaceDraft(null), enabled: true }}
        environments={[
          { stage_id: 's1', stage_title: 'Round 1', data_gib: 3, disk_gib: 13 },
          {
            stage_id: 's2',
            stage_title: 'Round 2',
            data_gib: 1,
            disk_gib: 21,
            published_at: '2099-01-01T00:00:00Z',
          },
        ]}
      />,
    );
    expect(screen.getByText(/One setting for the whole competition/)).toBeInTheDocument();
    expect(screen.getByText(/Profiles differ in memory/)).toBeInTheDocument();
    expect(
      screen.getByText("10 to 98 GiB for the student's own files and outputs."),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Round 1: 10 GiB work space + 3 GiB task data = 13 GiB'),
    ).toBeInTheDocument();
    expect(screen.getByText('Round 2: 21 GiB (published, locked)')).toBeInTheDocument();
    expect(screen.getByText(/The disk is the work space plus the task data/)).toBeInTheDocument();
    expect(screen.getByText(/Workspaces open at each stage's start/)).toBeInTheDocument();
    expect(screen.getByText(/Time zone: Europe\/Sofia/)).toBeInTheDocument();
  });

  it('adds the work space to the task data as it is typed', () => {
    render(<Harness initial={{ ...workspaceDraft(null), enabled: true }} />);
    expect(screen.getByText('10 GiB work space + 0 GiB task data = 10 GiB')).toBeInTheDocument();
    const size = screen.getByLabelText(/Work space \(GiB\)/);
    expect(size).toHaveAttribute('min', '10');
    expect(size).toHaveAttribute('max', '98');
    fireEvent.change(size, { target: { value: '25' } });
    expect(screen.getByText('25 GiB work space + 0 GiB task data = 25 GiB')).toBeInTheDocument();
  });

  it('shows each field error under its field and clears it on edit', () => {
    const onFieldEdit = vi.fn();
    render(
      <Harness
        initial={{ ...workspaceDraft(null), enabled: true }}
        errors={{
          workspace_gib: 'Work space must be between 10 and 98 GiB.',
          profile_id: 'Profile must be one of: CPU Compact, CPU Standard.',
          image_id: 'Choose a workspace image from the list.',
          archive_until: 'Keep archives until a date after the competition ends.',
        }}
        onFieldEdit={onFieldEdit}
      />,
    );
    const size = screen.getByLabelText(/Work space \(GiB\)/);
    expect(size).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Work space must be between 10 and 98 GiB.')).toBeInTheDocument();
    expect(
      screen.getByText('Profile must be one of: CPU Compact, CPU Standard.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Choose a workspace image from the list.')).toBeInTheDocument();
    expect(
      screen.getByText('Keep archives until a date after the competition ends.'),
    ).toBeInTheDocument();
    fireEvent.change(size, { target: { value: '20' } });
    expect(onFieldEdit).toHaveBeenCalledWith('workspace_gib');
  });

  it('keeps a stored profile nanoColab no longer lists', () => {
    render(<Harness initial={{ ...workspaceDraft(null), enabled: true, profile_id: 'cpu-old' }} />);
    const select = screen.getByRole('combobox', { name: /CPU profile/ });
    expect(select).toHaveTextContent('cpu-old (no longer offered)');
    fireEvent.click(select);
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(3);
  });
});
