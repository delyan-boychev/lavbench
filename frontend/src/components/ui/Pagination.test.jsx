import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Pagination from './Pagination';

describe('Pagination Component', () => {
  it('renders nothing when pages <= 1 and total is 0', () => {
    const { container } = render(
      <Pagination page={1} pages={1} total={0} onPageChange={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders range text and total correctly', () => {
    render(
      <Pagination
        page={1}
        pages={3}
        total={25}
        perPage={10}
        itemName="submissions"
        onPageChange={() => {}}
      />,
    );
    expect(screen.getByText(/Showing/)).toBeInTheDocument();
    expect(screen.getByText('1-10')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
    expect(screen.getByText(/submissions/)).toBeInTheDocument();
  });

  it('renders page number labels when total is 0', () => {
    render(<Pagination page={2} pages={5} total={0} onPageChange={() => {}} />);
    expect(screen.getByText('Page 2 of 5')).toBeInTheDocument();
  });

  it('triggers onPageChange when clicking page numbers', () => {
    const handlePageChange = vi.fn();
    render(<Pagination page={2} pages={5} total={0} onPageChange={handlePageChange} />);

    fireEvent.click(screen.getByText('3'));
    expect(handlePageChange).toHaveBeenCalledWith(3);
  });

  it('disables previous button on first page and next button on last page', () => {
    const { rerender } = render(
      <Pagination page={1} pages={3} total={30} perPage={10} onPageChange={() => {}} />,
    );
    expect(screen.getByTitle('Previous Page')).toBeDisabled();
    expect(screen.getByTitle('Next Page')).not.toBeDisabled();

    rerender(<Pagination page={3} pages={3} total={30} perPage={10} onPageChange={() => {}} />);
    expect(screen.getByTitle('Previous Page')).not.toBeDisabled();
    expect(screen.getByTitle('Next Page')).toBeDisabled();
  });

  it('triggers onPageChange when clicking previous or next buttons', () => {
    const handlePageChange = vi.fn();
    render(
      <Pagination page={2} pages={3} total={30} perPage={10} onPageChange={handlePageChange} />,
    );

    fireEvent.click(screen.getByTitle('Previous Page'));
    expect(handlePageChange).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByTitle('Next Page'));
    expect(handlePageChange).toHaveBeenCalledWith(3);
  });

  it('renders ellipses appropriately for large number of pages', () => {
    render(<Pagination page={5} pages={10} total={100} perPage={10} onPageChange={() => {}} />);

    // Page list: 1, ... (ellipsis-start), 4, 5, 6, ... (ellipsis-end), 10
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();

    // Ensure both ellipses are present (rendered as "...")
    const ellipses = screen.getAllByText('...');
    expect(ellipses.length).toBe(2);
  });
});
