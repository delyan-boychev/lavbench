import React from 'react';
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NotificationsProvider } from '../../../context/NotificationsContext';

// The editor asks before discarding changes through the notifications confirm
const render = (ui) => rtlRender(ui, { wrapper: NotificationsProvider });
const mockUpdateUser = vi.fn();

// The edit form saves through useUpdateUser inside useUserEditor
vi.mock('../../../hooks/useUserMutations', () => ({
  useUpdateUser: () => ({ mutateAsync: mockUpdateUser, isPending: false }),
}));

vi.mock('../../ui/InputField', () => ({
  default: ({
    label,
    value,
    onChange,
    type,
    placeholder,
    required,
    className,
    disabled,
    error,
  }) => (
    <div data-testid="input-field">
      {label && <label>{label}</label>}
      <input
        data-testid="input"
        aria-label={label || undefined}
        type={type || 'text'}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        className={className}
        disabled={disabled}
      />
      {error && <p>{error}</p>}
    </div>
  ),
}));

vi.mock('../../ui/Button', () => ({
  default: ({ children, type, variant, className, disabled, size, onClick }) => (
    <button
      type={type || 'button'}
      data-variant={variant}
      data-size={size}
      className={className}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  ),
}));

vi.mock('../../ui/SelectField', () => ({
  default: ({ label, value, onChange, options, required, error }) => (
    <div data-testid="select-field">
      <label>{label}</label>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <p>{error}</p>}
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
  default: ({ files: _files, onChange, accept, label, required, error }) => (
    <div data-testid="file-uploader">
      <span>{label}</span>
      <input
        type="file"
        accept={accept}
        onChange={(e) => onChange(e.target.files)}
        required={required}
      />
      {error && <p>{error}</p>}
    </div>
  ),
}));

import CompetitorManager from '../CompetitorManager';

const ALICE = {
  id: 10,
  alias_id: 'A001',
  name: 'Alice',
  middle_name: 'Marie',
  surname: 'Smith',
  birth_date: '2010-05-15',
  role: 'competitor',
  username: 'alice123',
  is_anonymous: false,
  grade: '10',
  school: 'Math School',
  city: 'Sofia',
  challenge_id: 1,
  can_reset_password: true,
};

const baseProps = {
  challenges: [{ id: 1, title: 'Challenge 1' }],
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
  bulkResetMessage: '',
  setBulkResetMessage: vi.fn(),
  competitorsList: [],
  competitorSearch: '',
  setCompetitorSearch: vi.fn(),
  handleBulkResetPasswords: vi.fn(),
  currentUser: { role: 'admin' },
  selectedChallenge: null,
  isChallengeStarted: vi.fn(() => false),
  handleResetUserPassword: vi.fn(),
  competitorsPage: 1,
  competitorsPages: 1,
  competitorsTotal: 0,
  setCompetitorsPage: vi.fn(),
};

describe('CompetitorManager', () => {
  beforeEach(() => {
    mockUpdateUser.mockReset();
  });

  it('renders manual registration form by default', () => {
    render(<CompetitorManager {...baseProps} />);
    expect(screen.getByText('Manual Competitor Registration')).toBeInTheDocument();
  });

  it('renders CSV import form', () => {
    render(<CompetitorManager {...baseProps} />);
    expect(screen.getByText('Import Competitors CSV')).toBeInTheDocument();
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

  it('shows bulk reset success banner without exposing credentials', () => {
    const message = 'Passwords were reset for 1 competitor.';
    render(<CompetitorManager {...baseProps} bulkResetMessage={message} />);
    expect(screen.getByText('Passwords Reset Successfully')).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.queryByText(/User1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Test/)).not.toBeInTheDocument();
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
        can_reset_password: true,
      },
    ];
    render(<CompetitorManager {...baseProps} competitorsList={competitors} />);
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(screen.getByText('Reset PW')).toBeInTheDocument();
  });

  it('offers a password reset only where the API allows it', () => {
    render(
      <CompetitorManager
        {...baseProps}
        currentUser={{ role: 'jury' }}
        competitorsList={[
          { ...ALICE, id: 10, alias_id: 'A-OK', can_reset_password: true },
          { ...ALICE, id: 11, alias_id: 'A-NO', can_reset_password: false },
          { ...ALICE, id: 12, alias_id: 'A-UNSET', can_reset_password: undefined },
        ]}
      />,
    );
    const resetButtons = screen.getAllByText('Reset PW');
    expect(resetButtons).toHaveLength(1);
    expect(resetButtons[0].closest('tr')).toHaveTextContent('A-OK');
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

  it('shows register and CSV errors under their fields', () => {
    render(
      <CompetitorManager
        {...baseProps}
        registerErrors={{ challenge_id: 'Select target competition.', school: 'Too long' }}
        csvErrors={{ file: 'Please select a CSV file.' }}
      />,
    );
    expect(screen.getByLabelText('Assign Competition').parentElement).toHaveTextContent(
      'Select target competition.',
    );
    expect(screen.getByLabelText('School').parentElement).toHaveTextContent('Too long');
    expect(screen.getByTestId('file-uploader')).toHaveTextContent('Please select a CSV file.');
  });

  it('allows downloading imported CSV credentials', () => {
    const mockImported = [{ id: '1', name: 'Test', generated_password: 'pwd' }];
    const mockCreateObjectURL = vi.fn().mockReturnValue('blob:mock-url');
    window.URL.createObjectURL = mockCreateObjectURL;
    const clickSpy = vi
      .spyOn(window.HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    render(<CompetitorManager {...baseProps} importedCompetitors={mockImported} />);
    const downloadBtn = screen.getByText('Download Credentials (CSV)');
    fireEvent.click(downloadBtn);

    expect(mockCreateObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);

    clickSpy.mockRestore();
  });

  it('neutralizes spreadsheet formulas in imported credentials', async () => {
    const createObjectURL = vi.fn().mockReturnValue('blob:mock-url');
    window.URL.createObjectURL = createObjectURL;
    const clickSpy = vi
      .spyOn(window.HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    render(
      <CompetitorManager
        {...baseProps}
        importedCompetitors={[
          {
            id: '1',
            name: '=HYPERLINK("evil")',
            generated_username: ' +SUM(1,1)',
            generated_password: '@cmd',
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByText('Download Credentials (CSV)'));

    const csv = await createObjectURL.mock.calls[0][0].text();
    expect(csv).toContain('"\'=HYPERLINK(""evil"")"');
    expect(csv).toContain('"\' +SUM(1,1)"');
    expect(csv).toContain('"\'@cmd"');
    clickSpy.mockRestore();
  });

  it('dismisses bulk reset success banner', () => {
    const setBulkResetMessage = vi.fn();
    render(
      <CompetitorManager
        {...baseProps}
        bulkResetMessage="Passwords were reset for 1 competitor."
        setBulkResetMessage={setBulkResetMessage}
      />,
    );
    fireEvent.click(screen.getByText('Clear List'));
    expect(setBulkResetMessage).toHaveBeenCalledWith('');
  });

  it('triggers table actions (Edit and Reset Password)', () => {
    const handleResetUserPassword = vi.fn();
    render(
      <CompetitorManager
        {...baseProps}
        competitorsList={[ALICE]}
        handleResetUserPassword={handleResetUserPassword}
      />,
    );
    fireEvent.click(screen.getByText('Reset PW'));
    expect(handleResetUserPassword).toHaveBeenCalledWith(10, 'Alice Smith');

    fireEvent.click(screen.getByText('Edit'));
    expect(screen.getByRole('heading', { name: 'Edit Competitor Details' })).toBeInTheDocument();
  });

  it('opens the editor in place of the forms and list, and Back returns to them', async () => {
    render(<CompetitorManager {...baseProps} competitorsList={[ALICE]} />);
    fireEvent.click(screen.getByText('Edit'));

    expect(screen.getByRole('heading', { name: 'Edit Competitor Details' })).toBeInTheDocument();
    expect(screen.queryByText('Manual Competitor Registration')).not.toBeInTheDocument();
    expect(screen.queryByText('Import Competitors CSV')).not.toBeInTheDocument();
    expect(screen.queryByText('Registered Competitors')).not.toBeInTheDocument();
    expect(screen.getByLabelText('System Username')).toHaveValue('alice123');
    expect(screen.getByLabelText('System Username')).toBeDisabled();
    expect(screen.getByLabelText('First Name')).toHaveValue('Alice');
    expect(screen.getByLabelText('School')).toHaveValue('Math School');

    fireEvent.click(screen.getByRole('button', { name: /Back/ }));
    expect(await screen.findByText('Manual Competitor Registration')).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'Edit Competitor Details' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('A001')).toBeInTheDocument();
  });

  it('Cancel closes the unchanged editor and returns to the list', async () => {
    render(<CompetitorManager {...baseProps} competitorsList={[ALICE]} />);
    fireEvent.click(screen.getByText('Edit'));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(await screen.findByText('Registered Competitors')).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'Edit Competitor Details' }),
    ).not.toBeInTheDocument();
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it('saves the edited competitor and returns to the list', async () => {
    mockUpdateUser.mockResolvedValue({ ok: true, data: {} });
    render(<CompetitorManager {...baseProps} competitorsList={[ALICE]} />);
    fireEvent.click(screen.getByText('Edit'));
    fireEvent.change(screen.getByLabelText('City'), { target: { value: 'Plovdiv' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save Changes' }).closest('form'));

    await waitFor(() =>
      expect(mockUpdateUser).toHaveBeenCalledWith(
        expect.objectContaining({ id: 10, city: 'Plovdiv', challenge_id: '1', email: null }),
      ),
    );
    expect(await screen.findByText('Registered Competitors')).toBeInTheDocument();
  });

  it('shows an invalid email under the email field without saving', () => {
    render(<CompetitorManager {...baseProps} competitorsList={[ALICE]} />);
    fireEvent.click(screen.getByText('Edit'));
    const email = screen.getByLabelText('Email Address');
    fireEvent.change(email, { target: { value: 'bad@' } });
    fireEvent.submit(email.closest('form'));

    expect(email.parentElement).toHaveTextContent('Please enter a valid email address');
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it('locks saving for the jury once the competition has started', () => {
    render(
      <CompetitorManager
        {...baseProps}
        currentUser={{ role: 'jury' }}
        isChallengeStarted={(id) => String(id) === '1'}
        challenges={[
          { id: 1, title: 'Challenge 1' },
          { id: 2, title: 'Challenge 2' },
        ]}
        competitorsList={[{ ...ALICE, challenge_id: 2 }]}
      />,
    );
    fireEvent.click(screen.getByText('Edit'));
    expect(screen.getByRole('button', { name: 'Save Changes' })).not.toBeDisabled();

    fireEvent.change(screen.getByLabelText('Assign Competition'), { target: { value: '1' } });
    expect(screen.getByRole('button', { name: 'Save Changes' })).toBeDisabled();
    expect(
      screen.getByText('This competition has started. Jury members cannot modify competitors.'),
    ).toBeInTheDocument();
  });

  it('triggers bulk password reset', () => {
    const competitors = [
      {
        id: 10,
        alias_id: 'comp1',
        name: 'Alice',
        surname: 'Smith',
        role: 'competitor',
        username: 'alice123',
        is_anonymous: false,
        grade: '10',
        school: 'Math School',
        city: 'Sofia',
        challenge_id: 1,
      },
    ];
    const handleBulkResetPasswords = vi.fn();
    render(
      <CompetitorManager
        {...baseProps}
        competitorsList={competitors}
        handleBulkResetPasswords={handleBulkResetPasswords}
      />,
    );
    fireEvent.click(screen.getByText('Reset All Passwords in Challenge'));
    expect(handleBulkResetPasswords).toHaveBeenCalledTimes(1);
  });
});
