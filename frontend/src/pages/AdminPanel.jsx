import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import api from '../services/ApiService';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import { useQueryClient } from '@tanstack/react-query';
import useDebounce from '../hooks/useDebounce';
import useSSE from '../hooks/useSSE';
import useMutation from '../hooks/useMutation';
import { useAdminMetricsQuery } from '../hooks/useAdminMetricsQuery';
import { useUsersQuery } from '../hooks/useUsersQuery';
import { useCompetitorsQuery } from '../hooks/useCompetitorsQuery';
import { Navigate } from 'react-router-dom';
import InputField from '../components/ui/InputField';
import Button from '../components/ui/Button';
import SelectField from '../components/ui/SelectField';
import ToggleField from '../components/ui/ToggleField';

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
import { TIMEZONES } from '../utils/timezones';
// eslint-disable-next-line react-refresh/only-export-components
export { formatMetricName } from '../components/admin/TaskManager';

export default function AdminPanel() {
  const { t } = useTranslation();
  const { currentUser } = useAuth();
  const { isLoading, run } = useMutation();

  const {
    challenges,
    selectedChallenge,
    setSelectedChallengeById,
    fetchChallenges,
    showToast,
    confirm,
  } = useApp();

  const API_BASE = '/api';
  const showApiError = (data, defaultTranslationKey, defaultText = '') => {
    if (data?.code) {
      showToast(t(`api.${data.code}`, data.error || t(defaultTranslationKey, defaultText)), 'rose');
    } else {
      showToast(data?.error || t(defaultTranslationKey, defaultText), 'rose');
    }
  };

  // Sub tab navigation
  const [adminSubTab, setAdminSubTab] = useState('competition-mgmt');

  const isChallengeStarted = (challengeId) => {
    if (!challengeId) return false;
    const challenge = challenges.find((c) => c.id.toString() === challengeId.toString());
    if (!challenge || !challenge.start_time) return false;
    return new Date() >= new Date(challenge.start_time);
  };

  const formatUptime = (seconds) => {
    if (seconds === undefined || seconds === null) return 'N/A';
    const d = Math.floor(seconds / (3600 * 24));
    const h = Math.floor((seconds % (3600 * 24)) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    const parts = [];
    if (d > 0) parts.push(`${d}d`);
    if (h > 0) parts.push(`${h}h`);
    if (m > 0) parts.push(`${m}m`);
    parts.push(`${s}s`);
    return parts.join(' ');
  };

  // Competition Creation (ChallengeConfig tab)
  const [newChallenge, setNewChallenge] = useState({
    title: '',
    description: '',
    max_eval_requests: 10,
    ram_limit_mb: 8192,
    time_limit_sec: 300,
    gpu_required: true,
    start_time: '',
    end_time: '',
    is_frozen: false,
    double_blind: true,
    timezone: 'UTC',
    test_stage_start_time: '',
    test_stage_end_time: '',
  });

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
  const [bulkResetCredentials, setBulkResetCredentials] = useState([]);

  const queryClient = useQueryClient();

  // User Management State
  const [userSearch, setUserSearch] = useState('');
  const debouncedUserSearch = useDebounce(userSearch, 300);
  const [usersPage, setUsersPage] = useState(1);
  const { data: usersData } = useUsersQuery(usersPage, debouncedUserSearch);
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

  // Competitor-reg Edit User State
  const [editingUser, setEditingUser] = useState(null);
  const [editUserForm, setEditUserForm] = useState({
    username: '',
    email: '',
    password: '',
    name: '',
    middle_name: '',
    surname: '',
    birth_date: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false,
    role: 'competitor',
    jury_challenges: [],
  });

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
  );
  const competitorsList = competitorsData?.items || [];
  const competitorsTotal = competitorsData?.total || 0;
  const competitorsPages = competitorsData?.pages || 1;

  // Workers & Resources State
  const [workerStats, setWorkerStats] = useState(null);
  const [workerStatsLoading, setWorkerStatsLoading] = useState(false);
  const [workerStatsError, setWorkerStatsError] = useState(null);

  const { data: availableMetricsData } = useAdminMetricsQuery();
  const availableMetrics = availableMetricsData || {};

  // Worker stats via SSE
  useSSE(adminSubTab === 'workers-stats' ? '/api/admin/workers/stats/live' : '', {
    onMessage: (data) => {
      if (data && !data.error) {
        setWorkerStats(data);
        setWorkerStatsError(null);
      } else if (data?.error) {
        setWorkerStatsError(data.error);
      }
      setWorkerStatsLoading(false);
    },
    onError: () => {
      setWorkerStatsError(t('admin.workers.fetch_stats_network_error'));
      setWorkerStatsLoading(false);
    },
  });

  const fetchWorkerStats = () => setWorkerStatsLoading(true);

  const invalidateUsers = () => queryClient.invalidateQueries({ queryKey: ['admin-users'] });
  const invalidateCompetitors = () =>
    queryClient.invalidateQueries({ queryKey: ['admin-competitors'] });
  const fetchUsers = invalidateUsers;
  const fetchCompetitors = invalidateCompetitors;

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
  const handleCreateChallenge = async (e) => {
    e.preventDefault();
    try {
      await run('createChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newChallenge),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.competition_created'));
          setNewChallenge({
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
            timezone: 'UTC',
            test_stage_start_time: '',
            test_stage_end_time: '',
          });
          fetchChallenges();
          setAdminSubTab('competition-mgmt');
        } else {
          showApiError(data, 'admin.notifications.competition_create_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_create_competition'), 'rose');
    }
  };

  // Manual Competitor Registration
  const handleRegisterCompetitor = async (e) => {
    e.preventDefault();
    if (!newCompetitor.challenge_id) {
      showToast(t('admin.notifications.select_competition'), 'rose');
      return;
    }
    setGeneratedCredentials(null);

    try {
      await run('registerCompetitor', async () => {
        const res = await api.fetch(`${API_BASE}/admin/register-competitor`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newCompetitor),
        });
        const data = await res.json();
        if (res.ok) {
          setGeneratedCredentials({
            username: data.generated_username,
            password: data.generated_password,
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
          fetchCompetitors();
        } else {
          showApiError(data, 'admin.notifications.competitor_register_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // User Administration Registration
  const handleRegisterUser = async (e) => {
    e.preventDefault();
    if (newUser.role === 'competitor' && !newUser.challenge_id) {
      showToast(t('admin.notifications.select_competition_competitor_role'), 'rose');
      return;
    }
    if (newUser.email) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(newUser.email)) {
        showToast(
          t('admin.notifications.invalid_email', 'Please enter a valid email address'),
          'rose',
        );
        return;
      }
    }
    setGeneratedUserCredentials(null);

    const hashPassword = async (p) => {
      const msgBuffer = new TextEncoder().encode(p);
      const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
      return Array.from(new Uint8Array(hashBuffer))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
    };

    const requestBody = { ...newUser };
    if (newUser.password) {
      requestBody.password = await hashPassword(newUser.password);
    }

    try {
      await run('registerUser', async () => {
        const res = await api.fetch(`${API_BASE}/admin/register-user`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.user_registered'));
          setGeneratedUserCredentials({
            username: data.generated_username,
            password: data.generated_password,
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
          fetchUsers();
        } else {
          showApiError(data, 'admin.notifications.user_register_failed');
        }
      });
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
      await run('deleteUser', async () => {
        const res = await api.fetch(`${API_BASE}/admin/users/${userId}`, {
          method: 'DELETE',
          headers: {},
        });
        if (res.ok) {
          showToast(t('admin.notifications.user_deleted', { username }));
          fetchUsers();
        } else {
          const data = await res.json();
          showApiError(data, 'admin.notifications.user_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // CSV Competitors Import
  const handleCSVImport = async (e) => {
    e.preventDefault();
    if (!csvChallengeId) {
      showToast(t('admin.notifications.select_competition'), 'rose');
      return;
    }
    if (!csvFile) {
      showToast(t('admin.notifications.select_csv_file'), 'rose');
      return;
    }
    setImportedCompetitors([]);

    const fd = new FormData();
    fd.append('file', csvFile);
    fd.append('challenge_id', csvChallengeId);

    try {
      await run('csvImport', async () => {
        const res = await api.fetch(`${API_BASE}/admin/import-competitors-csv`, {
          method: 'POST',
          headers: {},
          body: fd,
        });
        const data = await res.json();
        if (res.ok) {
          showToast(
            t('admin.notifications.imported_competitors_success', {
              count: data.competitors?.length || 0,
            }),
          );
          setImportedCompetitors(data.competitors || []);
          setCsvFile(null);
          fetchCompetitors();
        } else {
          showApiError(data, 'admin.notifications.import_csv_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // User editing (competitor-reg)
  const initEditUser = (user) => {
    setEditingUser(user);
    setEditUserForm({
      username: user.username || '',
      email: user.email || '',
      password: '',
      name: user.name || '',
      middle_name: user.middle_name || '',
      surname: user.surname || '',
      birth_date: user.birth_date || '',
      grade: user.grade || '',
      school: user.school || '',
      city: user.city || '',
      challenge_id: user.challenge_id ? user.challenge_id.toString() : '',
      is_anonymous: user.is_anonymous || false,
      role: user.role || 'competitor',
      jury_challenges: user.jury_challenges || [],
    });
  };

  const handleUpdateUserSubmit = async (e) => {
    e.preventDefault();
    if (editUserForm.email) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(editUserForm.email)) {
        showToast(
          t('admin.notifications.invalid_email', 'Please enter a valid email address'),
          'rose',
        );
        return;
      }
    }
    try {
      await run('updateUser', async () => {
        const res = await api.fetch(`${API_BASE}/admin/users/${editingUser.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: editUserForm.username,
            email: editUserForm.email || null,
            password: editUserForm.password || null,
            name: editUserForm.name,
            middle_name: editUserForm.middle_name || null,
            surname: editUserForm.surname,
            birth_date: editUserForm.birth_date || null,
            grade: editUserForm.grade || null,
            school: editUserForm.school || null,
            city: editUserForm.city || null,
            challenge_id: editUserForm.challenge_id === '' ? '' : editUserForm.challenge_id,
            is_anonymous: editUserForm.is_anonymous,
            role: editUserForm.role,
            jury_challenges: editUserForm.jury_challenges,
          }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.competitor_updated'));
          setEditingUser(null);
          fetchUsers();
          fetchCompetitors();
        } else {
          showApiError(data, 'admin.notifications.competitor_update_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_competitor'), 'rose');
    }
  };

  const handleResetUserPassword = async (userId, displayName) => {
    const ok = await confirm({
      title: t('admin.confirm.reset_password_title'),
      message: t('admin.confirm.reset_password_message', { displayName }),
    });
    if (!ok) return;
    try {
      await run('resetPassword', async () => {
        const res = await api.fetch(`${API_BASE}/admin/users/${userId}/reset-password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.password_reset_success'));
          setResetCredentials({ username: data.username, password: data.password });
          setBulkResetCredentials([]);
        } else {
          showApiError(data, 'admin.notifications.password_reset_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_reset_password'), 'rose');
    }
  };

  const handleBulkResetPasswords = async () => {
    const activeChallenges = challenges.filter(
      (c) => currentUser.role === 'admin' || !isChallengeStarted(c.id),
    );
    if (activeChallenges.length === 0) {
      showToast(t('admin.notifications.no_eligible_competitions'), 'rose');
      return;
    }

    const optionsStr = activeChallenges.map((c) => `ID ${c.id}: ${c.title}`).join('\n');
    const input = await confirm({
      title: t('admin.confirm.bulk_reset_title'),
      message: t('admin.confirm.bulk_reset_message', { optionsStr }),
      isPrompt: true,
      placeholder: t('admin.confirm.bulk_reset_placeholder'),
    });
    if (input === null) return;

    const selectedId = input.trim();
    const challenge = activeChallenges.find((c) => c.id.toString() === selectedId);
    if (!challenge) {
      showToast(t('admin.notifications.invalid_competition_id'), 'rose');
      return;
    }

    const ok = await confirm({
      title: t('admin.confirm.confirm_bulk_reset_title'),
      message: t('admin.confirm.confirm_bulk_reset_message', { title: challenge.title }),
    });
    if (!ok) return;

    try {
      await run('bulkResetPasswords', async () => {
        const res = await api.fetch(
          `${API_BASE}/admin/challenges/${challenge.id}/reset-all-passwords`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
          },
        );
        const data = await res.json();
        if (res.ok) {
          showToast(
            t('admin.notifications.bulk_reset_success', { count: data.reset_accounts?.length }),
          );
          setBulkResetCredentials(data.reset_accounts || []);
          setResetCredentials(null);
        } else {
          showApiError(data, 'admin.notifications.bulk_reset_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_bulk_reset'), 'rose');
    }
  };

  const filteredUsers = allUsers;

  const isManualRegisterDisabled =
    currentUser.role === 'jury' && isChallengeStarted(newCompetitor.challenge_id);
  const isCSVImportDisabled = currentUser.role === 'jury' && isChallengeStarted(csvChallengeId);
  const isEditDisabled =
    currentUser.role === 'jury' && isChallengeStarted(editUserForm.challenge_id);

  // Render components
  return (
    <>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start animate-fadein">
        <SidebarNav
          adminSubTab={adminSubTab}
          setAdminSubTab={setAdminSubTab}
          currentUser={currentUser}
          setIsCreatingTask={setIsCreatingTask}
          setEditingTask={setEditingTask}
          setIsCreatingStage={() => {}}
          setEditingStage={() => {}}
          setFinalizingStage={() => {}}
        />

        {/* Main Workspace Work Areas */}
        <div className="lg:col-span-3">
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
              timezones={TIMEZONES}
              isCreatingChallenge={isLoading('createChallenge')}
            />
          )}

          {/* 4. COMPETITOR REGISTRATION MODULE (JURY/ADMIN) */}
          {adminSubTab === 'competitor-reg' && (
            <CompetitorManager
              challenges={challenges}
              newCompetitor={newCompetitor}
              setNewCompetitor={setNewCompetitor}
              handleRegisterCompetitor={handleRegisterCompetitor}
              isManualRegisterDisabled={isManualRegisterDisabled}
              generatedCredentials={generatedCredentials}
              csvChallengeId={csvChallengeId}
              setCsvChallengeId={setCsvChallengeId}
              csvFile={csvFile}
              setCsvFile={setCsvFile}
              csvImporting={false}
              isCSVImportDisabled={isCSVImportDisabled}
              handleCSVImport={handleCSVImport}
              importedCompetitors={importedCompetitors}
              resetCredentials={resetCredentials}
              setResetCredentials={setResetCredentials}
              bulkResetCredentials={bulkResetCredentials}
              setBulkResetCredentials={setBulkResetCredentials}
              competitorsList={competitorsList}
              competitorSearch={competitorSearch}
              setCompetitorSearch={setCompetitorSearch}
              handleBulkResetPasswords={handleBulkResetPasswords}
              currentUser={currentUser}
              selectedChallenge={selectedChallenge}
              isChallengeStarted={isChallengeStarted}
              initEditUser={initEditUser}
              handleResetUserPassword={handleResetUserPassword}
              competitorsPage={competitorsPage}
              competitorsPages={competitorsPages}
              competitorsTotal={competitorsTotal}
              setCompetitorsPage={setCompetitorsPage}
              isRegisteringCompetitor={isLoading('registerCompetitor')}
              isResettingBulkPasswords={isLoading('bulkResetPasswords')}
              isResettingPassword={isLoading('resetPassword')}
            />
          )}

          {/* 5. DATABASE BACKUP MANAGEMENT */}
          {adminSubTab === 'backups' && currentUser.role === 'admin' && <BackupManager />}

          {/* 6. SYSTEM USER MANAGEMENT */}
          {adminSubTab === 'user-management' && currentUser.role === 'admin' && (
            <UserManager
              newUser={newUser}
              setNewUser={setNewUser}
              handleRegisterUser={handleRegisterUser}
              isRegisteringUser={isLoading('registerUser')}
              generatedUserCredentials={generatedUserCredentials}
              allUsers={filteredUsers}
              userSearch={userSearch}
              setUserSearch={setUserSearch}
              handleDeleteUser={handleDeleteUser}
              isDeletingUser={isLoading('deleteUser')}
              usersPage={usersPage}
              usersPages={usersPages}
              usersTotal={usersTotal}
              setUsersPage={setUsersPage}
              challenges={challenges}
              currentUser={currentUser}
              fetchUsers={fetchUsers}
              fetchCompetitors={fetchCompetitors}
            />
          )}

          {/* 7. WORKERS MONITORING MODULE */}
          {adminSubTab === 'workers-stats' &&
            (currentUser.role === 'admin' || currentUser.role === 'jury') && (
              <WorkersStats
                workerStats={workerStats}
                workerStatsLoading={workerStatsLoading}
                workerStatsError={workerStatsError}
                fetchWorkerStats={fetchWorkerStats}
                formatUptime={formatUptime}
              />
            )}

          {/* 8. SUBMISSION QUEUE */}
          {adminSubTab === 'submission-queue' &&
            (currentUser.role === 'admin' || currentUser.role === 'jury') && <SubmissionQueue />}

          {/* 9. AUDIT LOGS */}
          {adminSubTab === 'audit-logs' && currentUser.role === 'admin' && <AuditLogViewer />}
        </div>
      </div>

      {/* Edit Competitor Modal */}
      {editingUser &&
        adminSubTab === 'competitor-reg' &&
        createPortal(
          <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center z-[10000] p-4">
            <div className="bg-[#0b0c16] border border-white/10 rounded-2xl max-w-lg w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-fadein">
              <form
                onSubmit={handleUpdateUserSubmit}
                noValidate
                className="flex flex-col flex-1 min-h-0"
              >
                {/* Header */}
                <div className="p-6 border-b border-white/5 flex-shrink-0">
                  <h2 className="text-lg font-bold text-white mb-1">
                    {t('admin.competitor_reg.edit_competitor_details')}
                  </h2>
                  <p className="text-slate-400 text-xs">
                    {t('admin.competitor_reg.updating_account', { username: editingUser.username })}
                  </p>
                </div>

                {/* Form Body (Scrollable) */}
                <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
                  <div className="grid grid-cols-3 gap-4">
                    <InputField
                      label={t('admin.competitor_reg.first_name')}
                      value={editUserForm.name}
                      onChange={(e) => setEditUserForm({ ...editUserForm, name: e.target.value })}
                      required
                    />
                    <InputField
                      label={t('admin.competitor_reg.middle_name')}
                      value={editUserForm.middle_name || ''}
                      onChange={(e) =>
                        setEditUserForm({ ...editUserForm, middle_name: e.target.value })
                      }
                      required
                    />
                    <InputField
                      label={t('admin.competitor_reg.last_name')}
                      value={editUserForm.surname}
                      onChange={(e) =>
                        setEditUserForm({ ...editUserForm, surname: e.target.value })
                      }
                      required
                    />
                  </div>

                  <InputField
                    label={t('admin.competitor_reg.birth_date')}
                    type="date"
                    value={editUserForm.birth_date || ''}
                    onChange={(e) =>
                      setEditUserForm({ ...editUserForm, birth_date: e.target.value })
                    }
                    required
                  />

                  <div className="grid grid-cols-3 gap-4">
                    <InputField
                      label={t('admin.competitor_reg.grade')}
                      value={editUserForm.grade || ''}
                      onChange={(e) => setEditUserForm({ ...editUserForm, grade: e.target.value })}
                      required
                    />
                    <InputField
                      label={t('admin.competitor_reg.school')}
                      value={editUserForm.school || ''}
                      onChange={(e) => setEditUserForm({ ...editUserForm, school: e.target.value })}
                      required
                    />
                    <InputField
                      label={t('admin.competitor_reg.city')}
                      value={editUserForm.city || ''}
                      onChange={(e) => setEditUserForm({ ...editUserForm, city: e.target.value })}
                      required
                    />
                  </div>

                  <InputField
                    label={t('admin.competitor_reg.system_username')}
                    value={editUserForm.username}
                    onChange={(e) => setEditUserForm({ ...editUserForm, username: e.target.value })}
                    required
                    disabled
                  />

                  <InputField
                    label={t('admin.competitor_reg.email_address')}
                    type="text"
                    value={editUserForm.email || ''}
                    onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })}
                    placeholder={t('admin.competitor_reg.email_placeholder')}
                  />

                  <SelectField
                    label={t('admin.competitor_reg.assign_competition')}
                    value={editUserForm.challenge_id}
                    onChange={(val) => setEditUserForm({ ...editUserForm, challenge_id: val })}
                    required
                    options={[
                      { value: '', label: t('admin.competitor_reg.assign_competition_choose') },
                      ...challenges.map((c) => ({ value: c.id.toString(), label: c.title })),
                    ]}
                  />

                  <div className="mt-2.5">
                    <ToggleField
                      label={t('admin.competitor_reg.anonymous_help')}
                      id="edit-is-anonymous"
                      checked={editUserForm.is_anonymous}
                      onChange={(e) =>
                        setEditUserForm({ ...editUserForm, is_anonymous: e.target.checked })
                      }
                    />
                  </div>

                  {isEditDisabled && (
                    <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                      {t('admin.competitor_reg.competition_started_warning')}
                    </div>
                  )}
                </div>

                {/* Footer */}
                <div className="p-6 border-t border-white/5 flex justify-end gap-3 flex-shrink-0">
                  <Button type="button" variant="secondary" onClick={() => setEditingUser(null)}>
                    {t('common.cancel')}
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={isEditDisabled || isLoading('updateUser')}
                  >
                    {t('admin.stages.save_changes_btn')}
                  </Button>
                </div>
              </form>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
