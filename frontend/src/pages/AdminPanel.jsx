import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../AuthContext';
import { browserTimeZone } from '../utils/timezones';
import { useApp } from '../context/AppContext';
import useDebounce from '../hooks/useDebounce';
import { useAdminMetricsQuery } from '../hooks/useAdminMetricsQuery';
import { useUsersQuery } from '../hooks/useUsersQuery';
import { useCompetitorsQuery } from '../hooks/useCompetitorsQuery';
import { Navigate } from 'react-router';
import { useCreateChallenge } from '../hooks/useChallengeMutations';
import { useRegisterCompetitor, useCsvImportCompetitors } from '../hooks/useCompetitorMutations';
import {
  useRegisterUser,
  useDeleteUser,
  useResetPassword,
  useBulkResetPasswords,
} from '../hooks/useUserMutations';

import WorkersStats from '../components/admin/WorkersStats';
import BackupManager from '../components/admin/BackupManager';
import ChallengeList from '../components/admin/ChallengeList';
import TaskManager from '../components/admin/TaskManager';
import UserManager from '../components/admin/UserManager';
import CompetitorManager from '../components/admin/CompetitorManager';
import ChallengeConfig from '../components/admin/ChallengeConfig';
import SidebarNav from '../components/admin/SidebarNav';
import AuditLogViewer from '../components/admin/AuditLogViewer';
import SubmissionQueue from '../components/admin/SubmissionQueue';
import BulkResetDialog from '../components/admin/BulkResetDialog';
import { downloadCredentialsCsv } from '../utils/credentialsCsv';
import { useApiError } from '../hooks/useApiError';
import { useFieldErrors } from '../hooks/useFieldErrors';
import { useReveal } from '../hooks/useReveal';
import { useDiscardGuard } from '../hooks/useUnsavedChanges';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** A blank competition: in the browser's time zone, on CPU workers. */
function newChallengeForm() {
  return {
    title: '',
    description: '',
    max_eval_requests: 10,
    ram_limit_mb: 8192,
    time_limit_sec: 300,
    gpu_required: false,
    start_time: '',
    end_time: '',
    is_frozen: false,
    double_blind: true,
    timezone: browserTimeZone(),
    test_stage_start_time: '',
    test_stage_end_time: '',
  };
}

export default function AdminPanel() {
  const { t } = useTranslation();
  const { currentUser } = useAuth();
  const { mutateAsync: handleCreateChallengeAction, isPending: isCreatingChallenge } =
    useCreateChallenge();
  const { mutateAsync: handleRegisterCompetitorAction, isPending: isRegisteringCompetitor } =
    useRegisterCompetitor();
  const { mutateAsync: handleRegisterUserAction, isPending: isRegisteringUser } = useRegisterUser();
  const { mutateAsync: handleDeleteUserAction, isPending: isDeletingUser } = useDeleteUser();
  const { mutateAsync: handleCsvImportAction, isPending: isCsvImporting } =
    useCsvImportCompetitors();
  const { mutateAsync: handleResetPasswordAction, isPending: isResettingPassword } =
    useResetPassword();
  const { mutateAsync: handleBulkResetAction, isPending: isResettingBulk } =
    useBulkResetPasswords();

  const { challenges, selectedChallenge, setSelectedChallengeById, showToast, confirm } = useApp();

  const { showApiError } = useApiError();

  // Sub tab navigation
  const [adminSubTab, setAdminSubTab] = useState('competition-mgmt');
  // Remounts the tab content on every tab pick, which closes any editor left open in it
  const [tabVisit, setTabVisit] = useState(0);
  const [contentRef, revealContent] = useReveal({ singleColumnOnly: true });
  const confirmDiscard = useDiscardGuard();
  const competitorErrors = useFieldErrors();
  const userErrors = useFieldErrors();
  const csvErrors = useFieldErrors();
  const [bulkResetChoices, setBulkResetChoices] = useState(null);

  const isChallengeStarted = (challengeId) => {
    if (!challengeId) return false;
    const challenge = challenges.find((c) => c.id.toString() === challengeId.toString());
    if (!challenge || !challenge.start_time) return false;
    return new Date() >= new Date(challenge.start_time);
  };

  // Competition Creation (ChallengeConfig tab)
  const [newChallenge, setNewChallenge] = useState(newChallengeForm);

  // Task Form mode flags (used by SidebarNav to reset)
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [editingTask, setEditingTask] = useState(null);

  // Manual Competitor Register State
  const [newCompetitor, setNewCompetitor] = useState({
    name: '',
    middle_name: '',
    surname: '',
    birth_date: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false,
  });
  const [generatedCredentials, setGeneratedCredentials] = useState(null);
  const [resetCredentials, setResetCredentials] = useState(null);
  const [bulkResetMessage, setBulkResetMessage] = useState('');

  // User Management State
  const [userSearch, setUserSearch] = useState('');
  const debouncedUserSearch = useDebounce(userSearch, 300);
  const [usersPage, setUsersPage] = useState(1);
  const isAdmin = currentUser?.role === 'admin';
  const isAdminOrJury = isAdmin || currentUser?.role === 'jury';
  // Only fetch data for the visible sub-tab and endpoints the role may call
  const { data: usersData } = useUsersQuery(usersPage, debouncedUserSearch, 10, {
    enabled: isAdmin && adminSubTab === 'user-management',
  });
  const allUsers = usersData?.items || [];
  const usersTotal = usersData?.total || 0;
  const usersPages = usersData?.pages || 1;

  const [newUser, setNewUser] = useState({
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
  });
  const [generatedUserCredentials, setGeneratedUserCredentials] = useState(null);

  // CSV Import State
  const [csvFile, setCsvFile] = useState(null);
  const [csvChallengeId, setCsvChallengeId] = useState('');
  const [importedCompetitors, setImportedCompetitors] = useState([]);

  // Competitor Listing
  const [competitorSearch, setCompetitorSearch] = useState('');
  const debouncedCompetitorSearch = useDebounce(competitorSearch, 300);
  const [competitorsPage, setCompetitorsPage] = useState(1);
  const { data: competitorsData } = useCompetitorsQuery(
    selectedChallenge?.id,
    competitorsPage,
    debouncedCompetitorSearch,
    10,
    { enabled: isAdminOrJury && adminSubTab === 'competitor-reg' },
  );
  const competitorsList = competitorsData?.items || [];
  const competitorsTotal = competitorsData?.total || 0;
  const competitorsPages = competitorsData?.pages || 1;

  const { data: availableMetricsData } = useAdminMetricsQuery({
    enabled: isAdminOrJury && adminSubTab === 'competition-mgmt',
  });
  const availableMetrics = availableMetricsData || {};

  useEffect(() => {
    setUsersPage(1);
  }, [userSearch]);

  useEffect(() => {
    setCompetitorsPage(1);
  }, [competitorSearch]);

  if (currentUser?.role === 'competitor') {
    return <Navigate to="/challenges" replace />;
  }

  // Handle Competition creation
  const handleCreateChallenge = async (e, workspace = undefined) => {
    e.preventDefault();
    try {
      const result = await handleCreateChallengeAction(
        workspace ? { ...newChallenge, workspace } : newChallenge,
      );
      if (result.ok) {
        showToast(t('admin.notifications.competition_created'));
        setNewChallenge(newChallengeForm());
        setAdminSubTab('competition-mgmt');
      } else {
        showApiError(result.data, 'admin.notifications.competition_create_failed');
      }
    } catch (error) {
      showApiError(error, 'admin.notifications.network_error_create_competition');
      return error;
    }
    return null;
  };

  // Manual Competitor Registration
  const handleRegisterCompetitor = async (e) => {
    e.preventDefault();
    if (!newCompetitor.challenge_id) {
      competitorErrors.setErrors({ challenge_id: t('admin.notifications.select_competition') });
      return;
    }
    competitorErrors.reset();
    setGeneratedCredentials(null);

    try {
      const result = await handleRegisterCompetitorAction(newCompetitor);
      if (result.ok) {
        setGeneratedCredentials({
          username: result.data.generated_username,
          password: result.data.generated_password,
          name: newCompetitor.name,
          surname: newCompetitor.surname,
        });
        setNewCompetitor({
          name: '',
          middle_name: '',
          surname: '',
          birth_date: '',
          grade: '',
          school: '',
          city: '',
          challenge_id: '',
          is_anonymous: false,
        });
        showToast(t('admin.notifications.competitor_registered'));
      } else if (!competitorErrors.capture(result.data)) {
        showApiError(result.data, 'admin.notifications.competitor_register_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // User Administration Registration
  const handleRegisterUser = async (e) => {
    e.preventDefault();
    if (newUser.role === 'competitor' && !newUser.challenge_id) {
      userErrors.setErrors({
        challenge_id: t('admin.notifications.select_competition_competitor_role'),
      });
      return;
    }
    if (newUser.email && !EMAIL_RE.test(newUser.email)) {
      userErrors.setErrors({ email: t('admin.notifications.invalid_email') });
      return;
    }
    userErrors.reset();
    setGeneratedUserCredentials(null);

    try {
      // The password goes as typed: login sends plaintext and the server hashes it once
      const result = await handleRegisterUserAction(newUser);
      if (result.ok) {
        showToast(t('admin.notifications.user_registered'));
        setGeneratedUserCredentials({
          username: result.data.generated_username,
          password: result.data.generated_password,
          role: newUser.role,
          name: newUser.name,
          surname: newUser.surname,
        });
        setNewUser({
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
        });
      } else if (!userErrors.capture(result.data)) {
        showApiError(result.data, 'admin.notifications.user_register_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // Delete User
  const handleDeleteUser = async (userId, username) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_user_title'),
      message: t('admin.confirm.delete_user_message', { username }),
    });
    if (!ok) return;
    try {
      const result = await handleDeleteUserAction(userId);
      if (result.ok) {
        showToast(t('admin.notifications.user_deleted', { username }));
      } else {
        showApiError(result.data, 'admin.notifications.user_delete_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // CSV Competitors Import
  const handleCSVImport = async (e) => {
    e.preventDefault();
    if (!csvChallengeId) {
      csvErrors.setErrors({ challenge_id: t('admin.notifications.select_competition') });
      return;
    }
    if (!csvFile) {
      csvErrors.setErrors({ file: t('admin.notifications.select_csv_file') });
      return;
    }
    csvErrors.reset();
    setImportedCompetitors([]);

    const fd = new FormData();
    fd.append('file', csvFile);
    fd.append('challenge_id', csvChallengeId);

    try {
      const result = await handleCsvImportAction(fd);
      if (result.ok) {
        showToast(
          t('admin.notifications.imported_competitors_success', {
            count: result.data.competitors?.length || 0,
          }),
        );
        setImportedCompetitors(result.data.competitors || []);
        setCsvFile(null);
      } else {
        showApiError(result.data, 'admin.notifications.import_csv_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  const handleResetUserPassword = async (userId, displayName) => {
    const ok = await confirm({
      title: t('admin.confirm.reset_password_title'),
      message: t('admin.confirm.reset_password_message', { displayName }),
    });
    if (!ok) return;
    try {
      const result = await handleResetPasswordAction(userId);
      if (result.ok) {
        showToast(t('admin.notifications.password_reset_success'));
        setResetCredentials({ username: result.data.username, password: result.data.password });
        setBulkResetMessage('');
      } else {
        showApiError(result.data, 'admin.notifications.password_reset_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error_reset_password'), 'rose');
    }
  };

  const handleBulkResetPasswords = () => {
    const eligible = challenges.filter(
      (c) => currentUser.role === 'admin' || !isChallengeStarted(c.id),
    );
    if (eligible.length === 0) {
      showToast(t('admin.notifications.no_eligible_competitions'), 'rose');
      return;
    }
    setBulkResetChoices(eligible);
  };

  const handleBulkResetChosen = async (challenge) => {
    setBulkResetChoices(null);
    const ok = await confirm({
      title: t('admin.confirm.confirm_bulk_reset_title'),
      message: t('admin.confirm.confirm_bulk_reset_message', { title: challenge.title }),
    });
    if (!ok) return;

    try {
      const result = await handleBulkResetAction(challenge.id);
      if (result.ok) {
        const accounts = result.data.reset_accounts || [];
        // The passwords exist only in this response, so save them right away
        downloadCredentialsCsv(accounts, challenge.title);
        showToast(t('admin.notifications.bulk_reset_success'));
        setBulkResetMessage(t('admin.competitor_reg.bulk_reset_done', { count: accounts.length }));
        setResetCredentials(null);
      } else {
        showApiError(result.data, 'admin.notifications.bulk_reset_failed');
      }
    } catch {
      showToast(t('admin.notifications.network_error_bulk_reset'), 'rose');
    }
  };

  const selectTab = async (tab) => {
    if (!(await confirmDiscard())) return;
    setIsCreatingTask(false);
    setEditingTask(null);
    setAdminSubTab(tab);
    setTabVisit((n) => n + 1);
    revealContent();
  };

  const filteredUsers = allUsers;

  const isManualRegisterDisabled =
    currentUser.role === 'jury' && isChallengeStarted(newCompetitor.challenge_id);
  const isCSVImportDisabled = currentUser.role === 'jury' && isChallengeStarted(csvChallengeId);

  // Render components
  return (
    <>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start animate-fadein">
        <SidebarNav adminSubTab={adminSubTab} onSelectTab={selectTab} currentUser={currentUser} />

        {/* Main Workspace Work Areas */}
        <div ref={contentRef} key={tabVisit} className="lg:col-span-3">
          {/* 1. COMPETITION & TASK CONFIGURATION */}
          {adminSubTab === 'competition-mgmt' && !isCreatingTask && !editingTask && (
            <ChallengeList
              onAddTask={(challengeId) => {
                if (challengeId) setSelectedChallengeById(challengeId);
                setIsCreatingTask(true);
              }}
              onEditTask={(task) => setEditingTask(task)}
            />
          )}

          {/* 2. TASK EDITING OR CREATION (The Sandbox + HF + Rules form) */}
          {adminSubTab === 'competition-mgmt' && (isCreatingTask || editingTask) && (
            <TaskManager
              mode={isCreatingTask ? 'create' : 'edit'}
              initialTask={editingTask}
              challenges={challenges}
              selectedChallenge={selectedChallenge}
              availableMetrics={availableMetrics}
              isAdmin={isAdmin}
              onClose={() => {
                setIsCreatingTask(false);
                setEditingTask(null);
              }}
            />
          )}

          {/* 3. CREATE NEW COMPETITIONS */}
          {adminSubTab === 'challenge-config' && currentUser.role === 'admin' && (
            <ChallengeConfig
              handleCreateChallenge={handleCreateChallenge}
              newChallenge={newChallenge}
              setNewChallenge={setNewChallenge}
              isCreatingChallenge={isCreatingChallenge}
            />
          )}

          {/* 4. COMPETITOR REGISTRATION MODULE (JURY/ADMIN) */}
          {adminSubTab === 'competitor-reg' && (
            <CompetitorManager
              challenges={challenges}
              newCompetitor={newCompetitor}
              setNewCompetitor={(next) => {
                setNewCompetitor(next);
                competitorErrors.reset();
              }}
              handleRegisterCompetitor={handleRegisterCompetitor}
              registerErrors={competitorErrors.errors}
              isManualRegisterDisabled={isManualRegisterDisabled}
              generatedCredentials={generatedCredentials}
              csvChallengeId={csvChallengeId}
              setCsvChallengeId={(id) => {
                setCsvChallengeId(id);
                csvErrors.reset();
              }}
              csvFile={csvFile}
              setCsvFile={(file) => {
                setCsvFile(file);
                csvErrors.reset();
              }}
              csvImporting={isCsvImporting}
              isCSVImportDisabled={isCSVImportDisabled}
              handleCSVImport={handleCSVImport}
              csvErrors={csvErrors.errors}
              importedCompetitors={importedCompetitors}
              resetCredentials={resetCredentials}
              setResetCredentials={setResetCredentials}
              bulkResetMessage={bulkResetMessage}
              setBulkResetMessage={setBulkResetMessage}
              competitorsList={competitorsList}
              competitorSearch={competitorSearch}
              setCompetitorSearch={setCompetitorSearch}
              handleBulkResetPasswords={handleBulkResetPasswords}
              currentUser={currentUser}
              selectedChallenge={selectedChallenge}
              isChallengeStarted={isChallengeStarted}
              handleResetUserPassword={handleResetUserPassword}
              competitorsPage={competitorsPage}
              competitorsPages={competitorsPages}
              competitorsTotal={competitorsTotal}
              setCompetitorsPage={setCompetitorsPage}
              isRegisteringCompetitor={isRegisteringCompetitor}
              isResettingBulkPasswords={isResettingBulk}
              isResettingPassword={isResettingPassword}
            />
          )}

          {/* 5. DATABASE BACKUP MANAGEMENT */}
          {adminSubTab === 'backups' && currentUser.role === 'admin' && <BackupManager />}

          {/* 6. SYSTEM USER MANAGEMENT */}
          {adminSubTab === 'user-management' && currentUser.role === 'admin' && (
            <UserManager
              newUser={newUser}
              setNewUser={(next) => {
                setNewUser(next);
                userErrors.reset();
              }}
              handleRegisterUser={handleRegisterUser}
              registerErrors={userErrors.errors}
              isRegisteringUser={isRegisteringUser}
              generatedUserCredentials={generatedUserCredentials}
              allUsers={filteredUsers}
              userSearch={userSearch}
              setUserSearch={setUserSearch}
              handleDeleteUser={handleDeleteUser}
              isDeletingUser={isDeletingUser}
              usersPage={usersPage}
              usersPages={usersPages}
              usersTotal={usersTotal}
              setUsersPage={setUsersPage}
              challenges={challenges}
              currentUser={currentUser}
              isChallengeStarted={isChallengeStarted}
            />
          )}

          {/* 7. WORKERS MONITORING MODULE */}
          {adminSubTab === 'workers-stats' &&
            (currentUser.role === 'admin' || currentUser.role === 'jury') && <WorkersStats />}

          {/* 8. SUBMISSION QUEUE */}
          {adminSubTab === 'submission-queue' &&
            (currentUser.role === 'admin' || currentUser.role === 'jury') && <SubmissionQueue />}

          {/* 9. AUDIT LOGS */}
          {adminSubTab === 'audit-logs' && currentUser.role === 'admin' && <AuditLogViewer />}
        </div>
      </div>

      {bulkResetChoices && (
        <BulkResetDialog
          challenges={bulkResetChoices}
          onClose={() => setBulkResetChoices(null)}
          onChoose={handleBulkResetChosen}
        />
      )}
    </>
  );
}
