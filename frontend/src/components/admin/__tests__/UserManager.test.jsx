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
  default: ({ children, type, variant, className, disabled, onClick }) => (
    <button
      type={type}
      data-variant={variant}
      className={className}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, required, multiple }) => (
    <div>
      <label>{label}</label>
      <select
        value={value}
        onChange={(e) =>
          onChange(multiple ? Array.from(e.target.selectedOptions, (o) => o.value) : e.target.value)
        }
        required={required}
        multiple={multiple}
      >
        {options?.map((o) => (
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

vi.mock('../../../context/AppContext', () => ({
  useApp: () => ({
    showToast: vi.fn(),
    confirm: vi.fn(),
    challenges: [],
    selectedChallenge: null,
    selectedTask: null,
    setSelectedChallengeById: vi.fn(),
    setSelectedTask: vi.fn(),
    fetchChallenges: vi.fn(),
  }),
}));

// ── shared fixtures ──────────────────────────────────────────────────────────

const BASE_NEW_USER = {
  username: 'newguy',
  email: 'new@test.com',
  name: 'New',
  surname: 'Guy',
  role: 'jury',
  grade: '',
  school: '',
  city: '',
  challenge_id: '',
  jury_challenges: [],
  is_anonymous: false,
};

const MOCK_USERS = [
  {
    id: 1,
    username: 'admin',
    name: 'System',
    surname: 'Admin',
    role: 'admin',
    email: 'admin@test.com',
    is_anonymous: false,
  },
  {
    id: 2,
    username: 'jury1',
    name: 'Jury',
    surname: 'Member',
    role: 'jury',
    email: 'jury@test.com',
    is_anonymous: false,
  },
];

const MOCK_CHALLENGES = [
  { id: 10, title: 'Challenge Alpha' },
  { id: 11, title: 'Challenge Beta' },
];

const CURRENT_USER = { id: 1, username: 'admin', role: 'admin' };

function makeHandlers(overrides = {}) {
  return {
    setNewUser: vi.fn(),
    handleRegisterUser: vi.fn((e) => e?.preventDefault?.()),
    handleDeleteUser: vi.fn(),
    setUserSearch: vi.fn(),
    setUsersPage: vi.fn(),
    initEditUser: vi.fn(),
    ...overrides,
  };
}

function renderComponent(propOverrides = {}, handlerOverrides = {}) {
  const handlers = makeHandlers(handlerOverrides);
  const props = {
    newUser: BASE_NEW_USER,
    generatedUserCredentials: null,
    allUsers: MOCK_USERS,
    userSearch: '',
    usersPage: 1,
    usersPages: 1,
    usersTotal: 2,
    challenges: MOCK_CHALLENGES,
    currentUser: CURRENT_USER,
    ...handlers,
    ...propOverrides,
  };
  render(<UserManager {...props} />);
  return handlers;
}

// ── tests ────────────────────────────────────────────────────────────────────

describe('UserManager – rendering', () => {
  it('renders section headings', () => {
    renderComponent();
    expect(screen.getByText('Register User Account')).toBeInTheDocument();
    expect(screen.getByText('System User Accounts')).toBeInTheDocument();
  });

  it('lists all users with username, full name and role badge', () => {
    renderComponent();
    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.getByText('System Admin')).toBeInTheDocument();
    expect(screen.getByText('jury1')).toBeInTheDocument();
    expect(screen.getByText('Jury Member')).toBeInTheDocument();
  });

  it('shows "Current Admin" label instead of actions for the logged-in user', () => {
    renderComponent();
    expect(screen.getByText('Current Admin')).toBeInTheDocument();
  });

  it('shows Edit and Delete buttons only for other users', () => {
    renderComponent();
    expect(screen.getByRole('button', { name: /Edit/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete/i })).toBeInTheDocument();
  });

  it('renders empty-state message when allUsers is empty', () => {
    renderComponent({ allUsers: [] });
    expect(screen.getByText(/no users found/i)).toBeInTheDocument();
  });

  it('renders empty-state message when allUsers is null', () => {
    renderComponent({ allUsers: null });
    expect(screen.getByText(/no users found/i)).toBeInTheDocument();
  });
});

describe('UserManager – anonymous badge', () => {
  it('shows ANON badge for users with is_anonymous=true', () => {
    const usersWithAnon = [{ ...MOCK_USERS[1], is_anonymous: true }];
    renderComponent({ allUsers: usersWithAnon, usersTotal: 1 });
    expect(screen.getByTitle(/anonymity/i)).toBeInTheDocument();
  });

  it('does not show ANON badge for non-anonymous users', () => {
    renderComponent();
    expect(screen.queryByTitle(/anonymity/i)).not.toBeInTheDocument();
  });
});

describe('UserManager – registration form fields', () => {
  it('shows only common fields for jury role', () => {
    renderComponent({ newUser: { ...BASE_NEW_USER, role: 'jury' } });
    expect(screen.queryByText(/grade/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/school/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/birth date/i)).not.toBeInTheDocument();
  });

  it('shows competitor-specific fields when role is competitor', () => {
    renderComponent({ newUser: { ...BASE_NEW_USER, role: 'competitor', birth_date: '' } });
    expect(screen.getByText('Grade')).toBeInTheDocument();
    expect(screen.getByText('School')).toBeInTheDocument();
    expect(screen.getByText('City')).toBeInTheDocument();
    expect(screen.getByText(/birth date/i)).toBeInTheDocument();
  });

  it('renders challenge assignment dropdown for competitors', () => {
    renderComponent({ newUser: { ...BASE_NEW_USER, role: 'competitor', birth_date: '' } });
    expect(screen.getByText('Challenge Alpha')).toBeInTheDocument();
    expect(screen.getByText('Challenge Beta')).toBeInTheDocument();
  });

  it('renders middle name field only for competitor role', () => {
    renderComponent({
      newUser: { ...BASE_NEW_USER, role: 'competitor', birth_date: '', middle_name: '' },
    });
    expect(screen.getByText(/middle name/i)).toBeInTheDocument();
  });
});

describe('UserManager – credential banner', () => {
  it('does not render credential banner when generatedUserCredentials is null', () => {
    renderComponent();
    expect(screen.queryByText(/account created/i)).not.toBeInTheDocument();
  });

  it('renders credential banner with username and password after creation', () => {
    renderComponent({
      generatedUserCredentials: {
        role: 'jury',
        name: 'Jury',
        surname: 'Member',
        username: 'jury_abc',
        password: 'secret123',
      },
    });
    expect(screen.getByText('jury_abc')).toBeInTheDocument();
    expect(screen.getByText('secret123')).toBeInTheDocument();
  });
});

describe('UserManager – actions', () => {
  it('calls handleDeleteUser with correct id and username', () => {
    const { handleDeleteUser } = renderComponent();
    fireEvent.click(screen.getByRole('button', { name: /Delete/i }));
    expect(handleDeleteUser).toHaveBeenCalledWith(2, 'jury1');
    expect(handleDeleteUser).toHaveBeenCalledTimes(1);
  });

  it('opens edit form with user data when Edit is clicked', () => {
    renderComponent();
    fireEvent.click(screen.getByRole('button', { name: /Edit/i }));
    expect(screen.getByText(/Edit User/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue('jury1')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Jury')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Member')).toBeInTheDocument();
  });

  it('submits the registration form', () => {
    const { handleRegisterUser } = renderComponent();
    fireEvent.click(screen.getByRole('button', { name: /Register User/i }));
    expect(handleRegisterUser).toHaveBeenCalledTimes(1);
  });

  it('calls setUserSearch when typing in the search box', () => {
    const { setUserSearch } = renderComponent();
    const searchInput = screen.getByPlaceholderText(/search/i);
    fireEvent.change(searchInput, { target: { value: 'jury' } });
    expect(setUserSearch).toHaveBeenCalled();
  });
});

describe('UserManager – setNewUser callbacks', () => {
  it('calls setNewUser when email field changes', () => {
    const { setNewUser } = renderComponent();
    fireEvent.change(screen.getByDisplayValue('new@test.com'), {
      target: { value: 'changed@test.com' },
    });
    expect(setNewUser).toHaveBeenCalledWith(expect.objectContaining({ email: 'changed@test.com' }));
  });

  it('calls setNewUser when first name field changes', () => {
    const { setNewUser } = renderComponent();
    fireEvent.change(screen.getByDisplayValue('New'), {
      target: { value: 'Alice' },
    });
    expect(setNewUser).toHaveBeenCalledWith(expect.objectContaining({ name: 'Alice' }));
  });

  it('calls setNewUser when last name field changes', () => {
    const { setNewUser } = renderComponent();
    fireEvent.change(screen.getByDisplayValue('Guy'), {
      target: { value: 'Smith' },
    });
    expect(setNewUser).toHaveBeenCalledWith(expect.objectContaining({ surname: 'Smith' }));
  });

  it('calls setNewUser when anonymous toggle changes for competitors', () => {
    const { setNewUser } = renderComponent({
      newUser: { ...BASE_NEW_USER, role: 'competitor', birth_date: '' },
    });
    const toggle = screen.getByRole('checkbox');
    fireEvent.click(toggle);
    expect(setNewUser).toHaveBeenCalledWith(
      expect.objectContaining({ is_anonymous: expect.any(Boolean) }),
    );
  });
});
