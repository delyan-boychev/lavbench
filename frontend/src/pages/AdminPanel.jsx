import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import api from '../services/ApiService';
import ChallengeService from '../services/ChallengeService';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import Badge from '../components/ui/Badge';
import useDebounce from '../hooks/useDebounce';
import useSSE from '../hooks/useSSE';
import useMutation from '../hooks/useMutation';
import { Navigate } from 'react-router-dom';
import InputField from '../components/ui/InputField';
import Button from '../components/ui/Button';
import SelectField from '../components/ui/SelectField';
import Pagination from '../components/ui/Pagination';
import ToggleField from '../components/ui/ToggleField';
import { Plus } from 'lucide-react';

import WorkersStats from '../components/admin/WorkersStats';
import BackupManager from '../components/admin/BackupManager';
import UserManager from '../components/admin/UserManager';
import CompetitorManager from '../components/admin/CompetitorManager';
import ChallengeConfig from '../components/admin/ChallengeConfig';
import TaskForm from '../components/admin/TaskForm';
import SidebarNav from '../components/admin/SidebarNav';
import AuditLogViewer from '../components/admin/AuditLogViewer';
import { TIMEZONES } from '../utils/timezones';
import { formatMetricName } from '../utils/metrics';
import { formatDateTime } from '../utils/formatDate';
// eslint-disable-next-line react-refresh/only-export-components
export { formatMetricName };

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
  const importFileRef = useRef(null);

  // Sub tab navigation
  const [adminSubTab, setAdminSubTab] = useState('competition-mgmt');

  const formatDateTimeLocal = (dateStr) => {
    if (!dateStr) return '';
    return dateStr.substring(0, 16);
  };

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

  // Competition Creation
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

  // Edit Challenge State
  const [editingChallenge, setEditingChallenge] = useState(null);

  // Task Form State
  const [editingTask, setEditingTask] = useState(null); // Task object or null
  const [isCreatingTask, setIsCreatingTask] = useState(false); // boolean
  const [savingTask] = useState(false);
  const [taskForm, setTaskForm] = useState({
    title: '',
    description: '',
    ram_limit_mb: '',
    time_limit_sec: '',
    gpu_required: true,
    base_docker_image: '',
    apt_packages: '',
    pip_requirements: '',
    ban_magic_commands: false,
    banned_imports: '',
    whitelisted_imports: '',
    metrics_config: '',
    hf_datasets_raw: '',
    hf_models_raw: '',
    hf_api_key: '',
    public_eval_percentage: 30,
    max_submissions_per_period: '',
    submission_period_hours: '',
    stage_id: '',
  });

  // Task Upload Files
  const [taskFiles, setTaskFiles] = useState([]);
  const [baselineFile, setBaselineFile] = useState(null);
  const [evaluatorScript, setEvaluatorScript] = useState(null);
  const [evaluatorDeleted, setEvaluatorDeleted] = useState(false);

  // Stage CRUD & Finalization State
  const [isCreatingStage, setIsCreatingStage] = useState(false);
  const [editingStage, setEditingStage] = useState(null);
  const [stageChallengeId, setStageChallengeId] = useState(null);
  const [stageForm, setStageForm] = useState({
    title: '',
    stage_number: '',
    start_time: '',
    end_time: '',
    reveal_results: false,
  });

  const [finalizingStage, setFinalizingStage] = useState(null);
  const [stageFinalizeForm, setStageFinalizeForm] = useState({
    reveal_results: false,
  });

  const [finalizingChallenge, setFinalizingChallenge] = useState(null);
  const [challengeFinalizeForm, setChallengeFinalizeForm] = useState({
    reveal_results: false,
  });

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

  // User Management State
  const [allUsers, setAllUsers] = useState([]);
  const [userSearch, setUserSearch] = useState('');
  const debouncedUserSearch = useDebounce(userSearch, 300);
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

  // User Editing State
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
  const [csvImporting] = useState(false);
  const [csvChallengeId, setCsvChallengeId] = useState('');
  const [importedCompetitors, setImportedCompetitors] = useState([]);

  // Competitor Listing
  const [competitorsList, setCompetitorsList] = useState([]);
  const [competitorSearch, setCompetitorSearch] = useState('');
  const debouncedCompetitorSearch = useDebounce(competitorSearch, 300);
  const [competitorsPage, setCompetitorsPage] = useState(1);
  const [competitorsTotal, setCompetitorsTotal] = useState(0);
  const [competitorsPages, setCompetitorsPages] = useState(1);

  // Users Pagination State
  const [usersPage, setUsersPage] = useState(1);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersPages, setUsersPages] = useState(1);

  // Challenges Pagination State
  const [challengesPage, setChallengesPage] = useState(1);
  const [challengesTotal, setChallengesTotal] = useState(0);
  const [challengesPages, setChallengesPages] = useState(1);
  const [paginatedChallengesList, setPaginatedChallengesList] = useState([]);

  // Workers & Resources State
  const [workerStats, setWorkerStats] = useState(null);
  const [workerStatsLoading, setWorkerStatsLoading] = useState(false);
  const [workerStatsError, setWorkerStatsError] = useState(null);

  const [availableMetrics, setAvailableMetrics] = useState({});

  const fetchAvailableMetrics = useCallback(async () => {
    try {
      /** @type {Response} */
      const res = await api.fetch(`${API_BASE}/admin/metrics`, {
        headers: {},
      });
      if (res.ok) {
        /** @type {import('../types/api').paths['/api/admin/metrics']['get']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        setAvailableMetrics(data);
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    if (!currentUser) return;
    let cancelled = false;
    fetchAvailableMetrics().then(() => {
      if (cancelled) setAvailableMetrics([]);
    });
    return () => {
      cancelled = true;
    };
  }, [currentUser, fetchAvailableMetrics]);

  // Worker stats via SSE (persistent connection, no polling)

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

  const fetchUsers = useCallback(async () => {
    try {
      /** @type {Response} */
      const res = await api.fetch(
        `${API_BASE}/admin/users?page=${usersPage}&per_page=10&search=${userSearch}`,
        {
          headers: {},
        },
      );
      if (res.ok) {
        /** @type {import('../types/api').paths['/api/admin/users']['get']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        setAllUsers(data.items || []);
        setUsersTotal(data.total || 0);
        setUsersPages(data.pages || 1);
      }
    } catch (e) {
      console.error(e);
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  }, [usersPage, userSearch, showToast, t]);

  const fetchCompetitors = useCallback(async () => {
    if (!selectedChallenge) return;
    try {
      /** @type {Response} */
      const res = await api.fetch(
        `${API_BASE}/admin/users?page=${competitorsPage}&per_page=10&role=competitor&challenge_id=${selectedChallenge.id}&search=${competitorSearch}`,
        {
          headers: {},
        },
      );
      if (res.ok) {
        /** @type {import('../types/api').paths['/api/admin/users']['get']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        setCompetitorsList(data.items || []);
        setCompetitorsTotal(data.total || 0);
        setCompetitorsPages(data.pages || 1);
      }
    } catch (e) {
      console.error(e);
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  }, [selectedChallenge, competitorsPage, competitorSearch, showToast, t]);

  const fetchPaginatedChallenges = useCallback(async () => {
    try {
      /** @type {Response} */
      const res = await api.fetch(`${API_BASE}/challenges?page=${challengesPage}&per_page=5`, {
        headers: {},
      });
      if (res.ok) {
        /** @type {import('../types/api').paths['/api/challenges']['get']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        setPaginatedChallengesList(data.items);
        setChallengesTotal(data.total);
        setChallengesPages(data.pages);
      } else {
        showToast(t('admin.notifications.network_error'), 'rose');
        setPaginatedChallengesList([]);
      }
    } catch (e) {
      console.error(e);
    }
  }, [challengesPage, showToast, t]);

  useEffect(() => {
    if (adminSubTab === 'user-management') {
      fetchUsers(); // eslint-disable-line react-hooks/set-state-in-effect
    }
    // fetchUsers omitted from deps intentionally — its own deps (usersPage, userSearch)
    // are already listed, so identity changes coincide with existing dep changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminSubTab, usersPage, debouncedUserSearch]);

  useEffect(() => {
    if (adminSubTab === 'competitor-reg' || adminSubTab === 'competition-mgmt') {
      fetchCompetitors(); // eslint-disable-line react-hooks/set-state-in-effect
    }
    // fetchCompetitors omitted — its deps (selectedChallenge, competitorsPage, competitorSearch)
    // are already in this effect's deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminSubTab, selectedChallenge, competitorsPage, debouncedCompetitorSearch]);

  useEffect(() => {
    if (adminSubTab === 'competition-mgmt') {
      fetchPaginatedChallenges(); // eslint-disable-line react-hooks/set-state-in-effect
    }
    // fetchPaginatedChallenges omitted — its deps (challengesPage) are already listed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminSubTab, challengesPage]);

  useEffect(() => {
    if (adminSubTab === 'workers-stats') {
      // SSE handles updates — no polling needed
    }
  }, [adminSubTab]);

  useEffect(() => {
    setUsersPage(1); // eslint-disable-line react-hooks/set-state-in-effect
  }, [userSearch]);

  useEffect(() => {
    setCompetitorsPage(1); // eslint-disable-line react-hooks/set-state-in-effect
  }, [competitorSearch]);

  if (currentUser?.role === 'competitor') {
    return <Navigate to="/challenges" replace />;
  }

  // Handle Competition creation
  const handleCreateChallenge = async (e) => {
    e.preventDefault();
    try {
      await run('createChallenge', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(newChallenge),
        });
        /** @type {import('../types/api').paths['/api/challenges']['post']['responses']['201']['content']['application/json']} */
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
          fetchPaginatedChallenges();
          setAdminSubTab('competition-mgmt');
        } else {
          showApiError(data, 'admin.notifications.competition_create_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_create_competition'), 'rose');
    }
  };

  // Handle Competition update
  const handleUpdateChallenge = async (id, updated) => {
    let result = { success: false };
    try {
      await run('updateChallenge', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges/${id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(updated),
        });
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}']['put']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.competition_updated'));
          fetchChallenges();
          fetchPaginatedChallenges();
          result = { success: true };
        } else {
          showApiError(data, 'admin.notifications.competition_update_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_competition'), 'rose');
    }
    return result;
  };

  // Handle Competition delete
  const handleDeleteChallenge = async (id, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_competition_title'),
      message: t('admin.confirm.delete_competition_message', { title }),
    });
    if (!ok) return;
    try {
      await run('deleteChallenge', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges/${id}`, {
          method: 'DELETE',
          headers: {},
        });
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}']['delete']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.competition_deleted', { title }));
          if (editingChallenge?.id === id) setEditingChallenge(null);
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.competition_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_delete_competition'), 'rose');
    }
  };

  // Handle finalize scores setup
  const handleFinalizeSetup = (challenge) => {
    setFinalizingChallenge(challenge);
    setChallengeFinalizeForm({ reveal_results: false });
  };

  // Handle save/submit finalize challenge
  const handleSaveFinalizeChallenge = async (e) => {
    e.preventDefault();
    if (!finalizingChallenge) return;
    try {
      await run('finalizeChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${finalizingChallenge.id}/finalize`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            reveal_results: challengeFinalizeForm.reveal_results,
          }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.scores_finalized'));
          setFinalizingChallenge(null);
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.scores_finalize_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_finalize_scores'), 'rose');
    }
  };

  // Handle toggle reveal results for challenge
  const handleToggleRevealChallenge = async (id, currentRevealResults) => {
    const nextVal = !currentRevealResults;
    try {
      await run('toggleRevealChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${id}/reveal-results`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ reveal_results: nextVal }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast(
            nextVal
              ? t('admin.notifications.results_revealed', 'Results revealed successfully.')
              : t('admin.notifications.results_hidden', 'Results hidden successfully.'),
          );
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, '', 'Failed to toggle reveal');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  const handleToggleRevealStage = async (challengeId, stageId, currentRevealResults) => {
    const nextVal = !currentRevealResults;
    try {
      await run('toggleRevealStage', async () => {
        const res = await api.fetch(
          `${API_BASE}/challenges/${challengeId}/stages/${stageId}/reveal-results`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reveal_results: nextVal }),
          },
        );
        const data = await res.json();
        if (res.ok) {
          showToast(
            nextVal
              ? t('admin.notifications.stage_results_revealed', 'Stage results revealed.')
              : t('admin.notifications.stage_results_hidden', 'Stage results hidden.'),
          );
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, '', 'Failed to toggle stage reveal');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // Handle archive toggle
  const handleArchiveToggle = async (id) => {
    try {
      await run('archiveToggle', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges/${id}/archive`, {
          method: 'POST',
          headers: {},
        });
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}/archive']['post']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(data.message || t('admin.notifications.archive_toggle_success'));
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.archive_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // Stage management helpers
  const initCreateStage = (challengeId) => {
    setStageChallengeId(challengeId);
    setStageForm({
      title: '',
      stage_number: '',
      start_time: '',
      end_time: '',
      reveal_results: false,
    });
    setIsCreatingStage(true);
  };

  const initEditStage = (challengeId, stage) => {
    setStageChallengeId(challengeId);
    setEditingStage(stage);
    setStageForm({
      title: stage.title || '',
      stage_number:
        stage.stage_number !== null && stage.stage_number !== undefined
          ? stage.stage_number.toString()
          : '',
      start_time: formatDateTimeLocal(stage.start_time),
      end_time: formatDateTimeLocal(stage.end_time),
      reveal_results: !!stage.reveal_results,
    });
  };

  const initFinalizeStage = (challengeId, stage) => {
    setStageChallengeId(challengeId);
    setFinalizingStage(stage);
    setStageFinalizeForm({
      reveal_results: true,
    });
  };

  const handleSaveCreateStage = async (e) => {
    e.preventDefault();
    const payload = {
      title: stageForm.title,
      stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
      start_time: stageForm.start_time,
      end_time: stageForm.end_time,
    };
    try {
      await run('createStage', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges/${stageChallengeId}/stages`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        });
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}/stages']['post']['responses']['201']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_created'));
          setIsCreatingStage(false);
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_create_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_create_stage'), 'rose');
    }
  };

  const handleSaveUpdateStage = async (e) => {
    e.preventDefault();
    const payload = {
      title: stageForm.title,
      stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
      start_time: stageForm.start_time,
      end_time: stageForm.end_time,
      reveal_results: !!stageForm.reveal_results,
    };
    try {
      await run('updateStage', async () => {
        /** @type {Response} */
        const res = await api.fetch(
          `${API_BASE}/challenges/${stageChallengeId}/stages/${editingStage.id}`,
          {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
          },
        );
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}/stages/{stage_id}']['put']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_updated'));
          setEditingStage(null);
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_update_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_stage'), 'rose');
    }
  };

  const handleDeleteStage = async (challengeId, stageId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_stage_title'),
      message: t('admin.confirm.delete_stage_message', { title }),
    });
    if (!ok) return;
    try {
      await run('deleteStage', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges/${challengeId}/stages/${stageId}`, {
          method: 'DELETE',
          headers: {},
        });
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}/stages/{stage_id}']['delete']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_deleted', { title }));
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_delete_stage'), 'rose');
    }
  };

  const handleSaveFinalizeStage = async (e) => {
    e.preventDefault();
    const payload = {
      reveal_results: stageFinalizeForm.reveal_results,
    };
    try {
      await run('finalizeStage', async () => {
        /** @type {Response} */
        const res = await api.fetch(
          `${API_BASE}/challenges/${stageChallengeId}/stages/${finalizingStage.id}/finalize`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
          },
        );
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}/stages/{stage_id}/finalize']['post']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.stage_finalized'));
          setFinalizingStage(null);
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          showApiError(data, 'admin.notifications.stage_finalize_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_finalize_stage'), 'rose');
    }
  };

  // Set up task form edit / create
  const initCreateTask = (challengeId = null) => {
    const target = challengeId ? challenges.find((c) => c.id === challengeId) : selectedChallenge;
    if (!target) return;
    if (challengeId) setSelectedChallengeById(challengeId);
    setTaskForm({
      title: '',
      description: '',
      ram_limit_mb: '',
      time_limit_sec: '',
      gpu_required: true,
      base_docker_image: '',
      apt_packages: '',
      pip_requirements: '',
      ban_magic_commands: false,
      banned_imports: '',
      whitelisted_imports: '',
      metrics_config: '{"accuracy": {"weight": 1.0, "higher_is_better": true}}',
      hf_datasets_raw: '',
      hf_models_raw: '',
      hf_api_key: '',
      public_eval_percentage: 30,
      max_submissions_per_period: '',
      submission_period_hours: '',
      stage_id: '',
    });
    setTaskFiles([]);
    setBaselineFile(null);
    setEvaluatorScript(null);
    setEvaluatorDeleted(false);
    setIsCreatingTask(true);
  };

  const initEditTask = (task) => {
    setTaskForm({
      title: task.title || '',
      description: task.description || '',
      ram_limit_mb: task.ram_limit_mb !== null ? task.ram_limit_mb : '',
      time_limit_sec: task.time_limit_sec !== null ? task.time_limit_sec : '',
      gpu_required: task.gpu_required !== null ? task.gpu_required : true,
      base_docker_image: task.base_docker_image || '',
      apt_packages: task.apt_packages || '',
      pip_requirements: task.pip_requirements || '',
      ban_magic_commands: task.ban_magic_commands || false,
      banned_imports: task.banned_imports || '',
      whitelisted_imports: task.whitelisted_imports || '',
      metrics_config: task.metrics_config ? JSON.stringify(task.metrics_config) : '',
      hf_datasets_raw: task.hf_datasets
        ? Array.isArray(task.hf_datasets)
          ? task.hf_datasets.join(', ')
          : ''
        : '',
      hf_models_raw: task.hf_models
        ? Array.isArray(task.hf_models)
          ? task.hf_models.join(', ')
          : ''
        : '',
      hf_api_key: '', // Keep empty for input security
      public_eval_percentage: task.public_eval_percentage || 30,
      max_submissions_per_period:
        task.max_submissions_per_period !== null ? task.max_submissions_per_period : '',
      submission_period_hours:
        task.submission_period_hours !== null ? task.submission_period_hours : '',
      stage_id:
        task.stage_id !== null && task.stage_id !== undefined ? task.stage_id.toString() : '',
    });
    setEditingTask(task);
    setTaskFiles([]);
    setBaselineFile(null);
    setEvaluatorScript(null);
    setEvaluatorDeleted(false);
  };

  const validateTaskForm = () => {
    const errors = [];

    const DOCKER_IMAGE_RE =
      /^[a-z0-9]+(?:[._-][a-z0-9]+)*\/?[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[a-zA-Z0-9_.-]+)?$/;
    const APT_PACKAGE_RE = /^[a-zA-Z0-9.+-]+$/;
    const PIP_REQUIREMENT_RE =
      /^\s*([a-zA-Z0-9_.-]+)\s*(([><=!~]+)\s*[\w.*-]+(?:\s*,\s*[><=!~]+\s*[\w.*-]+)*)?\s*(#.*)?$/;

    if (taskForm.base_docker_image && !DOCKER_IMAGE_RE.test(taskForm.base_docker_image)) {
      errors.push('Invalid Docker image format.');
    }

    if (taskForm.apt_packages) {
      const packages = taskForm.apt_packages
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      const invalid = packages.filter((p) => !APT_PACKAGE_RE.test(p));
      if (invalid.length > 0) {
        errors.push(`Invalid APT package(s): ${invalid.join(', ')}`);
      }
    }

    if (taskForm.pip_requirements) {
      const lines = taskForm.pip_requirements
        .split('\n')
        .filter((l) => l.trim() && !l.trim().startsWith('#'));
      const invalid = lines.filter((l) => !PIP_REQUIREMENT_RE.test(l.trim()));
      if (invalid.length > 0) {
        errors.push(`Invalid pip requirement(s): ${invalid.join('; ')}`);
      }
    }

    if (taskForm.hf_datasets_raw) {
      const count = taskForm.hf_datasets_raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean).length;
      if (count > 5) {
        errors.push(`HF datasets: maximum 5 allowed, got ${count}.`);
      }
    }

    if (taskForm.hf_models_raw) {
      const count = taskForm.hf_models_raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean).length;
      if (count > 5) {
        errors.push(`HF models: maximum 5 allowed, got ${count}.`);
      }
    }

    return errors;
  };

  const prepareTaskFormData = () => {
    const formData = new FormData();
    formData.append('title', taskForm.title);
    formData.append('description', taskForm.description);

    if (taskForm.ram_limit_mb) formData.append('ram_limit_mb', taskForm.ram_limit_mb);
    if (taskForm.time_limit_sec) formData.append('time_limit_sec', String(taskForm.time_limit_sec));
    formData.append('gpu_required', String(taskForm.gpu_required));

    formData.append('base_docker_image', taskForm.base_docker_image);
    formData.append('apt_packages', taskForm.apt_packages);
    formData.append('pip_requirements', taskForm.pip_requirements);

    formData.append('ban_magic_commands', String(taskForm.ban_magic_commands));
    formData.append('banned_imports', taskForm.banned_imports);
    let cleanMetricsConfig = taskForm.metrics_config;
    try {
      const parsed = JSON.parse(taskForm.metrics_config);
      if (parsed && typeof parsed === 'object') {
        Object.keys(parsed).forEach((k) => {
          if (parsed[k] && parsed[k].options_raw !== undefined) {
            delete parsed[k].options_raw;
          }
        });
        cleanMetricsConfig = JSON.stringify(parsed);
      }
    } catch {
      /* noop */
    }
    formData.append('metrics_config', cleanMetricsConfig);

    if (taskForm.hf_api_key) formData.append('hf_api_key', taskForm.hf_api_key);
    formData.append('public_eval_percentage', String(taskForm.public_eval_percentage));

    formData.append('whitelisted_imports', taskForm.whitelisted_imports);
    const datasetsArray = taskForm.hf_datasets_raw
      ? taskForm.hf_datasets_raw
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
    formData.append('hf_datasets', JSON.stringify(datasetsArray));

    const modelsArray = taskForm.hf_models_raw
      ? taskForm.hf_models_raw
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
    formData.append('hf_models', JSON.stringify(modelsArray));

    if (taskForm.max_submissions_per_period)
      formData.append('max_submissions_per_period', taskForm.max_submissions_per_period);
    if (taskForm.submission_period_hours)
      formData.append('submission_period_hours', taskForm.submission_period_hours);
    if (taskForm.stage_id !== undefined && taskForm.stage_id !== null)
      formData.append('stage_id', taskForm.stage_id);

    // Regular task resource files (up to 5)
    taskFiles.forEach((file, idx) => {
      formData.append(`file_${idx}`, file);
    });

    // Special uploads
    if (baselineFile) formData.append('baseline_notebook', baselineFile);
    if (evaluatorScript) {
      formData.append('evaluator_script', evaluatorScript);
    } else if (evaluatorDeleted) {
      formData.append('delete_evaluator', 'true');
    }

    return formData;
  };

  // Submit Task Creation
  const handleSaveCreateTask = async (e) => {
    e.preventDefault();
    if (!selectedChallenge) return;

    const validationErrors = validateTaskForm();
    if (validationErrors.length > 0) {
      showToast(validationErrors.join('\n'), 'rose');
      return;
    }

    const hasLabels = taskFiles.some((f) => f.name === 'labels.parquet');
    if (!hasLabels) {
      showToast(t('admin.tasks.labels_parquet_required'), 'rose');
      return;
    }

    if (!baselineFile) {
      showToast(t('admin.tasks.baseline_required', 'Baseline notebook is required.'), 'rose');
      return;
    }

    const formData = prepareTaskFormData();

    try {
      await run('createTask', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/challenges/${selectedChallenge.id}/tasks`, {
          method: 'POST',
          headers: {},
          body: formData,
        });
        /** @type {import('../types/api').paths['/api/challenges/{challenge_id}/tasks']['post']['responses']['201']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.task_created'));
          fetchChallenges();
          fetchPaginatedChallenges();
          setIsCreatingTask(false);
        } else {
          showApiError(data, 'admin.notifications.task_create_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_create_task'), 'rose');
    }
  };

  // Submit Task Updates
  const handleSaveUpdateTask = async (e) => {
    e.preventDefault();
    if (!editingTask) return;

    const validationErrors = validateTaskForm();
    if (validationErrors.length > 0) {
      showToast(validationErrors.join('\n'), 'rose');
      return;
    }

    const deletedNames = editingTask.filesToDelete || [];
    const existingLabels = (() => {
      if (!editingTask.files) return false;
      const filesArr = Array.isArray(editingTask.files)
        ? editingTask.files
        : typeof editingTask.files === 'string' && editingTask.files.trim() !== ''
          ? JSON.parse(editingTask.files)
          : [];
      return filesArr.some(
        (f) => f.filename === 'labels.parquet' && !deletedNames.includes(f.filename),
      );
    })();
    const newLabels = taskFiles.some((f) => f.name === 'labels.parquet');
    if (!existingLabels && !newLabels) {
      showToast(t('admin.tasks.labels_parquet_required'), 'rose');
      return;
    }

    const hasBaseline =
      (editingTask.baseline_notebook_path && !editingTask.baselineDeleted) || baselineFile;
    if (!hasBaseline) {
      showToast(t('admin.tasks.baseline_required', 'Baseline notebook is required.'), 'rose');
      return;
    }

    const formData = prepareTaskFormData();
    if (deletedNames.length > 0) {
      formData.append('deleted_files', JSON.stringify(deletedNames));
    }
    if (editingTask.baselineDeleted && !baselineFile) {
      formData.append('delete_baseline', 'true');
    }

    try {
      await run('updateTask', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/tasks/${editingTask.id}`, {
          method: 'PUT',
          headers: {},
          body: formData,
        });
        /** @type {import('../types/api').paths['/api/tasks/{task_id}']['put']['responses']['200']['content']['application/json']} */
        const data = await res.json();
        if (res.ok) {
          showToast(t('admin.notifications.task_updated'));
          fetchChallenges();
          fetchPaginatedChallenges();
          setEditingTask(null);
        } else {
          showApiError(data, 'admin.notifications.task_update_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error_update_task'), 'rose');
    }
  };

  // Delete Task
  const handleDeleteTask = async (taskId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_task_title'),
      message: t('admin.confirm.delete_task_message', { title }),
    });
    if (!ok) return;
    try {
      await run('deleteTask', async () => {
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/tasks/${taskId}`, {
          method: 'DELETE',
          headers: {},
        });
        if (res.ok) {
          showToast(t('admin.notifications.task_deleted', { title }));
          if (editingTask?.id === taskId) {
            setEditingTask(null);
            setIsCreatingTask(false);
          }
          fetchChallenges();
          fetchPaginatedChallenges();
        } else {
          const data = await res.json();
          showApiError(data, 'admin.notifications.task_delete_failed');
        }
      });
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
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
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/admin/register-competitor`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(newCompetitor),
        });
        /** @type {import('../types/api').paths['/api/admin/register-competitor']['post']['responses']['201']['content']['application/json']} */
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

    // Hash password helper
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
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/admin/register-user`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        });
        /** @type {import('../types/api').paths['/api/admin/register-user']['post']['responses']['201']['content']['application/json']} */
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
        /** @type {Response} */
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
        /** @type {Response} */
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
          const competitors = data.competitors || [];
          setImportedCompetitors(competitors);
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

  // Backups — handled by BackupManager via API

  // Download Scores CSV
  const handleDownloadScores = async (challengeId, challengeTitle) => {
    try {
      await run('downloadScores', async () => {
        /** @type {Response} */
        const res = await api.fetch(
          `${API_BASE}/admin/challenges/${challengeId}/download-scores-csv`,
          {
            headers: {},
          },
        );
        if (!res.ok) {
          const errData = await res.json();
          showApiError(errData, 'admin.notifications.download_scores_failed');
          return;
        }
        const blob = await res.blob();
        const filename = `scores_${challengeTitle.replace(/\s+/g, '_')}.csv`;
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast(t('admin.notifications.scores_csv_downloaded'));
      });
    } catch {
      showToast(t('admin.notifications.download_scores_failed'), 'rose');
    }
  };

  // Download Submissions ZIP (supports optional stage filtering)
  const handleDownloadSubmissionsZip = async (
    challengeId,
    challengeTitle,
    stageId = null,
    stageTitle = null,
  ) => {
    try {
      await run('downloadSubmissionsZip', async () => {
        let url = `${API_BASE}/admin/challenges/${challengeId}/download-submissions-zip`;
        if (stageId) {
          url += `?stage_id=${stageId}`;
        }
        /** @type {Response} */
        const res = await api.fetch(url, {
          headers: {},
        });
        if (!res.ok) {
          const errData = await res.json();
          showApiError(errData, 'admin.notifications.download_submissions_failed');
          return;
        }
        const blob = await res.blob();

        let filename = `submissions_${challengeTitle.replace(/\s+/g, '_')}`;
        if (stageTitle) {
          filename += `_stage_${stageTitle.replace(/\s+/g, '_')}`;
        }
        filename += '.zip';

        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast(t('admin.notifications.submissions_zip_downloaded'));
      });
    } catch {
      showToast(t('admin.notifications.download_submissions_failed'), 'rose');
    }
  };

  const handleDownloadAuditLogs = async (challengeId, challengeTitle) => {
    try {
      await run('downloadAuditLogs', async () => {
        const res = await ChallengeService.downloadAuditLogs(challengeId);
        if (!res.ok) {
          showToast(
            t('admin.notifications.download_audits_failed', 'Download audit logs failed'),
            'rose',
          );
          return;
        }
        const blob = await res.blob();
        const filename = `audits_${challengeTitle.replace(/\s+/g, '_')}.json`;
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast(
          t('admin.notifications.audits_json_downloaded', 'Audit logs downloaded successfully'),
        );
      });
    } catch {
      showToast(
        t('admin.notifications.download_audits_failed', 'Download audit logs failed'),
        'rose',
      );
    }
  };

  const handleExportChallenge = async (challengeId, challengeTitle) => {
    try {
      await run('exportChallenge', async () => {
        const res = await api.fetch(`${API_BASE}/challenges/${challengeId}/export`, {
          headers: {},
        });
        if (!res.ok) {
          showToast('Failed to export challenge.', 'rose');
          return;
        }
        const blob = await res.blob();
        const filename = `challenge_${challengeTitle.replace(/\s+/g, '_')}.zip`;
        const link = document.createElement('a');
        link.href = window.URL.createObjectURL(blob);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast('Challenge exported.');
      });
    } catch {
      showToast('Failed to export challenge.', 'rose');
    }
  };

  const handleImportChallenge = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      await run('importChallenge', async () => {
        const res = await api.postForm(`/challenges/import`, formData);
        if (res.ok) {
          showToast('Challenge imported successfully.');
          fetchPaginatedChallenges();
        } else {
          showApiError(res.data, '', 'Failed to import challenge.');
        }
      });
    } catch {
      showToast('Failed to import challenge.', 'rose');
    }
    e.target.value = '';
  };

  // User editing
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
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/admin/users/${editingUser.id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
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
        /** @type {import('../types/api').paths['/api/admin/users/{user_id}']['put']['responses']['200']['content']['application/json']} */
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
        /** @type {Response} */
        const res = await api.fetch(`${API_BASE}/admin/users/${userId}/reset-password`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        });
        /** @type {import('../types/api').paths['/api/admin/users/{user_id}/reset-password']['post']['responses']['200']['content']['application/json']} */
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
        /** @type {Response} */
        const res = await api.fetch(
          `${API_BASE}/admin/challenges/${challenge.id}/reset-all-passwords`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
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
  const _filteredCompetitors = competitorsList; // eslint-disable-line no-unused-vars

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
          setIsCreatingStage={setIsCreatingStage}
          setEditingStage={setEditingStage}
          setFinalizingStage={setFinalizingStage}
        />

        {/* Main Workspace Work Areas */}
        <div className="lg:col-span-3">
          {/* 1. COMPETITION & TASK CONFIGURATION */}
          {adminSubTab === 'competition-mgmt' &&
            !isCreatingTask &&
            !editingTask &&
            !isCreatingStage &&
            !editingStage &&
            !finalizingStage &&
            !finalizingChallenge && (
              <div className="flex flex-col gap-6">
                {editingChallenge ? (
                  <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                    <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
                      <h2 className="text-xl font-bold text-white">
                        {t('admin.edit_competition', { title: editingChallenge.title })}
                      </h2>
                    </div>
                    <form
                      onSubmit={async (e) => {
                        e.preventDefault();
                        const res = await handleUpdateChallenge(
                          editingChallenge.id,
                          editingChallenge,
                        );
                        if (res.success) setEditingChallenge(null);
                      }}
                      className="flex flex-col gap-4"
                    >
                      <InputField
                        label={t('admin.competition_title')}
                        value={editingChallenge.title}
                        onChange={(e) =>
                          setEditingChallenge({ ...editingChallenge, title: e.target.value })
                        }
                        required
                      />
                      <InputField
                        multiline
                        label={t('admin.description')}
                        value={editingChallenge.description}
                        onChange={(e) =>
                          setEditingChallenge({ ...editingChallenge, description: e.target.value })
                        }
                        rows={4}
                      />
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <InputField
                          label={t('admin.daily_limits')}
                          type="number"
                          value={editingChallenge.max_eval_requests}
                          onChange={(e) =>
                            setEditingChallenge({
                              ...editingChallenge,
                              max_eval_requests: parseInt(e.target.value) || 0,
                            })
                          }
                        />
                        <InputField
                          label={t('admin.ram_limit_override')}
                          type="number"
                          value={editingChallenge.ram_limit_mb}
                          onChange={(e) =>
                            setEditingChallenge({
                              ...editingChallenge,
                              ram_limit_mb: parseInt(e.target.value) || 0,
                            })
                          }
                        />
                        <InputField
                          label={t('admin.time_limit_override')}
                          type="number"
                          value={editingChallenge.time_limit_sec}
                          onChange={(e) =>
                            setEditingChallenge({
                              ...editingChallenge,
                              time_limit_sec: parseInt(e.target.value) || 0,
                            })
                          }
                        />
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <InputField
                          label={t('admin.stages.start_time_label')}
                          type="datetime-local"
                          value={formatDateTimeLocal(editingChallenge.start_time)}
                          onChange={(e) =>
                            setEditingChallenge({ ...editingChallenge, start_time: e.target.value })
                          }
                          required
                        />
                        <InputField
                          label={t('admin.stages.end_time_label')}
                          type="datetime-local"
                          value={formatDateTimeLocal(editingChallenge.end_time)}
                          onChange={(e) =>
                            setEditingChallenge({ ...editingChallenge, end_time: e.target.value })
                          }
                          required
                        />
                        <SelectField
                          label={t('admin.timezone_choose')}
                          value={editingChallenge.timezone || 'UTC'}
                          onChange={(val) =>
                            setEditingChallenge({ ...editingChallenge, timezone: val })
                          }
                          options={TIMEZONES}
                          required
                        />
                      </div>
                      {(() => {
                        const existingTestStage = editingChallenge.stages?.find((s) => s.is_test);
                        return (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
                            <InputField
                              label={t('admin.test_stage_start')}
                              type="datetime-local"
                              value={
                                editingChallenge.test_stage_start_time !== undefined
                                  ? editingChallenge.test_stage_start_time
                                  : existingTestStage?.start_time
                                    ? existingTestStage.start_time.slice(0, 16)
                                    : ''
                              }
                              onChange={(e) =>
                                setEditingChallenge({
                                  ...editingChallenge,
                                  test_stage_start_time: e.target.value,
                                })
                              }
                            />
                            <InputField
                              label={t('admin.test_stage_end')}
                              type="datetime-local"
                              value={
                                editingChallenge.test_stage_end_time !== undefined
                                  ? editingChallenge.test_stage_end_time
                                  : existingTestStage?.end_time
                                    ? existingTestStage.end_time.slice(0, 16)
                                    : ''
                              }
                              onChange={(e) =>
                                setEditingChallenge({
                                  ...editingChallenge,
                                  test_stage_end_time: e.target.value,
                                })
                              }
                            />
                          </div>
                        );
                      })()}
                      <div className="flex flex-col gap-3 mt-2.5">
                        <ToggleField
                          label={t('admin.requires_gpu_sandbox')}
                          id="edit-gpu"
                          checked={editingChallenge.gpu_required}
                          onChange={(e) =>
                            setEditingChallenge({
                              ...editingChallenge,
                              gpu_required: e.target.checked,
                            })
                          }
                        />
                        <ToggleField
                          label={t('admin.double_blind_eval')}
                          id="edit-double-blind"
                          checked={editingChallenge.double_blind !== false}
                          onChange={(e) =>
                            setEditingChallenge({
                              ...editingChallenge,
                              double_blind: e.target.checked,
                            })
                          }
                        />
                        <ToggleField
                          label={t('admin.freeze_label')}
                          id="edit-is-frozen"
                          checked={editingChallenge.is_frozen || false}
                          onChange={(e) =>
                            setEditingChallenge({
                              ...editingChallenge,
                              is_frozen: e.target.checked,
                            })
                          }
                        />
                      </div>
                      <div className="flex gap-3 mt-4">
                        <Button type="submit" variant="primary">
                          {t('admin.stages.save_changes_btn')}
                        </Button>
                        <Button onClick={() => setEditingChallenge(null)} variant="secondary">
                          {t('common.cancel')}
                        </Button>
                      </div>
                    </form>
                  </div>
                ) : (
                  <div className="flex flex-col gap-6">
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <h1 className="text-xl font-bold text-white">
                        {t('admin.active_competitions')}
                      </h1>
                      <div className="flex gap-2">
                        <input
                          ref={importFileRef}
                          type="file"
                          accept=".json,.zip"
                          className="hidden"
                          onChange={handleImportChallenge}
                        />
                        <Button variant="secondary" onClick={() => importFileRef.current?.click()}>
                          {t('admin.import_challenge', 'Import Challenge')}
                        </Button>
                        <Button
                          variant="primary"
                          onClick={() => initCreateTask()}
                          disabled={!selectedChallenge}
                        >
                          <Plus size={16} />
                          {t('admin.add_task')}
                        </Button>
                      </div>
                    </div>

                    {paginatedChallengesList.length === 0 ? (
                      <p className="text-xs text-slate-500 italic">
                        {t('admin.no_competitions_created')}
                      </p>
                    ) : (
                      paginatedChallengesList.map((c) => (
                        <div
                          key={c.id}
                          className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col gap-4"
                        >
                          <div className="flex flex-wrap justify-between items-start gap-4">
                            <div>
                              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                                {c.title}
                                {(() => {
                                  const now = new Date();
                                  const start = c.start_time ? new Date(c.start_time) : null;
                                  const end = c.end_time ? new Date(c.end_time) : null;
                                  let compStatus;
                                  if (c.is_archived) {
                                    compStatus = 'archived';
                                  } else if (c.is_frozen) {
                                    compStatus = 'frozen';
                                  } else if (c.scores_finalized && c.reveal_results) {
                                    compStatus = 'public';
                                  } else if (c.scores_finalized && !c.reveal_results) {
                                    compStatus = 'internal';
                                  } else if (start && now < start) {
                                    compStatus = 'future';
                                  } else if (end && now > end) {
                                    compStatus = 'grading';
                                  } else {
                                    compStatus = 'active';
                                  }
                                  return <Badge status={compStatus} />;
                                })()}
                              </h2>
                              <p className="text-xs text-slate-400 mt-1">
                                {c.description || t('admin.no_description')}
                              </p>
                            </div>

                            <div className="flex flex-wrap gap-2">
                              {currentUser.role === 'admin' && (
                                <>
                                  <Button
                                    variant="secondary"
                                    onClick={() => setEditingChallenge(c)}
                                  >
                                    {t('admin.stages.edit')}
                                  </Button>
                                  <Button
                                    variant="secondary"
                                    onClick={() => handleArchiveToggle(c.id)}
                                    disabled={isLoading('archiveToggle')}
                                  >
                                    {c.is_archived ? t('admin.restore') : t('admin.archive')}
                                  </Button>
                                </>
                              )}

                              {c.scores_finalized && (
                                <Button
                                  variant="accent"
                                  onClick={() => handleDownloadScores(c.id, c.title)}
                                  disabled={isLoading('downloadScores')}
                                >
                                  {t('admin.download_csv_scores_short', 'Scores (CSV)')}
                                </Button>
                              )}

                              {(c.scores_finalized ||
                                (c.end_time ? new Date(c.end_time) <= new Date() : false)) && (
                                <Button
                                  variant="accent"
                                  onClick={() => handleDownloadSubmissionsZip(c.id, c.title)}
                                  disabled={isLoading('downloadSubmissionsZip')}
                                >
                                  {c.scores_finalized
                                    ? t('admin.download_submissions_zip_short', 'Submissions (ZIP)')
                                    : t(
                                        'admin.download_submissions_zip_short_blinded',
                                        'Submissions (ZIP) (Blinded)',
                                      )}
                                </Button>
                              )}

                              {c.scores_finalized && (
                                <>
                                  <Button
                                    variant="accent"
                                    onClick={() => handleDownloadAuditLogs(c.id, c.title)}
                                    disabled={isLoading('downloadAuditLogs')}
                                  >
                                    {t('admin.download_audits_json_short', 'Audits (JSON)')}
                                  </Button>
                                  {currentUser.role === 'jury' && (
                                    <Button
                                      variant="secondary"
                                      onClick={() =>
                                        handleToggleRevealChallenge(c.id, c.reveal_results)
                                      }
                                      disabled={isLoading('toggleRevealChallenge')}
                                    >
                                      {c.reveal_results
                                        ? t('admin.hide_results', 'Hide')
                                        : t('admin.reveal_results', 'Reveal')}
                                    </Button>
                                  )}
                                </>
                              )}
                              {!c.scores_finalized &&
                                currentUser.role === 'jury' &&
                                (c.end_time ? new Date(c.end_time) <= new Date() : false) && (
                                  <Button
                                    variant="accent"
                                    onClick={() => handleFinalizeSetup(c)}
                                    disabled={c.stages && c.stages.some((st) => !st.is_finalized)}
                                    title={
                                      c.stages && c.stages.some((st) => !st.is_finalized)
                                        ? t('leaderboard.finalize_disabled_tooltip')
                                        : ''
                                    }
                                  >
                                    {t('admin.finalize_short', 'Finalize')}
                                  </Button>
                                )}
                              <Button
                                variant="secondary"
                                onClick={() => handleExportChallenge(c.id, c.title)}
                                disabled={isLoading('exportChallenge')}
                              >
                                {t('admin.export_short', 'Export')}
                              </Button>
                              {currentUser.role === 'admin' && (
                                <Button
                                  variant="danger"
                                  onClick={() => handleDeleteChallenge(c.id, c.title)}
                                  disabled={isLoading('deleteChallenge')}
                                >
                                  {t('admin.stages.delete')}
                                </Button>
                              )}
                            </div>
                          </div>

                          <div className="border-t border-white/5 pt-4 mt-2">
                            <div className="flex justify-between items-center mb-3">
                              <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                                {t('admin.tasks_in_competition', {
                                  count: c.tasks ? c.tasks.length : 0,
                                })}
                              </h3>
                              <Button
                                variant="primary"
                                className="py-1 px-3 text-[10px]"
                                onClick={() => initCreateTask(c.id)}
                              >
                                <Plus size={14} />
                                {t('admin.add_task')}
                              </Button>
                            </div>
                            {c.tasks?.length === 0 ? (
                              <p className="text-xs text-slate-500 italic">
                                {t('admin.no_tasks_created')}
                              </p>
                            ) : (
                              <div className="flex flex-col gap-2">
                                {c.tasks?.map((task) => (
                                  <div
                                    key={task.id}
                                    className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs"
                                  >
                                    <div>
                                      <span className="font-bold text-slate-200">{task.title}</span>
                                      <span className="text-[10px] text-slate-500 ml-2">
                                        {t('admin.public_eval_split', {
                                          percentage: task.public_eval_percentage || 30,
                                        })}
                                      </span>
                                    </div>
                                    <div className="flex gap-2">
                                      <Button
                                        variant="secondary"
                                        onClick={() => initEditTask(task)}
                                      >
                                        {t('admin.edit_config')}
                                      </Button>
                                      <Button
                                        variant="danger"
                                        onClick={() => handleDeleteTask(task.id, task.title)}
                                        disabled={isLoading('deleteTask')}
                                      >
                                        {t('admin.stages.delete')}
                                      </Button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>

                          <div className="border-t border-white/5 pt-4 mt-2">
                            <div className="flex justify-between items-center mb-3">
                              <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                                {t('admin.stages.stages_in_competition', {
                                  count: c.stages ? c.stages.length : 0,
                                })}
                              </h3>
                              <Button
                                variant="primary"
                                className="py-1 px-3 text-[10px]"
                                onClick={() => initCreateStage(c.id)}
                              >
                                <Plus size={14} />
                                {t('admin.stages.add_stage')}
                              </Button>
                            </div>
                            {c.stages?.length === 0 ? (
                              <p className="text-xs text-slate-500 italic">
                                {t('admin.stages.no_stages')}
                              </p>
                            ) : (
                              <div className="flex flex-col gap-2">
                                {c.stages?.map((st) => (
                                  <div
                                    key={st.id}
                                    className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs"
                                  >
                                    <div className="flex items-center flex-wrap gap-x-2 gap-y-1">
                                      <span className="font-bold text-slate-200">
                                        {t('admin.stages.stage_label', {
                                          number: st.stage_number,
                                          title: st.title,
                                        })}
                                      </span>
                                      <span className="text-[10px] text-indigo-400">
                                        {formatDateTime(st.start_time, c.timezone)} {t('common.to')}{' '}
                                        {formatDateTime(st.end_time, c.timezone)}
                                      </span>
                                      {(() => {
                                        const now = new Date();
                                        const start = new Date(st.start_time);
                                        const end = new Date(st.end_time);
                                        let stageStatus;
                                        if (st.is_finalized && st.reveal_results) {
                                          stageStatus = 'public';
                                        } else if (st.is_finalized && !st.reveal_results) {
                                          stageStatus = 'internal';
                                        } else if (now < start) {
                                          stageStatus = 'future';
                                        } else if (now > end) {
                                          stageStatus = 'grading';
                                        } else {
                                          stageStatus = 'active';
                                        }
                                        return <Badge status={stageStatus} />;
                                      })()}
                                    </div>
                                    <div className="flex gap-2">
                                      <Button
                                        variant="secondary"
                                        className="py-1 px-2.5"
                                        onClick={() => initEditStage(c.id, st)}
                                      >
                                        {t('admin.stages.edit')}
                                      </Button>
                                      {!st.is_finalized &&
                                        currentUser.role === 'jury' &&
                                        (st.end_time
                                          ? new Date(st.end_time) <= new Date()
                                          : false) && (
                                          <Button
                                            variant="accent"
                                            className="py-1 px-2.5"
                                            onClick={() => initFinalizeStage(c.id, st)}
                                          >
                                            {t('admin.stages.finalize')}
                                          </Button>
                                        )}
                                      {st.is_finalized && currentUser.role === 'jury' && (
                                        <Button
                                          variant="secondary"
                                          className="py-1 px-2.5"
                                          onClick={() =>
                                            handleToggleRevealStage(c.id, st.id, st.reveal_results)
                                          }
                                          disabled={isLoading('toggleRevealStage')}
                                        >
                                          {st.reveal_results
                                            ? t('admin.hide_results', 'Hide')
                                            : t('admin.reveal_results', 'Reveal')}
                                        </Button>
                                      )}

                                      {(c.scores_finalized ||
                                        st.is_finalized ||
                                        (st.end_time
                                          ? new Date(st.end_time) <= new Date()
                                          : false)) && (
                                        <Button
                                          variant="accent"
                                          className="py-1 px-2.5"
                                          onClick={() =>
                                            handleDownloadSubmissionsZip(
                                              c.id,
                                              c.title,
                                              st.id,
                                              st.title,
                                            )
                                          }
                                          disabled={isLoading('downloadSubmissionsZip')}
                                        >
                                          {c.scores_finalized
                                            ? t('admin.download_submissions_stage', 'Download')
                                            : t(
                                                'admin.download_submissions_stage_blinded',
                                                'Download (Blinded)',
                                              )}
                                        </Button>
                                      )}
                                      <Button
                                        variant="danger"
                                        className="py-1 px-2.5"
                                        onClick={() => handleDeleteStage(c.id, st.id, st.title)}
                                        disabled={isLoading('deleteStage')}
                                      >
                                        {t('admin.stages.delete')}
                                      </Button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      ))
                    )}

                    <Pagination
                      page={challengesPage}
                      pages={challengesPages}
                      total={challengesTotal}
                      perPage={5}
                      onPageChange={setChallengesPage}
                      itemName={t('admin.competitions_pagination_item')}
                    />
                  </div>
                )}
              </div>
            )}

          {/* Stage Create/Edit Form */}
          {adminSubTab === 'competition-mgmt' && (isCreatingStage || editingStage) && (
            <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
              <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
                <h2 className="text-xl font-bold text-white">
                  {isCreatingStage
                    ? t('admin.stages.create_stage_modal_title')
                    : t('admin.stages.edit_stage_modal_title', { title: editingStage?.title })}
                </h2>
              </div>

              <form
                onSubmit={isCreatingStage ? handleSaveCreateStage : handleSaveUpdateStage}
                className="flex flex-col gap-4"
              >
                <InputField
                  label={t('admin.stages.stage_title_label')}
                  value={stageForm.title}
                  onChange={(e) => setStageForm({ ...stageForm, title: e.target.value })}
                  required
                />
                <InputField
                  label={t('admin.stages.stage_number_optional')}
                  type="number"
                  value={stageForm.stage_number}
                  onChange={(e) => setStageForm({ ...stageForm, stage_number: e.target.value })}
                  placeholder={t('admin.stages.edit_stage_number_placeholder')}
                />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <InputField
                    label={t('admin.stages.start_time_label')}
                    type="datetime-local"
                    value={stageForm.start_time}
                    onChange={(e) => setStageForm({ ...stageForm, start_time: e.target.value })}
                    required
                  />
                  <InputField
                    label={t('admin.stages.end_time_label')}
                    type="datetime-local"
                    value={stageForm.end_time}
                    onChange={(e) => setStageForm({ ...stageForm, end_time: e.target.value })}
                    required
                  />
                </div>

                <div className="flex gap-3 mt-4">
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={isLoading('createStage') || isLoading('updateStage')}
                  >
                    {isCreatingStage
                      ? t('admin.stages.create_stage_btn')
                      : t('admin.stages.save_changes_btn')}
                  </Button>
                  <Button
                    onClick={() => {
                      setIsCreatingStage(false);
                      setEditingStage(null);
                    }}
                    variant="secondary"
                  >
                    {t('common.cancel')}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {/* Stage Finalize Form */}
          {adminSubTab === 'competition-mgmt' && finalizingStage && (
            <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
              <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
                <h2 className="text-xl font-bold text-white">
                  {t('admin.stages.finalize_stage_modal_title', { title: finalizingStage.title })}
                </h2>
              </div>

              <form onSubmit={handleSaveFinalizeStage} className="flex flex-col gap-6">
                <div className="flex flex-col gap-3 p-4 bg-slate-900/40 border border-white/5 rounded-xl">
                  <ToggleField
                    label={t(
                      'admin.stages.reveal_results_and_points_desc',
                      'Разкриване на резултатите и точките за състезателите (в противен случай завършването е само вътрешно за журито)',
                    )}
                    id="stage-reveal-results-and-points"
                    checked={stageFinalizeForm.reveal_results}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      setStageFinalizeForm({
                        reveal_results: checked,
                      });
                    }}
                  />
                </div>

                <div className="flex gap-3 mt-4">
                  <Button type="submit" variant="primary" disabled={isLoading('finalizeStage')}>
                    {t('admin.stages.finalize_stage_btn')}
                  </Button>
                  <Button onClick={() => setFinalizingStage(null)} variant="secondary">
                    {t('common.cancel')}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {/* Challenge Finalize Form */}
          {adminSubTab === 'competition-mgmt' && finalizingChallenge && (
            <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
              <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
                <h2 className="text-xl font-bold text-white">
                  {t('admin.finalize_competition_title', { title: finalizingChallenge.title })}
                </h2>
              </div>

              <form onSubmit={handleSaveFinalizeChallenge} className="flex flex-col gap-6">
                <div className="flex flex-col gap-3 p-4 bg-slate-900/40 border border-white/5 rounded-xl">
                  <ToggleField
                    label={t(
                      'admin.reveal_results_label',
                      'Reveal private scores and competitor identities immediately',
                    )}
                    id="challenge-reveal-results"
                    checked={challengeFinalizeForm.reveal_results}
                    onChange={(e) =>
                      setChallengeFinalizeForm({
                        ...challengeFinalizeForm,
                        reveal_results: e.target.checked,
                      })
                    }
                  />
                </div>

                <div className="flex gap-3 mt-4">
                  <Button type="submit" variant="primary" disabled={isLoading('finalizeChallenge')}>
                    {t('admin.finalize_short', 'Finalize')}
                  </Button>
                  <Button onClick={() => setFinalizingChallenge(null)} variant="secondary">
                    {t('common.cancel')}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {/* 2. TASK EDITING OR CREATION (The Sandbox + HF + Rules form) */}
          {adminSubTab === 'competition-mgmt' && (isCreatingTask || editingTask) && (
            <TaskForm
              taskForm={taskForm}
              setTaskForm={setTaskForm}
              isCreatingTask={isCreatingTask}
              editingTask={editingTask}
              setEditingTask={setEditingTask}
              setIsCreatingTask={setIsCreatingTask}
              handleSaveCreateTask={handleSaveCreateTask}
              handleSaveUpdateTask={handleSaveUpdateTask}
              challenges={challenges}
              selectedChallenge={selectedChallenge}
              availableMetrics={availableMetrics}
              formatMetricName={formatMetricName}
              taskFiles={taskFiles}
              setTaskFiles={setTaskFiles}
              baselineFile={baselineFile}
              setBaselineFile={setBaselineFile}
              formatDateTime={formatDateTime}
              savingTask={savingTask}
              evaluatorScript={evaluatorScript}
              setEvaluatorScript={setEvaluatorScript}
              evaluatorDeleted={evaluatorDeleted}
              setEvaluatorDeleted={setEvaluatorDeleted}
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
              csvImporting={csvImporting}
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
              generatedUserCredentials={generatedUserCredentials}
              allUsers={filteredUsers}
              userSearch={userSearch}
              setUserSearch={setUserSearch}
              handleDeleteUser={handleDeleteUser}
              usersPage={usersPage}
              usersPages={usersPages}
              usersTotal={usersTotal}
              setUsersPage={setUsersPage}
              challenges={challenges}
              currentUser={currentUser}
              initEditUser={initEditUser}
              isRegisteringUser={isLoading('registerUser')}
              isDeletingUser={isLoading('deleteUser')}
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

          {/* 8. AUDIT LOGS */}
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

      {/* Edit User Account Modal */}
      {editingUser &&
        adminSubTab === 'user-management' &&
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
                    {t('admin.user_mgmt.edit_user_account', 'Edit User Account')}
                  </h2>
                  <p className="text-slate-400 text-xs">
                    {t(
                      'admin.user_mgmt.edit_user_account_desc',
                      'Update user details, role, and assigned competitions.',
                    )}
                  </p>
                </div>

                {/* Form Body (Scrollable) */}
                <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
                  <InputField
                    label={t('admin.user_mgmt.username_label')}
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
                  />
                  <InputField
                    label={t('admin.user_mgmt.password_optional_label', 'New Password (Optional)')}
                    type="password"
                    value={editUserForm.password || ''}
                    onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })}
                    placeholder={t(
                      'admin.user_mgmt.password_optional_placeholder',
                      'Leave blank to keep current',
                    )}
                  />
                  <div
                    className={`grid ${editUserForm.role === 'competitor' ? 'grid-cols-3' : 'grid-cols-2'} gap-4`}
                  >
                    <InputField
                      label={t('admin.competitor_reg.first_name')}
                      value={editUserForm.name}
                      onChange={(e) => setEditUserForm({ ...editUserForm, name: e.target.value })}
                      required
                    />
                    {editUserForm.role === 'competitor' && (
                      <InputField
                        label={t('admin.competitor_reg.middle_name')}
                        value={editUserForm.middle_name || ''}
                        onChange={(e) =>
                          setEditUserForm({ ...editUserForm, middle_name: e.target.value })
                        }
                        required
                      />
                    )}
                    <InputField
                      label={t('admin.competitor_reg.last_name')}
                      value={editUserForm.surname}
                      onChange={(e) =>
                        setEditUserForm({ ...editUserForm, surname: e.target.value })
                      }
                      required
                    />
                  </div>

                  <SelectField
                    label={t('admin.user_mgmt.role_label')}
                    value={editUserForm.role}
                    onChange={(val) => setEditUserForm({ ...editUserForm, role: val })}
                    required
                    options={[
                      { value: 'competitor', label: t('admin.user_mgmt.role_competitor') },
                      { value: 'jury', label: t('admin.user_mgmt.role_jury') },
                    ]}
                  />

                  {editUserForm.role === 'competitor' && (
                    <>
                      <div className="grid grid-cols-1 gap-4 mb-2">
                        <InputField
                          label={t('admin.competitor_reg.birth_date')}
                          type="date"
                          value={editUserForm.birth_date || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, birth_date: e.target.value })
                          }
                          required
                        />
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <InputField
                          label={t('admin.competitor_reg.grade')}
                          value={editUserForm.grade || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, grade: e.target.value })
                          }
                          required
                        />
                        <InputField
                          label={t('admin.competitor_reg.school')}
                          value={editUserForm.school || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, school: e.target.value })
                          }
                          required
                        />
                        <InputField
                          label={t('admin.competitor_reg.city')}
                          value={editUserForm.city || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, city: e.target.value })
                          }
                          required
                        />
                      </div>
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
                          id="edit-user-is-anonymous"
                          checked={editUserForm.is_anonymous}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, is_anonymous: e.target.checked })
                          }
                        />
                      </div>
                    </>
                  )}

                  {editUserForm.role === 'jury' && (
                    <SelectField
                      label={t('admin.user_mgmt.assign_jury_competitions', 'Assign Competitions')}
                      multiple
                      searchable
                      value={editUserForm.jury_challenges || []}
                      onChange={(vals) =>
                        setEditUserForm({ ...editUserForm, jury_challenges: vals })
                      }
                      options={challenges.map((c) => ({ value: c.id.toString(), label: c.title }))}
                      placeholder={t(
                        'admin.user_mgmt.no_competitions_assigned',
                        'No competitions assigned',
                      )}
                    />
                  )}
                </div>

                {/* Footer */}
                <div className="p-6 border-t border-white/5 flex justify-end gap-3 flex-shrink-0">
                  <Button type="button" variant="secondary" onClick={() => setEditingUser(null)}>
                    {t('common.cancel', 'Cancel')}
                  </Button>
                  <Button type="submit" variant="primary" disabled={isLoading('updateUser')}>
                    {t('common.save', 'Save')}
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
