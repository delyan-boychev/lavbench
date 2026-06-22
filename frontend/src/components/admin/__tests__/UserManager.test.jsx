import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../ui/InputField', () => ({
  default: ({ label, value, onChange, type, placeholder, required }) => (
    <div>
      {label && <label>{label}</label>}
      <input
        type={type || 'text'}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
      />
    </div>
  ),
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, type, variant, className, disabled }) => (
    <button type={type} data-variant={variant} className={className} disabled={disabled}>
      {children}
    </button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, required }) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  ),
}));

vi.mock('../../ui/ToggleField', () => ({
  default: ({ label, id, checked, onChange }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input type="checkbox" id={id} checked={checked} onChange={onChange} />
    </div>
  ),
}));

vi.mock('../../ui/Pagination', () => ({
  default: ({ page, pages, total, onPageChange: _onPageChange, itemName: _itemName }) => (
    <div>
      <span data-testid="page-info">
        {page}/{pages}
      </span>
      <span data-testid="total">{total}</span>
    </div>
  ),
}));

import UserManager from '../UserManager';

const baseProps = {
  newUser: {
    username: '',
    email: '',
    password: '',
    name: '',
    surname: '',
    role: 'competitor',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false,
  },
  setNewUser: vi.fn(),
  handleRegisterUser: vi.fn((e) => e.preventDefault()),
  generatedUserCredentials: null,
  allUsers: [],
  userSearch: '',
  setUserSearch: vi.fn(),
  handleDeleteUser: vi.fn(),
  usersPage: 1,
  usersPages: 1,
  usersTotal: 0,
  setUsersPage: vi.fn(),
  challenges: [{ id: 1, title: 'Challenge 1' }],
  currentUser: { id: 1, role: 'admin' },
};

describe('UserManager', () => {
  it('renders register user form', () => {
    render(<UserManager {...baseProps} />);
    expect(screen.getByText('Register User Account')).toBeInTheDocument();
  });

  it('renders the role select field label', () => {
    render(<UserManager {...baseProps} />);
    expect(screen.getByText('Role')).toBeInTheDocument();
  });

  it('shows competitor-specific fields when role is competitor', () => {
    render(<UserManager {...baseProps} />);
    expect(screen.getByText('Grade')).toBeInTheDocument();
    expect(screen.getByText('School')).toBeInTheDocument();
    expect(screen.getByText('City')).toBeInTheDocument();
    expect(
      screen.getByText('Anonymous (Hide name/school/city from other students)'),
    ).toBeInTheDocument();
  });

  it('shows generated user credentials when provided', () => {
    render(
      <UserManager
        {...baseProps}
        generatedUserCredentials={{
          username: 'newadmin',
          password: 'sec123',
          role: 'jury',
          name: 'Jane',
          surname: 'Doe',
        }}
      />,
    );
    expect(screen.getByText('newadmin')).toBeInTheDocument();
    expect(screen.getByText('sec123')).toBeInTheDocument();
  });

  it('shows no users found when list is empty', () => {
    render(<UserManager {...baseProps} />);
    expect(screen.getByText('No users found matching your search.')).toBeInTheDocument();
  });

  it('renders user accounts list table', () => {
    const users = [
      {
        id: 1,
        username: 'admin1',
        name: 'Admin',
        surname: 'One',
        email: 'admin@test.com',
        role: 'admin',
        is_anonymous: false,
      },
      {
        id: 2,
        username: 'jury1',
        name: 'Jury',
        surname: 'One',
        email: 'jury@test.com',
        role: 'jury',
        is_anonymous: false,
      },
    ];
    render(<UserManager {...baseProps} allUsers={users} />);
    expect(screen.getByText('admin1')).toBeInTheDocument();
    expect(screen.getByText('jury1')).toBeInTheDocument();
  });

  it('shows current admin label for own user', () => {
    const users = [
      {
        id: 1,
        username: 'admin1',
        name: 'Admin',
        surname: 'One',
        email: '',
        role: 'admin',
        is_anonymous: false,
      },
    ];
    render(<UserManager {...baseProps} allUsers={users} currentUser={{ id: 1, role: 'admin' }} />);
    expect(screen.getByText('Current Admin')).toBeInTheDocument();
  });

  it('shows delete button for other users', () => {
    const users = [
      {
        id: 2,
        username: 'other',
        name: 'Other',
        surname: 'User',
        email: '',
        role: 'competitor',
        is_anonymous: false,
      },
    ];
    const handleDeleteUser = vi.fn();
    render(<UserManager {...baseProps} allUsers={users} handleDeleteUser={handleDeleteUser} />);
    expect(screen.getByText('Delete')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Delete'));
    expect(handleDeleteUser).toHaveBeenCalledWith(2, 'other');
  });

  it('shows anonymous badge for users with is_anonymous', () => {
    const users = [
      {
        id: 2,
        username: 'anon',
        name: 'Anon',
        surname: 'User',
        email: '',
        role: 'competitor',
        is_anonymous: true,
      },
    ];
    render(<UserManager {...baseProps} allUsers={users} />);
    const anonBadges = screen.getAllByText('Anon');
    expect(anonBadges.length).toBeGreaterThan(0);
  });

  it('renders pagination info for users list', () => {
    const users = Array.from({ length: 5 }, (_, i) => ({
      id: i,
      username: `u${i}`,
      name: '',
      surname: '',
      email: '',
      role: 'competitor',
      is_anonymous: false,
    }));
    render(<UserManager {...baseProps} allUsers={users} usersPages={3} usersTotal={15} />);
    expect(screen.getByTestId('page-info')).toBeInTheDocument();
    expect(screen.getByTestId('total')).toHaveTextContent('15');
  });
});
