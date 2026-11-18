import React, { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test-utils';
import { useGuide } from '../../../context/GuideContext';
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
  auto_publish_lead_hours: 6,
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

function GuideProbe() {
  const { isOpen, tab, section } = useGuide();
  return <span data-testid="guide">{`${isOpen}|${tab}|${section}`}</span>;
}

describe('WorkspaceSettingsSection', () => {
  it('is hidden when the platform has no workspaces', () => {
    const off = { isError: false, error: null, data: { available: false, images: [] } };
    expect(workspacesOffered(off)).toBe(false);
    expect(workspacesOffered({ isError: true, error: { status: 503 } })).toBe(true);
    expect(workspacesOffered({ isError: false, error: null, data: { available: true } })).toBe(
      true,
    );
    renderWithProviders(<Harness initial={workspaceDraft(null)} catalog={off} />);
    expect(screen.queryByTestId('workspace-settings')).not.toBeInTheDocument();
  });

  it('shows only the switch while off, then fills the catalog defaults', () => {
    const onDraft = vi.fn();
    renderWithProviders(<Harness initial={workspaceDraft(null)} onDraft={onDraft} />);
    expect(screen.getByText('Student workspaces')).toBeInTheDocument();
    expect(screen.queryByText('CPU profile')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Give students a workspace'));
    expect(onDraft).toHaveBeenLastCalledWith(
      expect.objectContaining({
        enabled: true,
        image_id: 'python-ml',
        profile_id: 'cpu-compact',
        workspace_gib: 10,
      }),
    );
    expect(screen.getByRole('combobox', { name: /Machine/ })).toHaveTextContent(
      'CPU Compact (2 vCPU, 8 GiB memory)',
    );
  });

  it('keeps the help to one line per field, with the disk of the stages that follow it', () => {
    renderWithProviders(
      <Harness
        initial={{ ...workspaceDraft(null), enabled: true, auto_publish: true }}
        environments={[
          { stage_id: 's1', stage_title: 'Round 1', data_gib: 3, disk_gib: 13 },
          { stage_id: 's3', stage_title: 'Round 3', data_gib: 5, disk_gib: 15 },
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
    const section = screen.getByTestId('workspace-settings');
    expect(
      screen.getByText('Applies to every stage. Published stages keep their settings.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Larger models need more memory')).toBeInTheDocument();
    expect(screen.getByText('10-98 GiB. Disk with task files: 13-15 GiB')).toBeInTheDocument();
    expect(screen.getByText('Round 2 is published and keeps 21 GiB')).toBeInTheDocument();
    expect(screen.getByLabelText('Publish automatically')).toHaveAccessibleDescription(
      '6 h before each stage starts',
    );
    expect(section).not.toHaveTextContent(/24 h|nanoColab/);
    expect(section).not.toHaveTextContent(/The disk is the|Workspaces open at each stage/);
  });

  it('adds the storage to the task data as it is typed', () => {
    renderWithProviders(<Harness initial={{ ...workspaceDraft(null), enabled: true }} />);
    expect(screen.getByText('10-98 GiB. Disk with task files: 10 GiB')).toBeInTheDocument();
    const size = screen.getByLabelText(/Storage per student \(GiB\)/);
    expect(size).toHaveAttribute('min', '10');
    expect(size).toHaveAttribute('max', '98');
    fireEvent.change(size, { target: { value: '25' } });
    expect(screen.getByText('10-98 GiB. Disk with task files: 25 GiB')).toBeInTheDocument();
  });

  it('folds the archive date under More options', () => {
    renderWithProviders(<Harness initial={{ ...workspaceDraft(null), enabled: true }} />);
    expect(screen.queryByLabelText('Keep archives until')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'More options' }));
    expect(screen.getByLabelText('Keep archives until')).toBeInTheDocument();
    expect(
      screen.getByText('Empty: 30 days after each stage ends (Europe/Sofia)'),
    ).toBeInTheDocument();
  });

  it('opens the admin guide at the workspaces section', () => {
    renderWithProviders(
      <>
        <Harness initial={workspaceDraft(null)} />
        <GuideProbe />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Learn more' }));
    expect(screen.getByTestId('guide')).toHaveTextContent('true|admin|10');
  });

  it('locks every field once all stages are published', () => {
    const published = { published_at: '2099-01-01T00:00:00Z', data_gib: 1, disk_gib: 11 };
    renderWithProviders(
      <Harness
        initial={{ ...workspaceDraft(null), enabled: true }}
        environments={[
          { ...published, stage_id: 's1', stage_title: 'Round 1' },
          { ...published, stage_id: 's2', stage_title: 'Round 2' },
        ]}
      />,
    );
    expect(
      screen.getByText('All stages are published, so these settings are locked.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Give students a workspace')).toBeDisabled();
    expect(screen.getByLabelText(/Storage per student/)).toBeDisabled();
  });

  it('offers a retry when the image list cannot load', () => {
    const refetch = vi.fn();
    renderWithProviders(
      <Harness
        initial={{ ...workspaceDraft(null), enabled: true }}
        catalog={{ data: undefined, isError: true, error: { status: 503 }, refetch }}
      />,
    );
    expect(screen.getByText('Could not load the image list from nanoColab.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('shows each field error under its field and clears it on edit', () => {
    const onFieldEdit = vi.fn();
    renderWithProviders(
      <Harness
        initial={{ ...workspaceDraft(null), enabled: true }}
        errors={{
          workspace_gib: 'Storage per student must be between 10 and 98 GiB.',
          profile_id: 'Machine must be one of: CPU Compact, CPU Standard.',
          image_id: 'Choose an image from the list.',
          archive_until: 'Keep archives until a date after the competition ends.',
        }}
        onFieldEdit={onFieldEdit}
      />,
    );
    const size = screen.getByLabelText(/Storage per student \(GiB\)/);
    expect(size).toHaveAttribute('aria-invalid', 'true');
    expect(
      screen.getByText('Storage per student must be between 10 and 98 GiB.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Machine must be one of: CPU Compact, CPU Standard.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Choose an image from the list.')).toBeInTheDocument();
    expect(screen.getByLabelText('Keep archives until')).toHaveAttribute('aria-invalid', 'true');
    expect(
      screen.getByText('Keep archives until a date after the competition ends.'),
    ).toBeInTheDocument();
    fireEvent.change(size, { target: { value: '20' } });
    expect(onFieldEdit).toHaveBeenCalledWith('workspace_gib');
  });

  it('keeps a stored profile nanoColab no longer lists', () => {
    renderWithProviders(
      <Harness initial={{ ...workspaceDraft(null), enabled: true, profile_id: 'cpu-old' }} />,
    );
    const select = screen.getByRole('combobox', { name: /Machine/ });
    expect(select).toHaveTextContent('cpu-old (no longer offered)');
    fireEvent.click(select);
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(3);
  });
});
