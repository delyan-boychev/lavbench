import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CredentialsBox from '../CredentialsBox';

const props = {
  title: 'Login details',
  usernameLabel: 'Username:',
  username: 'ivan01',
  passwordLabel: 'Password:',
  password: 's3cret',
};

describe('CredentialsBox', () => {
  beforeEach(() => vi.mocked(window.scrollTo).mockClear());

  it('shows the title, username and password as a status', () => {
    render(<CredentialsBox {...props} />);
    const box = screen.getByRole('status');
    expect(box).toHaveTextContent('Login details');
    expect(screen.getByText('ivan01')).toBeInTheDocument();
    expect(screen.getByText('s3cret')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('shows the person and help text when given', () => {
    render(
      <CredentialsBox
        {...props}
        personLabel="Competitor:"
        person="Ivan Petrov"
        help="Hand these over now."
      />,
    );
    expect(screen.getByText('Competitor:')).toBeInTheDocument();
    expect(screen.getByText(/Ivan Petrov/)).toBeInTheDocument();
    expect(screen.getByText('Hand these over now.')).toBeInTheDocument();
  });

  it('offers a clear button only with onClear', () => {
    const onClear = vi.fn();
    render(<CredentialsBox {...props} onClear={onClear} clearLabel="Clear" />);
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('scrolls into view when it appears off screen', () => {
    const spy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(/** @type {DOMRect} */ ({ top: 3000, bottom: 3200 }));
    try {
      render(<CredentialsBox {...props} />);
      expect(window.scrollTo).toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });
});
