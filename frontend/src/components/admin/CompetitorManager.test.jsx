import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CompetitorManager from './CompetitorManager';

describe('CompetitorManager Component', () => {
  const mockNewCompetitor = {
    username: 'comp1',
    email: 'comp1@test.com',
    name: 'Alice',
    surname: 'Smith',
    grade: '10',
    school: 'Math School',
    city: 'Sofia',
    challenge_id: '1',
    is_anonymous: false
  };

  const mockCompetitorsList = [
    {
      id: 10,
      username: 'comp1',
      name: 'Alice',
      surname: 'Smith',
      role: 'competitor',
      email: 'alice@test.com',
      is_anonymous: false,
      grade: '10',
      school: 'Math School',
      city: 'Sofia',
      challenge_id: 1
    }
  ];

  const mockChallenges = [{ id: 1, title: 'AI Competition' }];
  const mockCurrentUser = { id: 1, username: 'admin', role: 'admin' };
  const mockIsChallengeStarted = vi.fn().mockReturnValue(false);

  it('renders registration form and competitor table', () => {
    const setEditingUser = vi.fn();
    const setEditUserForm = vi.fn();
    const handleUpdateUserSubmit = vi.fn();
    const setNewCompetitor = vi.fn();
    const handleRegisterCompetitor = vi.fn();
    const setCsvChallengeId = vi.fn();
    const setCsvFile = vi.fn();
    const handleCSVImport = vi.fn();
    const setResetCredentials = vi.fn();
    const setBulkResetCredentials = vi.fn();
    const setCompetitorSearch = vi.fn();
    const handleBulkResetPasswords = vi.fn();
    const initEditUser = vi.fn();
    const handleResetUserPassword = vi.fn();
    const setCompetitorsPage = vi.fn();

    render(
      <CompetitorManager
        editingUser={null}
        setEditingUser={setEditingUser}
        editUserForm={{}}
        setEditUserForm={setEditUserForm}
        handleUpdateUserSubmit={handleUpdateUserSubmit}
        challenges={mockChallenges}
        isEditDisabled={false}
        newCompetitor={mockNewCompetitor}
        setNewCompetitor={setNewCompetitor}
        handleRegisterCompetitor={handleRegisterCompetitor}
        isManualRegisterDisabled={false}
        generatedCredentials={null}
        csvChallengeId=""
        setCsvChallengeId={setCsvChallengeId}
        setCsvFile={setCsvFile}
        csvImporting={false}
        isCSVImportDisabled={false}
        handleCSVImport={handleCSVImport}
        importedCompetitors={[]}
        resetCredentials={null}
        setResetCredentials={setResetCredentials}
        bulkResetCredentials={[]}
        setBulkResetCredentials={setBulkResetCredentials}
        competitorsList={mockCompetitorsList}
        competitorSearch=""
        setCompetitorSearch={setCompetitorSearch}
        handleBulkResetPasswords={handleBulkResetPasswords}
        currentUser={mockCurrentUser}
        selectedChallenge={mockChallenges[0]}
        isChallengeStarted={mockIsChallengeStarted}
        initEditUser={initEditUser}
        handleResetUserPassword={handleResetUserPassword}
        competitorsPage={1}
        competitorsPages={1}
        competitorsTotal={1}
        setCompetitorsPage={setCompetitorsPage}
      />
    );

    // Form/Workspace headers
    expect(screen.getByText('Manual Competitor Registration')).toBeInTheDocument();
    expect(screen.getByText('Import Competitors CSV')).toBeInTheDocument();
    expect(screen.getByText('Registered Competitors')).toBeInTheDocument();

    // Table rows
    expect(screen.getByText('comp1')).toBeInTheDocument();
    expect(screen.getByText('Alice Smith')).toBeInTheDocument();
    expect(screen.getByText('Math School (10 grade)')).toBeInTheDocument();
    expect(screen.getByText('Sofia')).toBeInTheDocument();
  });

  it('triggers competitor manual registration form submit', () => {
    const setEditingUser = vi.fn();
    const setEditUserForm = vi.fn();
    const handleUpdateUserSubmit = vi.fn();
    const setNewCompetitor = vi.fn();
    const handleRegisterCompetitor = vi.fn((e) => e.preventDefault());
    const setCsvChallengeId = vi.fn();
    const setCsvFile = vi.fn();
    const handleCSVImport = vi.fn();
    const setResetCredentials = vi.fn();
    const setBulkResetCredentials = vi.fn();
    const setCompetitorSearch = vi.fn();
    const handleBulkResetPasswords = vi.fn();
    const initEditUser = vi.fn();
    const handleResetUserPassword = vi.fn();
    const setCompetitorsPage = vi.fn();

    render(
      <CompetitorManager
        editingUser={null}
        setEditingUser={setEditingUser}
        editUserForm={{}}
        setEditUserForm={setEditUserForm}
        handleUpdateUserSubmit={handleUpdateUserSubmit}
        challenges={mockChallenges}
        isEditDisabled={false}
        newCompetitor={mockNewCompetitor}
        setNewCompetitor={setNewCompetitor}
        handleRegisterCompetitor={handleRegisterCompetitor}
        isManualRegisterDisabled={false}
        generatedCredentials={null}
        csvChallengeId=""
        setCsvChallengeId={setCsvChallengeId}
        setCsvFile={setCsvFile}
        csvImporting={false}
        isCSVImportDisabled={false}
        handleCSVImport={handleCSVImport}
        importedCompetitors={[]}
        resetCredentials={null}
        setResetCredentials={setResetCredentials}
        bulkResetCredentials={[]}
        setBulkResetCredentials={setBulkResetCredentials}
        competitorsList={mockCompetitorsList}
        competitorSearch=""
        setCompetitorSearch={setCompetitorSearch}
        handleBulkResetPasswords={handleBulkResetPasswords}
        currentUser={mockCurrentUser}
        selectedChallenge={mockChallenges[0]}
        isChallengeStarted={mockIsChallengeStarted}
        initEditUser={initEditUser}
        handleResetUserPassword={handleResetUserPassword}
        competitorsPage={1}
        competitorsPages={1}
        competitorsTotal={1}
        setCompetitorsPage={setCompetitorsPage}
      />
    );

    const registerBtn = screen.getByRole('button', { name: /Generate Credentials/i });
    fireEvent.click(registerBtn);

    expect(handleRegisterCompetitor).toHaveBeenCalledTimes(1);
  });
});
