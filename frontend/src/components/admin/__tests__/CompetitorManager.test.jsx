import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../ui/InputField', () => ({
  default: ({ label, value, onChange, type, placeholder, required, className }) => (
    <div data-testid="input-field">
      {label && <label>{label}</label>}
      <input
        data-testid="input"
        type={type || 'text'}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        className={className}
      />
    </div>
  ),
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, type, variant, className, disabled, size }) => (
    <button
      type={type}
      data-variant={variant}
      data-size={size}
      className={className}
      disabled={disabled}
    >
      {children}
    </button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, required }) => (
    <div data-testid="select-field">
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
    <div data-testid="toggle-field">
      <label htmlFor={id}>{label}</label>
      <input type="checkbox" id={id} checked={checked} onChange={onChange} />
    </div>
  ),
}));

vi.mock('../../ui/Pagination', () => ({
  default: ({ page, pages, total, onPageChange, itemName: _itemName }) => (
    <div data-testid="pagination">
      <span data-testid="page-info">
        {page}/{pages}
      </span>
      <span data-testid="total">{total}</span>
      <button onClick={() => onPageChange(page + 1)}>Next</button>
    </div>
  ),
}));

vi.mock('../../ui/FileUploader', () => ({
  default: ({ files: _files, onChange, accept, label, required }) => (
    <div data-testid="file-uploader">
      <span>{label}</span>
      <input
        type="file"
        accept={accept}
        onChange={(e) => onChange(e.target.files)}
        required={required}
      />
    </div>
  ),
}));

import CompetitorManager from '../CompetitorManager';

const baseProps = {
  editingUser: null,
  setEditingUser: vi.fn(),
  editUserForm: {
    name: '',
    middle_name: '',
    surname: '',
    birth_date: '',
    grade: '',
    school: '',
    city: '',
    username: '',
    email: '',
    challenge_id: '',
    is_anonymous: false,
  },
  setEditUserForm: vi.fn(),
  handleUpdateUserSubmit: vi.fn((e) => e.preventDefault()),
  challenges: [{ id: 1, title: 'Challenge 1' }],
  isEditDisabled: false,
  newCompetitor: {
    name: '',
    middle_name: '',
    surname: '',
    birth_date: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false,
  },
  setNewCompetitor: vi.fn(),
  handleRegisterCompetitor: vi.fn((e) => e.preventDefault()),
  isManualRegisterDisabled: false,
  generatedCredentials: null,
  csvChallengeId: '',
  setCsvChallengeId: vi.fn(),
  csvFile: null,
  setCsvFile: vi.fn(),
  csvImporting: false,
  isCSVImportDisabled: false,
  handleCSVImport: vi.fn((e) => e.preventDefault()),
  importedCompetitors: [],
  resetCredentials: null,
  setResetCredentials: vi.fn(),
  bulkResetCredentials: [],
  setBulkResetCredentials: vi.fn(),
  competitorsList: [],
  competitorSearch: '',
  setCompetitorSearch: vi.fn(),
  handleBulkResetPasswords: vi.fn(),
  currentUser: { role: 'admin' },
  selectedChallenge: null,
  isChallengeStarted: vi.fn(() => false),
  initEditUser: vi.fn(),
  handleResetUserPassword: vi.fn(),
  competitorsPage: 1,
  competitorsPages: 1,
  competitorsTotal: 0,
  setCompetitorsPage: vi.fn(),
};

describe('CompetitorManager', () => {
  it('renders manual registration form by default', () => {
    render(<CompetitorManager {...baseProps} />);
    expect(screen.getByText('Manual Competitor Registration')).toBeInTheDocument();
  });

  it('renders CSV import form', () => {
    render(<CompetitorManager {...baseProps} />);
    expect(screen.getByText('Import Competitors CSV')).toBeInTheDocument();
  });

  it('shows manual form even when editingUser is set', () => {
    render(<CompetitorManager {...baseProps} editingUser={{ id: 1, username: 'testuser' }} />);
    expect(screen.getByText('Manual Competitor Registration')).toBeInTheDocument();
  });

  it('shows generated credentials when provided', () => {
    render(
      <CompetitorManager
        {...baseProps}
        generatedCredentials={{
          username: 'newuser',
          password: 'pass123',
          name: 'John',
          surname: 'Doe',
        }}
      />,
    );
    expect(screen.getByText('newuser')).toBeInTheDocument();
    expect(screen.getByText('pass123')).toBeInTheDocument();
  });

  it('does not show imported competitors in the document (privacy constraint) but shows download button', () => {
    const imported = [
      {
        name: 'Alice',
        middle_name: 'Marie',
        surname: 'Smith',
        birth_date: '2010-05-15',
        generated_username: 'alice_s',
        generated_password: 'p1',
      },
    ];
    render(<CompetitorManager {...baseProps} importedCompetitors={imported} />);
    expect(screen.queryByText(/Alice/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Smith/)).not.toBeInTheDocument();
    expect(screen.queryByText('alice_s')).not.toBeInTheDocument();
    expect(screen.getByText('Download Credentials (CSV)')).toBeInTheDocument();
  });

  it('shows registered competitors table when list is non-empty', () => {
    const competitors = [
      {
        id: 1,
        alias_id: 'A001',
        name: 'Bob',
        surname: 'Jones',
        school: 'High School',
        grade: '10',
        city: 'NY',
        username: 'bobj',
        is_anonymous: false,
        challenge_id: 1,
      },
    ];
    render(<CompetitorManager {...baseProps} competitorsList={competitors} />);
    expect(screen.getByText('A001')).toBeInTheDocument();
    expect(screen.getByText(/Bob/)).toBeInTheDocument();
    expect(screen.getByText('bobj')).toBeInTheDocument();
  });

  it('shows empty state when no competitors found', () => {
    render(<CompetitorManager {...baseProps} />);
    expect(screen.getByText('No competitors found matching your search.')).toBeInTheDocument();
  });

  it('shows competition started warning when manual register is disabled', () => {
    render(<CompetitorManager {...baseProps} isManualRegisterDisabled={true} />);
    expect(
      screen.getByText('This competition has started. Jury members cannot modify competitors.'),
    ).toBeInTheDocument();
  });

  it('shows competition started warning when CSV import is disabled', () => {
    render(<CompetitorManager {...baseProps} isCSVImportDisabled={true} />);
    expect(
      screen.getByText('This competition has started. Jury members cannot import competitors.'),
    ).toBeInTheDocument();
  });

  it('shows password reset credentials when provided', () => {
    render(
      <CompetitorManager
        {...baseProps}
        resetCredentials={{ username: 'reset_user', password: 'new_pass' }}
      />,
    );
    expect(screen.getByText('reset_user')).toBeInTheDocument();
    expect(screen.getByText('new_pass')).toBeInTheDocument();
  });

  it('does not show bulk reset credentials in the document (privacy constraint) but shows download button', () => {
    const bulk = [
      {
        name: 'User1',
        middle_name: 'Jane',
        surname: 'Test',
        birth_date: '2010-05-15',
        username: 'u1',
        password: 'p1',
      },
    ];
    render(<CompetitorManager {...baseProps} bulkResetCredentials={bulk} />);
    expect(screen.queryByText(/User1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Test/)).not.toBeInTheDocument();
    expect(screen.getByText('Download Credentials (CSV)')).toBeInTheDocument();
  });

  it('renders pagination info for competitors list', () => {
    const competitors = Array.from({ length: 10 }, (_, i) => ({
      id: i,
      alias_id: `A${i}`,
      name: `User${i}`,
      surname: '',
      school: '',
      grade: '',
      city: '',
      username: '',
      is_anonymous: false,
      challenge_id: 1,
    }));
    render(
      <CompetitorManager
        {...baseProps}
        competitorsList={competitors}
        competitorsPages={3}
        competitorsTotal={25}
      />,
    );
    expect(screen.getByText('1/3')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
  });

  it('renders reset all passwords button for admin', () => {
    render(<CompetitorManager {...baseProps} />);
    expect(screen.getByText('Reset All Passwords in Challenge')).toBeInTheDocument();
  });

  it('hides reset all passwords button for jury when challenge started', () => {
    render(
      <CompetitorManager
        {...baseProps}
        currentUser={{ role: 'jury' }}
        isChallengeStarted={() => true}
      />,
    );
    expect(screen.queryByText('Reset All Passwords in Challenge')).not.toBeInTheDocument();
  });

  it('shows edit and reset password buttons for each competitor', () => {
    const competitors = [
      {
        id: 1,
        alias_id: 'A001',
        name: 'Bob',
        surname: 'Jones',
        school: '',
        grade: '',
        city: '',
        username: 'bobj',
        is_anonymous: false,
        challenge_id: 1,
      },
    ];
    render(<CompetitorManager {...baseProps} competitorsList={competitors} />);
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(screen.getByText('Reset PW')).toBeInTheDocument();
  });

  it('calls handleRegisterCompetitor on form submit', () => {
    const handleRegisterCompetitor = vi.fn((e) => e.preventDefault());
    render(
      <CompetitorManager {...baseProps} handleRegisterCompetitor={handleRegisterCompetitor} />,
    );
    const forms = screen.getAllByText('Generate Credentials').map((el) => el.closest('form'));
    fireEvent.submit(forms[0]);
    expect(handleRegisterCompetitor).toHaveBeenCalled();
  });

  it('calls handleCSVImport on CSV form submit', () => {
    const handleCSVImport = vi.fn((e) => e.preventDefault());
    render(<CompetitorManager {...baseProps} handleCSVImport={handleCSVImport} />);
    const forms = screen.getAllByText('Upload & Parse CSV').map((el) => el.closest('form'));
    fireEvent.submit(forms[0]);
    expect(handleCSVImport).toHaveBeenCalled();
  });
});
