import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import UserManager from './UserManager';

describe('UserManager Component', () => {
  const mockNewUser = {
    username: 'newguy',
    email: 'new@test.com',
    name: 'New',
    surname: 'Guy',
    role: 'jury',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false,
  };

  const mockUsers = [
    {
      id: 1,
      username: 'admin',
      name: 'System',
      surname: 'Admin',
      role: 'admin',
      email: 'admin@test.com',
    },
    {
      id: 2,
      username: 'jury1',
      name: 'Jury',
      surname: 'Member',
      role: 'jury',
      email: 'jury@test.com',
    },
  ];

  const mockCurrentUser = { id: 1, username: 'admin', role: 'admin' };
  const mockChallenges = [];

  it('renders user account list and registration forms', () => {
    const handleRegisterUser = vi.fn();
    const setNewUser = vi.fn();
    const setUserSearch = vi.fn();
    const handleDeleteUser = vi.fn();
    const setUsersPage = vi.fn();

    render(
      <UserManager
        newUser={mockNewUser}
        setNewUser={setNewUser}
        handleRegisterUser={handleRegisterUser}
        generatedUserCredentials={null}
        allUsers={mockUsers}
        userSearch=""
        setUserSearch={setUserSearch}
        handleDeleteUser={handleDeleteUser}
        usersPage={1}
        usersPages={1}
        usersTotal={2}
        setUsersPage={setUsersPage}
        challenges={mockChallenges}
        currentUser={mockCurrentUser}
      />,
    );

    // Form headers
    expect(screen.getByText('Register User Account')).toBeInTheDocument();
    expect(screen.getByText('System User Accounts')).toBeInTheDocument();

    // Listed users
    expect(screen.getByText('jury1')).toBeInTheDocument();
    expect(screen.getByText('Jury Member')).toBeInTheDocument();
    expect(screen.getByText('admin')).toBeInTheDocument();

    // Actions
    expect(screen.getByText('Current Admin')).toBeInTheDocument();
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('triggers delete action when delete button is clicked', () => {
    const handleRegisterUser = vi.fn();
    const setNewUser = vi.fn();
    const setUserSearch = vi.fn();
    const handleDeleteUser = vi.fn();
    const setUsersPage = vi.fn();

    render(
      <UserManager
        newUser={mockNewUser}
        setNewUser={setNewUser}
        handleRegisterUser={handleRegisterUser}
        generatedUserCredentials={null}
        allUsers={mockUsers}
        userSearch=""
        setUserSearch={setUserSearch}
        handleDeleteUser={handleDeleteUser}
        usersPage={1}
        usersPages={1}
        usersTotal={2}
        setUsersPage={setUsersPage}
        challenges={mockChallenges}
        currentUser={mockCurrentUser}
      />,
    );

    const deleteBtn = screen.getByRole('button', { name: /Delete/i });
    fireEvent.click(deleteBtn);

    expect(handleDeleteUser).toHaveBeenCalledWith(2, 'jury1');
  });

  it('submits registration form', () => {
    const handleRegisterUser = vi.fn((e) => e.preventDefault());
    const setNewUser = vi.fn();
    const setUserSearch = vi.fn();
    const handleDeleteUser = vi.fn();
    const setUsersPage = vi.fn();

    render(
      <UserManager
        newUser={mockNewUser}
        setNewUser={setNewUser}
        handleRegisterUser={handleRegisterUser}
        generatedUserCredentials={null}
        allUsers={mockUsers}
        userSearch=""
        setUserSearch={setUserSearch}
        handleDeleteUser={handleDeleteUser}
        usersPage={1}
        usersPages={1}
        usersTotal={2}
        setUsersPage={setUsersPage}
        challenges={mockChallenges}
        currentUser={mockCurrentUser}
      />,
    );

    const submitBtn = screen.getByRole('button', { name: /Register User/i });
    fireEvent.click(submitBtn);

    expect(handleRegisterUser).toHaveBeenCalledTimes(1);
  });
});
