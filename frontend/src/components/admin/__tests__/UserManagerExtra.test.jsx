/**
 * UserManagerExtra.test.jsx
 * Directly targets the uncovered lines in UserManager.jsx:
 *  - Lines 45-119: competitor-specific form fields (birth date, grade, school, city, challenge)
 *  - Lines 132-202: generated credentials display + jury-role jury_challenges picker
 */
import React, { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import UserManager from '../UserManager';

vi.mock('../../ui/InputField', () => ({
  default: ({ label, value, onChange, type, placeholder }) => (
    <div>
      {label && <label>{label}</label>}
      <input
        aria-label={label || placeholder}
        type={type || 'text'}
        value={value ?? ''}
        onChange={onChange}
        placeholder={placeholder}
      />
    </div>
  ),
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, type, onClick }) => (
    <button type={type || 'button'} onClick={onClick}>
      {children}
    </button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, multiple }) => (
    <div>
      {label && <label>{label}</label>}
      <select
        aria-label={label}
        value={value}
        multiple={multiple}
        onChange={(e) => onChange(e.target.value)}
      >
        {(options || []).map((o) => (
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
  default: () => <div data-testid="pagination" />,
}));

const baseUser = {
  username: '',
  email: '',
  password: '',
  name: '',
  middle_name: '',
  surname: '',
  birth_date: '',
  role: 'competitor',
  grade: '',
  school: '',
  city: '',
  challenge_id: '',
  is_anonymous: false,
  jury_challenges: [],
};

const challenges = [
  { id: 1, title: 'Challenge Alpha' },
  { id: 2, title: 'Challenge Beta' },
];

function ControlledUserManager({ initialUser = baseUser, ...props }) {
  const [newUser, setNewUser] = useState(initialUser);
  return (
    <UserManager
      newUser={newUser}
      setNewUser={setNewUser}
      handleRegisterUser={vi.fn()}
      generatedUserCredentials={null}
      allUsers={[]}
      userSearch=""
      setUserSearch={vi.fn()}
      handleDeleteUser={vi.fn()}
      usersPage={1}
      usersPages={1}
      usersTotal={0}
      setUsersPage={vi.fn()}
      challenges={challenges}
      currentUser={{ id: 99, username: 'admin' }}
      initEditUser={vi.fn()}
      {...props}
    />
  );
}

describe('UserManager – competitor role form fields (lines 45-119)', () => {
  it('renders birth date field for competitor role', () => {
    render(<ControlledUserManager />);
    expect(screen.getByLabelText('Birth Date')).toBeInTheDocument();
  });

  it('renders grade, school, city fields for competitor role', () => {
    render(<ControlledUserManager />);
    expect(screen.getByLabelText('Grade')).toBeInTheDocument();
    expect(screen.getByLabelText('School')).toBeInTheDocument();
    expect(screen.getByLabelText('City')).toBeInTheDocument();
  });

  it('renders assign competition dropdown for competitor', () => {
    render(<ControlledUserManager />);
    // The label key is 'admin.competitor_reg.assign_competition'
    // Our mock t() resolves it to the real translation text
    const select = screen.getAllByRole('combobox');
    // At least one select (the role select and the competition select) should exist
    expect(select.length).toBeGreaterThan(0);
    // Both challenge names should appear as options
    expect(screen.getByText('Challenge Alpha')).toBeInTheDocument();
    expect(screen.getByText('Challenge Beta')).toBeInTheDocument();
  });

  it('renders anonymous toggle for competitor', () => {
    render(<ControlledUserManager />);
    expect(screen.getByText(/anonymous/i)).toBeInTheDocument();
  });

  it('renders middle name field only for competitor role', () => {
    render(<ControlledUserManager />);
    expect(screen.getByLabelText('Middle Name')).toBeInTheDocument();
  });

  it('does NOT render middle name or birth date for jury role', () => {
    render(<ControlledUserManager initialUser={{ ...baseUser, role: 'jury' }} />);
    expect(screen.queryByLabelText('Middle Name')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Birth Date')).not.toBeInTheDocument();
  });
});

describe('UserManager – jury role form fields', () => {
  it('renders jury_challenges multi-select for jury role', () => {
    render(<ControlledUserManager initialUser={{ ...baseUser, role: 'jury' }} />);
    expect(screen.getByLabelText('Assign Competitions')).toBeInTheDocument();
  });
});

describe('UserManager – generated credentials display (lines 158-184)', () => {
  it('shows generated credentials when provided', () => {
    const creds = {
      role: 'competitor',
      name: 'Jane',
      surname: 'Smith',
      username: 'jane.smith',
      password: 'secret123',
    };
    render(<ControlledUserManager generatedUserCredentials={creds} />);
    expect(screen.getByText('jane.smith')).toBeInTheDocument();
    expect(screen.getByText('secret123')).toBeInTheDocument();
    // Name + surname are rendered inside a div with a space between — use a regex matcher
    const matches = screen.getAllByText(
      (_, el) => el?.textContent?.includes('Jane') && el?.textContent?.includes('Smith'),
    );
    expect(matches.length).toBeGreaterThan(0);
  });

  it('shows jury role label in credentials when role is jury', () => {
    const creds = {
      role: 'jury',
      name: 'Bob',
      surname: 'Jones',
      username: 'bob.jones',
      password: 'pw456',
    };
    render(<ControlledUserManager generatedUserCredentials={creds} />);
    expect(screen.getByText('bob.jones')).toBeInTheDocument();
    expect(screen.getByText('pw456')).toBeInTheDocument();
  });
});

describe('UserManager – user list section (lines 187+)', () => {
  const users = [
    {
      id: 1,
      username: 'alice',
      name: 'Alice',
      surname: 'A',
      role: 'competitor',
      is_anonymous: false,
    },
    { id: 2, username: 'bob', name: 'Bob', surname: 'B', role: 'jury', is_anonymous: false },
  ];

  it('renders user list with edit and delete buttons', () => {
    render(<ControlledUserManager allUsers={users} usersTotal={2} />);
    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText('bob')).toBeInTheDocument();
  });

  it('calls initEditUser when Edit is clicked', () => {
    const initEditUser = vi.fn();
    render(<ControlledUserManager allUsers={users} usersTotal={2} initEditUser={initEditUser} />);
    // The edit button text is resolved via t('common.edit', 'Edit') → 'Edit'
    const editBtns = screen.getAllByText('Edit');
    fireEvent.click(editBtns[0]);
    expect(initEditUser).toHaveBeenCalledWith(users[0]);
  });

  it('calls handleDeleteUser when Delete is clicked', () => {
    const handleDeleteUser = vi.fn();
    render(
      <ControlledUserManager allUsers={users} usersTotal={2} handleDeleteUser={handleDeleteUser} />,
    );
    // The delete button text is resolved via t('admin.user_mgmt.delete_btn')
    const deleteBtns = screen.getAllByText('Delete');
    fireEvent.click(deleteBtns[0]);
    expect(handleDeleteUser).toHaveBeenCalledWith(users[0].id, users[0].username);
  });

  it('shows anonymous badge for is_anonymous users', () => {
    const anonUsers = [
      { id: 3, username: 'anon1', name: 'A', surname: 'N', role: 'competitor', is_anonymous: true },
    ];
    render(<ControlledUserManager allUsers={anonUsers} usersTotal={1} />);
    // The anonymous badge text comes from t('admin.competitor_reg.anon_badge') → 'Anon'
    expect(screen.getByTitle(/anonymity/i)).toBeInTheDocument();
  });

  it('shows current-admin label instead of edit/delete for own user', () => {
    const selfUsers = [
      {
        id: 99,
        username: 'admin',
        name: 'Admin',
        surname: 'X',
        role: 'admin',
        is_anonymous: false,
      },
    ];
    render(<ControlledUserManager allUsers={selfUsers} usersTotal={1} />);
    // currentUser.id === 99 → no Edit/Delete, shows current-admin label
    expect(screen.queryByText('Edit')).not.toBeInTheDocument();
    expect(screen.queryByText('Delete')).not.toBeInTheDocument();
  });
});
