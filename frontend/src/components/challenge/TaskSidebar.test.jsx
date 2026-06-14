import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TaskSidebar from './TaskSidebar';

describe('TaskSidebar Component', () => {
  it('renders empty state when tasks is empty or null', () => {
    const { rerender } = render(<TaskSidebar tasks={null} onSelect={() => {}} />);
    expect(screen.getByText('No tasks published yet.')).toBeInTheDocument();

    rerender(<TaskSidebar tasks={[]} onSelect={() => {}} />);
    expect(screen.getByText('No tasks published yet.')).toBeInTheDocument();
  });

  it('renders task list items with correct title, index, description, and file indicators', () => {
    const tasks = [
      {
        id: 1,
        title: 'Task Alpha',
        description: 'First task description *with markdown* formatting.',
        files: ['file1.txt', 'file2.txt'],
      },
      {
        id: 2,
        title: 'Task Beta',
        description: 'Second task description.',
        files: [],
      },
    ];

    render(<TaskSidebar tasks={tasks} selectedTask={tasks[0]} onSelect={() => {}} />);

    // Header count
    expect(screen.getByText('Tasks (2)')).toBeInTheDocument();

    // Check Task 1
    expect(screen.getByText('Task #1')).toBeInTheDocument();
    expect(screen.getByText('Task Alpha')).toBeInTheDocument();
    expect(screen.getByText('First task description with markdown formatting.')).toBeInTheDocument(); // stripped markdown
    expect(screen.getByText('2')).toBeInTheDocument();

    // Check Task 2
    expect(screen.getByText('Task #2')).toBeInTheDocument();
    expect(screen.getByText('Task Beta')).toBeInTheDocument();
    expect(screen.getByText('Second task description.')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument(); // Beta has no files, shouldn't show files indicator
  });

  it('triggers onSelect callback when clicking a task button', () => {
    const tasks = [
      { id: 1, title: 'Task Alpha' },
      { id: 2, title: 'Task Beta' },
    ];
    const handleSelect = vi.fn();

    render(<TaskSidebar tasks={tasks} selectedTask={null} onSelect={handleSelect} />);

    fireEvent.click(screen.getByText('Task Beta'));
    expect(handleSelect).toHaveBeenCalledWith(tasks[1]);
  });
});
