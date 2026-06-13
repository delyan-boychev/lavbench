import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import InputField from '../components/ui/InputField';
import Button from '../components/ui/Button';
import SelectField from '../components/ui/SelectField';
import Pagination from '../components/ui/Pagination';
import CodeHighlight from '../components/ui/CodeHighlight';
import ToggleField from '../components/ui/ToggleField';

const getTimezones = () => {
  let zones = [];
  try {
    zones = Intl.supportedValuesOf('timeZone');
  } catch (e) {
    zones = [
      'UTC',
      'Europe/Sofia',
      'Europe/London',
      'Europe/Paris',
      'Europe/Berlin',
      'Europe/Athens',
      'Europe/Bucharest',
      'Europe/Rome',
      'Europe/Madrid',
      'Europe/Dublin',
      'America/New_York',
      'America/Chicago',
      'America/Denver',
      'America/Los_Angeles',
      'America/Toronto',
      'America/Mexico_City',
      'America/Sao_Paulo',
      'Asia/Tokyo',
      'Asia/Shanghai',
      'Asia/Singapore',
      'Asia/Kolkata',
      'Asia/Dubai',
      'Australia/Sydney',
      'Australia/Melbourne',
      'Africa/Cairo',
      'Africa/Johannesburg',
      'Pacific/Auckland'
    ];
  }
  // Remove underscores from labels
  return zones.map(zone => ({
    value: zone,
    label: zone.replace(/_/g, ' ')
  }));
};

const TIMEZONES = getTimezones();

const CUSTOM_EVALUATOR_TEMPLATE = `import os
import json
import traceback
import time

# 1. SECURE IMPORT
# The student's notebook cells are saved as 'submission_runner.py'
try:
    import submission_runner
except Exception as e:
    # Safely catch import errors without leaking sandbox state
    with open("eval_results.json", "w") as f:
        json.dump({"status": "error", "error": "Failed to compile or import student code."}, f)
    exit(1)

def run_evaluation():
    try:
        # 2. RUN STUDENT LOGIC
        # Execute the student's entry point (e.g., predict, generate, or a full pipeline)
        # Assuming the Jury requested a function named 'run_pipeline':
        if not hasattr(submission_runner, 'run_pipeline'):
            raise AttributeError("Your notebook must define the requested entry point function.")
            
        student_func = submission_runner.run_pipeline

        start_time = time.time()
        
        # Pass whatever data the Jury deems necessary
        # The student code can handle training, prediction, etc. internally.
        public_score, private_score = student_func() 
        
        execution_time_ms = int((time.time() - start_time) * 1000)

        # 3. WRITE SECURE RESULTS (Do not print to stdout)
        results = {
            "status": "success",
            "public_score": float(public_score),
            "private_score": float(private_score),
            "execution_time_ms": execution_time_ms,
            "metrics_payload_public": {"score": public_score},
            "metrics_payload_private": {"score": private_score}
        }
        
        with open("eval_results.json", "w") as f:
            json.dump(results, f)
            
    except Exception as e:
        # 4. PREVENT DATA LEAKAGE
        # Do NOT write traceback.format_exc() to prevent leaking private dataset values
        # that might be captured in exception variables.
        error_type = type(e).__name__
        with open("eval_results.json", "w") as f:
            json.dump({"status": "error", "error": f"Evaluation failed with {error_type}"}, f)

if __name__ == "__main__":
    run_evaluation()`;


export default function AdminPanel() {
  const { t } = useTranslation();
  const { token, currentUser } = useAuth();
  const { 
    challenges, 
    selectedChallenge, 
    setSelectedChallengeById, 
    fetchChallenges, 
    showToast,
    confirm
  } = useApp();

  const API_BASE = '/api';



  // Sub tab navigation
  const [adminSubTab, setAdminSubTab] = useState('competition-mgmt');

  const formatDateTimeLocal = (dateStr) => {
    if (!dateStr) return '';
    return dateStr.substring(0, 16);
  };

  const formatDateTime = (dateStr, timezone = 'UTC') => {
    if (!dateStr) return '—';
    try {
      const d = new Date(dateStr);
      const formatter = new Intl.DateTimeFormat('sv-SE', {
        timeZone: timezone || 'UTC',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      });
      const parts = formatter.formatToParts(d);
      const getPart = (type) => parts.find(p => p.type === type)?.value || '';
      const tzLabel = (timezone || 'UTC').replace(/_/g, ' ');
      return `${getPart('year')}-${getPart('month')}-${getPart('day')} ${getPart('hour')}:${getPart('minute')} (${tzLabel})`;
    } catch (err) {
      const d = new Date(dateStr);
      const pad = (n) => n.toString().padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())} ${t('challenge.local_timezone')}`;
    }
  };

  const isChallengeStarted = (challengeId) => {
    if (!challengeId) return false;
    const challenge = challenges.find(c => c.id.toString() === challengeId.toString());
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
    timezone: 'UTC'
  });

  // Edit Challenge State
  const [editingChallenge, setEditingChallenge] = useState(null);

  // Task Form State
  const [editingTask, setEditingTask] = useState(null); // Task object or null
  const [isCreatingTask, setIsCreatingTask] = useState(false); // boolean
  const [taskForm, setTaskForm] = useState({
    title: '',
    description: '',
    ram_limit_mb: '',
    time_limit_sec: '',
    gpu_required: true,
    base_docker_image: '',
    apt_packages: '',
    pip_requirements: '',
    require_submit_tag: false,
    ban_magic_commands: false,
    banned_imports: '',
    metrics_config: '',
    hf_train_repo: '',
    hf_eval_repo: '',
    hf_api_key: '',
    public_eval_percentage: 30,
    max_submissions_per_period: '',
    submission_period_hours: '',
    stage_id: ''
  });

  // Task Upload Files
  const [taskFiles, setTaskFiles] = useState([]);
  const [evaluatorFile, setEvaluatorFile] = useState(null);
  const [baselineFile, setBaselineFile] = useState(null);
  const [solutionFile, setSolutionFile] = useState(null);

  // Stage CRUD & Finalization State
  const [isCreatingStage, setIsCreatingStage] = useState(false);
  const [editingStage, setEditingStage] = useState(null);
  const [stageChallengeId, setStageChallengeId] = useState(null);
  const [stageForm, setStageForm] = useState({
    title: '',
    stage_number: '',
    start_time: '',
    end_time: ''
  });

  const [finalizingStage, setFinalizingStage] = useState(null);
  const [stageFinalizeForm, setStageFinalizeForm] = useState({
    finalize_type: 'visible',
    reveal_public: true,
    reveal_private: false,
    reveal_points: false
  });

  // Manual Competitor Register State
  const [newCompetitor, setNewCompetitor] = useState({
    name: '',
    surname: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false
  });
  const [generatedCredentials, setGeneratedCredentials] = useState(null);
  const [resetCredentials, setResetCredentials] = useState(null);
  const [bulkResetCredentials, setBulkResetCredentials] = useState([]);

  // User Management State
  const [allUsers, setAllUsers] = useState([]);
  const [userSearch, setUserSearch] = useState('');
  const [newUser, setNewUser] = useState({
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
    is_anonymous: false
  });
  const [generatedUserCredentials, setGeneratedUserCredentials] = useState(null);

  // User Editing State
  const [editingUser, setEditingUser] = useState(null);
  const [editUserForm, setEditUserForm] = useState({
    username: '',
    email: '',
    password: '',
    name: '',
    surname: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false
  });

  // CSV Import State
  const [csvFile, setCsvFile] = useState(null);
  const [csvImporting, setCsvImporting] = useState(false);
  const [csvChallengeId, setCsvChallengeId] = useState('');
  const [importedCompetitors, setImportedCompetitors] = useState([]);

  // Competitor Listing
  const [competitorsList, setCompetitorsList] = useState([]);
  const [competitorSearch, setCompetitorSearch] = useState('');
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

  // Fetch Worker & Resource Stats
  const fetchWorkerStats = async () => {
    setWorkerStatsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/workers/stats`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setWorkerStats(data);
        setWorkerStatsError(null);
      } else {
        const errData = await res.json().catch(() => ({}));
        setWorkerStatsError(errData.error || `Failed to fetch stats (Status: ${res.status})`);
      }
    } catch (e) {
      console.error(e);
      setWorkerStatsError(e.message || 'Network error fetching stats');
    } finally {
      setWorkerStatsLoading(false);
    }
  };

  // Fetch Users
  const fetchUsers = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/users?page=${usersPage}&per_page=10&search=${userSearch}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setAllUsers(data.items || []);
        setUsersTotal(data.total || 0);
        setUsersPages(data.pages || 1);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Fetch Competitors (based on user lists or submissions)
  const fetchCompetitors = async () => {
    if (!selectedChallenge) return;
    try {
      const res = await fetch(`${API_BASE}/admin/users?page=${competitorsPage}&per_page=10&role=competitor&challenge_id=${selectedChallenge.id}&search=${competitorSearch}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setCompetitorsList(data.items || []);
        setCompetitorsTotal(data.total || 0);
        setCompetitorsPages(data.pages || 1);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Fetch Paginated Challenges (Competitions)
  const fetchPaginatedChallenges = async () => {
    try {
      const res = await fetch(`${API_BASE}/challenges?page=${challengesPage}&per_page=5`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        if (data.items) {
          setPaginatedChallengesList(data.items);
          setChallengesTotal(data.total);
          setChallengesPages(data.pages);
        } else {
          setPaginatedChallengesList(data || []);
          setChallengesTotal(data?.length || 0);
          setChallengesPages(1);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (adminSubTab === 'user-management') {
      fetchUsers();
    }
  }, [adminSubTab, usersPage, userSearch]);

  useEffect(() => {
    if (adminSubTab === 'competitor-reg' || adminSubTab === 'competition-mgmt') {
      fetchCompetitors();
    }
  }, [adminSubTab, selectedChallenge, competitorsPage, competitorSearch]);

  useEffect(() => {
    if (adminSubTab === 'competition-mgmt') {
      fetchPaginatedChallenges();
    }
  }, [adminSubTab, challengesPage]);

  useEffect(() => {
    if (adminSubTab === 'workers-stats') {
      fetchWorkerStats();
      const interval = setInterval(fetchWorkerStats, 5000);
      return () => clearInterval(interval);
    }
  }, [adminSubTab]);

  useEffect(() => {
    setUsersPage(1);
  }, [userSearch]);

  useEffect(() => {
    setCompetitorsPage(1);
  }, [competitorSearch]);

  // Handle Competition creation
  const handleCreateChallenge = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/challenges`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(newChallenge)
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
          gpu_required: true,
          start_time: '',
          end_time: '',
          is_frozen: false,
          double_blind: true,
          timezone: 'UTC'
        });
        fetchChallenges();
        fetchPaginatedChallenges();
        setAdminSubTab('competition-mgmt');
      } else {
        showToast(data.error || t('admin.notifications.competition_create_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_create_competition'), 'rose');
    }
  };

  // Handle Competition update
  const handleUpdateChallenge = async (id, updated) => {
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(updated)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.competition_updated'));
        fetchChallenges();
        fetchPaginatedChallenges();
        return { success: true };
      } else {
        showToast(data.error || t('admin.notifications.competition_update_failed'), 'rose');
        return { success: false };
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_update_competition'), 'rose');
      return { success: false };
    }
  };

  // Handle Competition delete
  const handleDeleteChallenge = async (id, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_competition_title'),
      message: t('admin.confirm.delete_competition_message', { title })
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.competition_deleted', { title }));
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.competition_delete_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_delete_competition'), 'rose');
    }
  };

  // Handle finalize scores
  const handleFinalize = async (id) => {
    const ok = await confirm({
      title: t('admin.confirm.finalize_scores_title'),
      message: t('admin.confirm.finalize_scores_message')
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}/finalize`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.scores_finalized'));
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.scores_finalize_failed'), "rose");
      }
    } catch (e) {
      showToast(t('admin.notifications.network_error_finalize_scores'), "rose");
    }
  };

  // Handle archive toggle
  const handleArchiveToggle = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}/archive`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message || t('admin.notifications.archive_toggle_success'));
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.archive_failed'), "rose");
      }
    } catch (e) {
      showToast(t('admin.notifications.network_error'), "rose");
    }
  };

  // Handle scheduled test competition creation
  const handleCreateTestCompetition = async (id) => {
    const ok = await confirm({
      title: t('admin.confirm.schedule_test_title'),
      message: t('admin.confirm.schedule_test_message')
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}/test-competition`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.test_competition_scheduled'));
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.test_competition_schedule_failed'), "rose");
      }
    } catch (e) {
      showToast(t('admin.notifications.network_error_schedule_test'), "rose");
    }
  };

  // Stage management helpers
  const initCreateStage = (challengeId) => {
    setStageChallengeId(challengeId);
    setStageForm({
      title: '',
      stage_number: '',
      start_time: '',
      end_time: ''
    });
    setIsCreatingStage(true);
  };

  const initEditStage = (challengeId, stage) => {
    setStageChallengeId(challengeId);
    setEditingStage(stage);
    setStageForm({
      title: stage.title || '',
      stage_number: stage.stage_number !== null && stage.stage_number !== undefined ? stage.stage_number.toString() : '',
      start_time: formatDateTimeLocal(stage.start_time),
      end_time: formatDateTimeLocal(stage.end_time)
    });
  };

  const initFinalizeStage = (challengeId, stage) => {
    setStageChallengeId(challengeId);
    setFinalizingStage(stage);
    setStageFinalizeForm({
      finalize_type: 'visible',
      reveal_public: true,
      reveal_private: false,
      reveal_points: false
    });
  };

  const handleSaveCreateStage = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        title: stageForm.title,
        stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
        start_time: stageForm.start_time,
        end_time: stageForm.end_time
      };
      const res = await fetch(`${API_BASE}/challenges/${stageChallengeId}/stages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.stage_created'));
        setIsCreatingStage(false);
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.stage_create_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_create_stage'), 'rose');
    }
  };

  const handleSaveUpdateStage = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        title: stageForm.title,
        stage_number: stageForm.stage_number ? parseInt(stageForm.stage_number) : null,
        start_time: stageForm.start_time,
        end_time: stageForm.end_time
      };
      const res = await fetch(`${API_BASE}/challenges/${stageChallengeId}/stages/${editingStage.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.stage_updated'));
        setEditingStage(null);
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.stage_update_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_update_stage'), 'rose');
    }
  };

  const handleDeleteStage = async (challengeId, stageId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_stage_title'),
      message: t('admin.confirm.delete_stage_message', { title })
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/challenges/${challengeId}/stages/${stageId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.stage_deleted', { title }));
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.stage_delete_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_delete_stage'), 'rose');
    }
  };

  const handleSaveFinalizeStage = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        finalize_type: stageFinalizeForm.finalize_type,
        reveal_public: stageFinalizeForm.reveal_public,
        reveal_private: stageFinalizeForm.reveal_private,
        reveal_points: stageFinalizeForm.reveal_points
      };
      const res = await fetch(`${API_BASE}/challenges/${stageChallengeId}/stages/${finalizingStage.id}/finalize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.stage_finalized'));
        setFinalizingStage(null);
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || t('admin.notifications.stage_finalize_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_finalize_stage'), 'rose');
    }
  };

  // Set up task form edit / create
  const initCreateTask = () => {
    setTaskForm({
      title: '',
      description: '',
      ram_limit_mb: '',
      time_limit_sec: '',
      gpu_required: true,
      base_docker_image: '',
      apt_packages: '',
      pip_requirements: '',
      require_submit_tag: false,
      ban_magic_commands: false,
      banned_imports: '',
      metrics_config: '{"accuracy": {"weight": 1.0, "higher_is_better": true}}',
      hf_train_repo: '',
      hf_eval_repo: '',
      hf_api_key: '',
      public_eval_percentage: 30,
      max_submissions_per_period: '',
      submission_period_hours: '',
      stage_id: ''
    });
    setTaskFiles([]);
    setEvaluatorFile(null);
    setBaselineFile(null);
    setSolutionFile(null);
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
      require_submit_tag: task.require_submit_tag || false,
      ban_magic_commands: task.ban_magic_commands || false,
      banned_imports: task.banned_imports || '',
      metrics_config: task.metrics_config ? JSON.stringify(task.metrics_config) : '',
      hf_train_repo: task.hf_train_repo || '',
      hf_eval_repo: task.hf_eval_repo || '',
      hf_api_key: '', // Keep empty for input security
      public_eval_percentage: task.public_eval_percentage || 30,
      max_submissions_per_period: task.max_submissions_per_period !== null ? task.max_submissions_per_period : '',
      submission_period_hours: task.submission_period_hours !== null ? task.submission_period_hours : '',
      stage_id: task.stage_id !== null && task.stage_id !== undefined ? task.stage_id.toString() : ''
    });
    setEditingTask(task);
    setTaskFiles([]);
    setEvaluatorFile(null);
    setBaselineFile(null);
    setSolutionFile(null);
  };

  const prepareTaskFormData = () => {
    const formData = new FormData();
    formData.append("title", taskForm.title);
    formData.append("description", taskForm.description);
    
    if (taskForm.ram_limit_mb) formData.append("ram_limit_mb", taskForm.ram_limit_mb);
    if (taskForm.time_limit_sec) formData.append("time_limit_sec", taskForm.time_limit_sec);
    formData.append("gpu_required", taskForm.gpu_required);
    
    formData.append("base_docker_image", taskForm.base_docker_image);
    formData.append("apt_packages", taskForm.apt_packages);
    formData.append("pip_requirements", taskForm.pip_requirements);
    
    formData.append("require_submit_tag", taskForm.require_submit_tag);
    formData.append("ban_magic_commands", taskForm.ban_magic_commands);
    formData.append("banned_imports", taskForm.banned_imports);
    formData.append("metrics_config", taskForm.metrics_config);
    
    formData.append("hf_train_repo", taskForm.hf_train_repo);
    formData.append("hf_eval_repo", taskForm.hf_eval_repo);
    if (taskForm.hf_api_key) formData.append("hf_api_key", taskForm.hf_api_key);
    formData.append("public_eval_percentage", taskForm.public_eval_percentage);
    
    if (taskForm.max_submissions_per_period) formData.append("max_submissions_per_period", taskForm.max_submissions_per_period);
    if (taskForm.submission_period_hours) formData.append("submission_period_hours", taskForm.submission_period_hours);
    if (taskForm.stage_id !== undefined && taskForm.stage_id !== null) formData.append("stage_id", taskForm.stage_id);

    // Regular task resource files (up to 5)
    taskFiles.forEach((file, idx) => {
      formData.append(`file_${idx}`, file);
    });

    // Special uploads
    if (evaluatorFile) formData.append("evaluator_script", evaluatorFile, "evaluator.py");
    if (baselineFile) formData.append("baseline_notebook", baselineFile);
    if (solutionFile) formData.append("solution_notebook", solutionFile);

    return formData;
  };

  // Submit Task Creation
  const handleSaveCreateTask = async (e) => {
    e.preventDefault();
    if (!selectedChallenge) return;
    const formData = prepareTaskFormData();

    try {
      const res = await fetch(`${API_BASE}/challenges/${selectedChallenge.id}/tasks`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.task_created'));
        fetchChallenges();
        setIsCreatingTask(false);
      } else {
        showToast(data.error || t('admin.notifications.task_create_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_create_task'), 'rose');
    }
  };

  // Submit Task Updates
  const handleSaveUpdateTask = async (e) => {
    e.preventDefault();
    if (!editingTask) return;
    const formData = prepareTaskFormData();

    // Handle file deletions if selected
    const deletedNames = editingTask.filesToDelete || [];
    if (deletedNames.length > 0) {
      formData.append("deleted_files", JSON.stringify(deletedNames));
    }

    try {
      const res = await fetch(`${API_BASE}/tasks/${editingTask.id}`, {
        method: 'PUT',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.task_updated'));
        fetchChallenges();
        setEditingTask(null);
      } else {
        showToast(data.error || t('admin.notifications.task_update_failed'), 'rose');
      }
    } catch (err) {
      showToast(t('admin.notifications.network_error_update_task'), 'rose');
    }
  };

  // Delete Task
  const handleDeleteTask = async (taskId, title) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_task_title'),
      message: t('admin.confirm.delete_task_message', { title })
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        showToast(t('admin.notifications.task_deleted', { title }));
        fetchChallenges();
      } else {
        const data = await res.json();
        showToast(data.error || t('admin.notifications.task_delete_failed'), 'rose');
      }
    } catch (e) {
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
      const res = await fetch(`${API_BASE}/admin/register-competitor`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(newCompetitor)
      });
      const data = await res.json();
      if (res.ok) {
        setGeneratedCredentials({
          username: data.generated_username,
          password: data.generated_password,
          name: newCompetitor.name,
          surname: newCompetitor.surname
        });
        setNewCompetitor({ name: '', surname: '', grade: '', school: '', city: '', challenge_id: '', is_anonymous: false });
        showToast(t('admin.notifications.competitor_registered'));
        fetchCompetitors();
      } else {
        showToast(data.error || t('admin.notifications.competitor_register_failed'), 'rose');
      }
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
    setGeneratedUserCredentials(null);

    // Hash password helper
    const hashPassword = async (p) => {
      const msgBuffer = new TextEncoder().encode(p);
      const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
      return Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
    };

    try {
      const requestBody = { ...newUser };
      if (newUser.password) {
        requestBody.password = await hashPassword(newUser.password);
      }
      const res = await fetch(`${API_BASE}/admin/register-user`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(requestBody)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.user_registered'));
        setGeneratedUserCredentials({
          username: data.generated_username,
          password: data.generated_password,
          role: newUser.role,
          name: newUser.name,
          surname: newUser.surname
        });
        setNewUser({
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
          is_anonymous: false
        });
        fetchUsers();
      } else {
        showToast(data.error || t('admin.notifications.user_register_failed'), 'rose');
      }
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    }
  };

  // Delete User
  const handleDeleteUser = async (userId, username) => {
    const ok = await confirm({
      title: t('admin.confirm.delete_user_title'),
      message: t('admin.confirm.delete_user_message', { username })
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/admin/users/${userId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        showToast(t('admin.notifications.user_deleted', { username }));
        fetchUsers();
      } else {
        const data = await res.json();
        showToast(data.error || t('admin.notifications.user_delete_failed'), 'rose');
      }
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
    setCsvImporting(true);
    setImportedCompetitors([]);

    const fd = new FormData();
    fd.append('file', csvFile);
    fd.append('challenge_id', csvChallengeId);

    try {
      const res = await fetch(`${API_BASE}/admin/import-competitors-csv`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: fd
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.imported_competitors_success', { count: data.competitors?.length || 0 }));
        setImportedCompetitors(data.competitors || []);
        setCsvFile(null);
        fetchCompetitors();
      } else {
        showToast(data.error || t('admin.notifications.import_csv_failed'), 'rose');
      }
    } catch {
      showToast(t('admin.notifications.network_error'), 'rose');
    } finally {
      setCsvImporting(false);
    }
  };

  // Backups
  const handleDownloadBackup = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/backup`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) {
        const errData = await res.json();
        showToast(errData.error || t('admin.notifications.backup_failed'), 'rose');
        return;
      }
      const blob = await res.blob();
      const filename = `backup_nai_db_${new Date().toISOString().slice(0,19).replace(/[:-]/g,"")}.sql`;
      const link = document.createElement('a');
      link.href = window.URL.createObjectURL(blob);
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      showToast(t('admin.notifications.backup_success'));
    } catch {
      showToast(t('admin.notifications.backup_failed'), 'rose');
    }
  };

  // Download Scores CSV
  const handleDownloadScores = async (challengeId, challengeTitle) => {
    try {
      const res = await fetch(`${API_BASE}/admin/challenges/${challengeId}/download-scores-csv`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) {
        const errData = await res.json();
        showToast(errData.error || t('admin.notifications.download_scores_failed'), 'rose');
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
    } catch {
      showToast(t('admin.notifications.download_scores_failed'), 'rose');
    }
  };

  // Download Submissions ZIP
  const handleDownloadSubmissionsZip = async (challengeId, challengeTitle) => {
    try {
      const res = await fetch(`${API_BASE}/admin/challenges/${challengeId}/download-submissions-zip`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) {
        const errData = await res.json();
        showToast(errData.error || t('admin.notifications.download_submissions_failed'), 'rose');
        return;
      }
      const blob = await res.blob();
      const filename = `submissions_${challengeTitle.replace(/\s+/g, '_')}.zip`;
      const link = document.createElement('a');
      link.href = window.URL.createObjectURL(blob);
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      showToast(t('admin.notifications.submissions_zip_downloaded'));
    } catch {
      showToast(t('admin.notifications.download_submissions_failed'), 'rose');
    }
  };

  // User editing
  const initEditUser = (user) => {
    setEditingUser(user);
    setEditUserForm({
      username: user.username || '',
      email: user.email || '',
      password: '',
      name: user.name || '',
      surname: user.surname || '',
      grade: user.grade || '',
      school: user.school || '',
      city: user.city || '',
      challenge_id: user.challenge_id ? user.challenge_id.toString() : '',
      is_anonymous: user.is_anonymous || false
    });
  };

  const handleUpdateUserSubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/admin/users/${editingUser.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          username: editUserForm.username,
          email: editUserForm.email || null,
          password: editUserForm.password || null,
          name: editUserForm.name,
          surname: editUserForm.surname,
          grade: editUserForm.grade || null,
          school: editUserForm.school || null,
          city: editUserForm.city || null,
          challenge_id: editUserForm.challenge_id === "" ? "" : parseInt(editUserForm.challenge_id),
          is_anonymous: editUserForm.is_anonymous
        })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.competitor_updated'));
        setEditingUser(null);
        fetchUsers();
        fetchCompetitors();
      } else {
        showToast(data.error || t('admin.notifications.competitor_update_failed'), 'rose');
      }
    } catch {
      showToast(t('admin.notifications.network_error_update_competitor'), 'rose');
    }
  };

  const handleResetUserPassword = async (userId, displayName) => {
    const ok = await confirm({
      title: t('admin.confirm.reset_password_title'),
      message: t('admin.confirm.reset_password_message', { displayName })
    });
    if (!ok) return;
    try {
      const res = await fetch(`${API_BASE}/admin/users/${userId}/reset-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.password_reset_success'));
        setResetCredentials({ username: data.username, password: data.password });
        setBulkResetCredentials([]);
      } else {
        showToast(data.error || t('admin.notifications.password_reset_failed'), 'rose');
      }
    } catch {
      showToast(t('admin.notifications.network_error_reset_password'), 'rose');
    }
  };

  const handleBulkResetPasswords = async () => {
    const activeChallenges = challenges.filter(c => currentUser.role === 'admin' || !isChallengeStarted(c.id));
    if (activeChallenges.length === 0) {
      showToast(t('admin.notifications.no_eligible_competitions'), 'rose');
      return;
    }
    
    const optionsStr = activeChallenges.map(c => `ID ${c.id}: ${c.title}`).join('\n');
    const input = await confirm({
      title: t('admin.confirm.bulk_reset_title'),
      message: t('admin.confirm.bulk_reset_message', { optionsStr }),
      isPrompt: true,
      placeholder: t('admin.confirm.bulk_reset_placeholder')
    });
    if (input === null) return;
    
    const selectedId = input.trim();
    const challenge = activeChallenges.find(c => c.id.toString() === selectedId);
    if (!challenge) {
      showToast(t('admin.notifications.invalid_competition_id'), 'rose');
      return;
    }
    
    const ok = await confirm({
      title: t('admin.confirm.confirm_bulk_reset_title'),
      message: t('admin.confirm.confirm_bulk_reset_message', { title: challenge.title })
    });
    if (!ok) return;
    
    try {
      const res = await fetch(`${API_BASE}/admin/challenges/${challenge.id}/reset-all-passwords`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('admin.notifications.bulk_reset_success', { count: data.reset_accounts?.length }));
        setBulkResetCredentials(data.reset_accounts || []);
        setResetCredentials(null);
      } else {
        showToast(data.error || t('admin.notifications.bulk_reset_failed'), 'rose');
      }
    } catch {
      showToast(t('admin.notifications.network_error_bulk_reset'), 'rose');
    }
  };

  const filteredUsers = allUsers;
  const fontFilteredCompetitors = competitorsList; // keep simple naming
  const filteredCompetitors = competitorsList;

  const isManualRegisterDisabled = currentUser.role === 'jury' && isChallengeStarted(newCompetitor.challenge_id);
  const isCSVImportDisabled = currentUser.role === 'jury' && isChallengeStarted(csvChallengeId);
  const isEditDisabled = currentUser.role === 'jury' && isChallengeStarted(editUserForm.challenge_id);

  // Render components
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start animate-fadein">
      
      {/* Sidebar Control Submenu */}
      <div className="bg-[#0d0e18] border border-white/5 p-5 rounded-2xl flex flex-col gap-1.5">
        <h2 className="text-xs font-extrabold uppercase text-slate-400 tracking-wider mb-3 px-2">{t('admin.jury_control_hub')}</h2>
        
        {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <button 
            onClick={() => { setAdminSubTab('competition-mgmt'); setIsCreatingTask(false); setEditingTask(null); }}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'competition-mgmt' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            {t('admin.manage_competitions')}
          </button>
        )}

        {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <button 
            onClick={() => setAdminSubTab('challenge-config')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'challenge-config' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            {t('admin.create_competition')}
          </button>
        )}
        
        <button 
          onClick={() => setAdminSubTab('competitor-reg')}
          className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'competitor-reg' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {t('admin.competitor_registrations')}
        </button>

        {currentUser.role === 'admin' && (
          <button 
            onClick={() => setAdminSubTab('backups')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'backups' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            {t('admin.database_backup')}
          </button>
        )}

        {currentUser.role === 'admin' && (
          <button 
            onClick={() => setAdminSubTab('user-management')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'user-management' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            {t('admin.user_management')}
          </button>
        )}

        {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <button 
            onClick={() => setAdminSubTab('workers-stats')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'workers-stats' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            {t('admin.workers_resources')}
          </button>
        )}
      </div>

      {/* Main Workspace Work Areas */}
      <div className="lg:col-span-3">

        {/* 1. COMPETITION & TASK CONFIGURATION */}
        {adminSubTab === 'competition-mgmt' && !isCreatingTask && !editingTask && !isCreatingStage && !editingStage && !finalizingStage && (
          <div className="flex flex-col gap-6">
            
            {editingChallenge ? (
              <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
                  <h2 className="text-xl font-bold text-white">{t('admin.edit_competition', { title: editingChallenge.title })}</h2>
                </div>
                <form 
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const res = await handleUpdateChallenge(editingChallenge.id, editingChallenge);
                    if (res.success) setEditingChallenge(null);
                  }}
                  className="flex flex-col gap-4"
                >
                  <InputField 
                    label={t('admin.competition_title')} 
                    value={editingChallenge.title} 
                    onChange={(e) => setEditingChallenge({ ...editingChallenge, title: e.target.value })} 
                    required 
                  />
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-slate-300">{t('admin.description')}</label>
                    <textarea 
                      rows="4" 
                      className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-sm font-sans"
                      value={editingChallenge.description} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, description: e.target.value })} 
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <InputField 
                      label={t('admin.daily_limits')} 
                      type="number"
                      value={editingChallenge.max_eval_requests} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, max_eval_requests: parseInt(e.target.value) })} 
                      required 
                    />
                    <InputField 
                      label={t('admin.ram_limit_override')} 
                      type="number"
                      value={editingChallenge.ram_limit_mb} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, ram_limit_mb: parseInt(e.target.value) })} 
                      required 
                    />
                    <InputField 
                      label={t('admin.time_limit_override')} 
                      type="number"
                      value={editingChallenge.time_limit_sec} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, time_limit_sec: parseInt(e.target.value) })} 
                      required 
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <InputField 
                      label={t('admin.stages.start_time_label')} 
                      type="datetime-local"
                      value={formatDateTimeLocal(editingChallenge.start_time)} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, start_time: e.target.value })} 
                      required
                    />
                    <InputField 
                      label={t('admin.stages.end_time_label')} 
                      type="datetime-local"
                      value={formatDateTimeLocal(editingChallenge.end_time)} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, end_time: e.target.value })} 
                      required
                    />
                    <SelectField
                      label={t('admin.timezone_choose')}
                      value={editingChallenge.timezone || 'UTC'}
                      onChange={(val) => setEditingChallenge({ ...editingChallenge, timezone: val })}
                      options={TIMEZONES}
                      required
                    />
                  </div>
                  <div className="flex flex-col gap-3 mt-2.5">
                    <ToggleField 
                      label={t('admin.requires_gpu_sandbox')}
                      id="edit-gpu"
                      checked={editingChallenge.gpu_required}
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, gpu_required: e.target.checked })}
                    />
                    <ToggleField 
                      label={t('admin.double_blind_eval')}
                      id="edit-double-blind"
                      checked={editingChallenge.double_blind !== false}
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, double_blind: e.target.checked })}
                    />
                    <ToggleField 
                      label={t('admin.freeze_label')}
                      id="edit-is-frozen"
                      checked={editingChallenge.is_frozen || false}
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, is_frozen: e.target.checked })}
                    />
                  </div>
                  <div className="flex gap-3 mt-4">
                    <Button type="submit" variant="primary">{t('admin.stages.save_changes_btn')}</Button>
                    <Button onClick={() => setEditingChallenge(null)} variant="secondary">{t('common.cancel')}</Button>
                  </div>
                </form>
              </div>
            ) : (
              <div className="flex flex-col gap-6">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h1 className="text-xl font-bold text-white">{t('admin.active_competitions')}</h1>
                  <Button variant="primary" onClick={initCreateTask}>{t('admin.add_task')}</Button>
                </div>
                
                {paginatedChallengesList.length === 0 ? (
                  <p className="text-xs text-slate-500 italic">{t('admin.no_competitions_created')}</p>
                ) : (
                  paginatedChallengesList.map(c => (
                    <div key={c.id} className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col gap-4">
                      <div className="flex flex-wrap justify-between items-start gap-4">
                        <div>
                          <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            {c.title}
                            {c.is_archived && <span className="text-[10px] bg-slate-800 border border-white/5 text-slate-400 px-2 py-0.5 rounded-full font-bold">{t('admin.archived')}</span>}
                          </h2>
                          <p className="text-xs text-slate-400 mt-1">{c.description || t('admin.no_description')}</p>
                        </div>
                        
                        <div className="flex flex-wrap gap-2">
                          <Button variant="secondary" onClick={() => setEditingChallenge(c)}>{t('admin.stages.edit')}</Button>
                          <Button 
                            variant="secondary" 
                            onClick={() => handleArchiveToggle(c.id)}
                          >
                            {c.is_archived ? t('admin.restore') : t('admin.archive')}
                          </Button>
                          {!c.title.startsWith("Test:") && (
                            <Button 
                              variant="secondary" 
                              onClick={() => handleCreateTestCompetition(c.id)}
                            >
                              {t('admin.schedule_test')}
                            </Button>
                          )}
                          {c.scores_finalized && (
                            <>
                              <span className="text-[10px] font-bold border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 px-2.5 py-1.5 rounded-lg flex items-center">{t('leaderboard.finalized')}</span>
                              <Button variant="accent" onClick={() => handleDownloadScores(c.id, c.title)}>
                                {t('admin.download_csv_scores')}
                              </Button>
                              <Button variant="accent" onClick={() => handleDownloadSubmissionsZip(c.id, c.title)}>
                                {t('admin.download_submissions_zip')}
                              </Button>
                            </>
                          )}
                          {!c.scores_finalized && currentUser.role === 'jury' && (
                            <Button 
                              variant="accent" 
                              onClick={() => handleFinalize(c.id)}
                              disabled={c.stages && c.stages.some(st => !st.is_finalized)}
                              title={c.stages && c.stages.some(st => !st.is_finalized) ? t('leaderboard.finalize_disabled_tooltip') : ""}
                            >
                              {t('admin.finalize_challenge')}
                            </Button>
                          )}
                          <Button variant="danger" onClick={() => handleDeleteChallenge(c.id, c.title)}>{t('admin.stages.delete')}</Button>
                        </div>
                      </div>

                      <div className="border-t border-white/5 pt-4 mt-2">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">{t('admin.tasks_in_competition', { count: c.tasks ? c.tasks.length : 0 })}</h3>
                        {c.tasks?.length === 0 ? (
                          <p className="text-xs text-slate-500 italic">{t('admin.no_tasks_created')}</p>
                        ) : (
                          <div className="flex flex-col gap-2">
                            {c.tasks?.map(task => (
                              <div key={task.id} className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs">
                                <div>
                                  <span className="font-bold text-slate-200">{task.title}</span>
                                  <span className="text-[10px] text-slate-500 ml-2">{t('admin.public_eval_split', { percentage: task.public_eval_percentage || 30 })}</span>
                                </div>
                                <div className="flex gap-2">
                                  <Button variant="secondary" onClick={() => initEditTask(task)}>{t('admin.edit_config')}</Button>
                                  <Button variant="danger" onClick={() => handleDeleteTask(task.id, task.title)}>{t('admin.stages.delete')}</Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      <div className="border-t border-white/5 pt-4 mt-2">
                        <div className="flex justify-between items-center mb-3">
                          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('admin.stages.stages_in_competition', { count: c.stages ? c.stages.length : 0 })}</h3>
                          <Button variant="primary" className="py-1 px-3 text-[10px]" onClick={() => initCreateStage(c.id)}>{t('admin.stages.add_stage')}</Button>
                        </div>
                        {c.stages?.length === 0 ? (
                          <p className="text-xs text-slate-500 italic">{t('admin.stages.no_stages')}</p>
                        ) : (
                          <div className="flex flex-col gap-2">
                            {c.stages?.map(st => (
                              <div key={st.id} className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs">
                                <div>
                                  <span className="font-bold text-slate-200">{t('admin.stages.stage_label', { number: st.stage_number, title: st.title })}</span>
                                  <span className="text-[10px] text-indigo-400 ml-3">
                                    {formatDateTime(st.start_time, c.timezone)} {t('common.to')} {formatDateTime(st.end_time, c.timezone)}
                                  </span>
                                  {st.is_finalized && (
                                    <span className={`text-[9px] font-bold ml-2 px-1.5 py-0.5 rounded border ${st.finalize_type === 'internal' ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'}`}>
                                      {t('admin.stages.finalized_type', { type: st.finalize_type })}
                                    </span>
                                  )}
                                </div>
                                <div className="flex gap-2">
                                  <Button variant="secondary" className="py-1 px-2.5" onClick={() => initEditStage(c.id, st)}>{t('admin.stages.edit')}</Button>
                                  {!st.is_finalized && (
                                    <Button variant="accent" className="py-1 px-2.5" onClick={() => initFinalizeStage(c.id, st)}>{t('admin.stages.finalize')}</Button>
                                  )}
                                  <Button variant="danger" className="py-1 px-2.5" onClick={() => handleDeleteStage(c.id, st.id, st.title)}>{t('admin.stages.delete')}</Button>
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
                  itemName="competitions"
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
                {isCreatingStage ? t('admin.stages.create_stage_modal_title') : t('admin.stages.edit_stage_modal_title', { title: editingStage?.title })}
              </h2>
            </div>
            
            <form onSubmit={isCreatingStage ? handleSaveCreateStage : handleSaveUpdateStage} className="flex flex-col gap-4">
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
                <Button type="submit" variant="primary">{isCreatingStage ? t('admin.stages.create_stage_btn') : t('admin.stages.save_changes_btn')}</Button>
                <Button onClick={() => { setIsCreatingStage(false); setEditingStage(null); }} variant="secondary">{t('common.cancel')}</Button>
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
              <div className="flex flex-col gap-2">
                <label className="text-xs font-semibold text-slate-300">{t('admin.stages.finalize_type_label')}</label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-slate-200 text-sm cursor-pointer">
                    <input 
                      type="radio" 
                      name="finalize_type" 
                      value="visible" 
                      checked={stageFinalizeForm.finalize_type === 'visible'}
                      onChange={() => setStageFinalizeForm({ ...stageFinalizeForm, finalize_type: 'visible' })}
                    />
                    {t('admin.stages.finalize_type_visible')}
                  </label>
                  <label className="flex items-center gap-2 text-slate-200 text-sm cursor-pointer">
                    <input 
                      type="radio" 
                      name="finalize_type" 
                      value="internal" 
                      checked={stageFinalizeForm.finalize_type === 'internal'}
                      onChange={() => setStageFinalizeForm({ ...stageFinalizeForm, finalize_type: 'internal' })}
                    />
                    {t('admin.stages.finalize_type_internal')}
                  </label>
                </div>
              </div>

              {stageFinalizeForm.finalize_type === 'visible' && (
                <div className="flex flex-col gap-3 p-4 bg-slate-900/40 border border-white/5 rounded-xl">
                  <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-1">{t('admin.stages.visibility_rules_students')}</h4>
                  <ToggleField 
                    label={t('admin.stages.reveal_public_split')}
                    id="stage-reveal-public"
                    checked={stageFinalizeForm.reveal_public}
                    onChange={(e) => setStageFinalizeForm({ ...stageFinalizeForm, reveal_public: e.target.checked })}
                  />
                  <ToggleField 
                    label={t('admin.stages.reveal_private_split')}
                    id="stage-reveal-private"
                    checked={stageFinalizeForm.reveal_private}
                    onChange={(e) => setStageFinalizeForm({ ...stageFinalizeForm, reveal_private: e.target.checked })}
                  />
                  <ToggleField 
                    label={t('admin.stages.reveal_total_points')}
                    id="stage-reveal-points"
                    checked={stageFinalizeForm.reveal_points}
                    onChange={(e) => setStageFinalizeForm({ ...stageFinalizeForm, reveal_points: e.target.checked })}
                  />
                </div>
              )}

              <div className="flex gap-3 mt-4">
                <Button type="submit" variant="primary">{t('admin.stages.finalize_stage_btn')}</Button>
                <Button onClick={() => setFinalizingStage(null)} variant="secondary">{t('common.cancel')}</Button>
              </div>
            </form>
          </div>
        )}

        {/* 2. TASK EDITING OR CREATION (The Sandbox + HF + Rules form) */}
        {(isCreatingTask || editingTask) && (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
            <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
              <h2 className="text-xl font-bold text-white">
                {isCreatingTask ? t('admin.tasks.create_task_under', { title: selectedChallenge?.title }) : t('admin.tasks.edit_task', { title: editingTask?.title })}
              </h2>
            </div>
            
            <form onSubmit={isCreatingTask ? handleSaveCreateTask : handleSaveUpdateTask} className="flex flex-col gap-6">
              
              {/* Section A: General */}
              <div>
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.general_settings')}</h3>
                <div className="flex flex-col gap-4">
                  <InputField 
                    label={t('admin.tasks.task_title')} 
                    value={taskForm.title} 
                    onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} 
                    required 
                  />
                  <SelectField
                    label={t('admin.tasks.stage_optional')}
                    value={taskForm.stage_id}
                    onChange={(val) => setTaskForm({ ...taskForm, stage_id: val })}
                    options={[
                      { value: "", label: t('admin.tasks.stage_none') },
                      ...(challenges.find(c => c.id === (editingTask ? editingTask.challenge_id : selectedChallenge?.id))?.stages || []).map(st => {
                        const challenge = challenges.find(c => c.id === (editingTask ? editingTask.challenge_id : selectedChallenge?.id));
                        return {
                          value: st.id.toString(),
                          label: t('admin.tasks.stage_option_label', { number: st.stage_number, title: st.title, start: formatDateTime(st.start_time, challenge?.timezone), end: formatDateTime(st.end_time, challenge?.timezone) })
                        };
                      })
                    ]}
                  />
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-slate-300">{t('admin.tasks.description_markdown')}</label>
                    <textarea 
                      rows="4" 
                      className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-sm font-sans"
                      value={taskForm.description} 
                      onChange={(e) => setTaskForm({ ...taskForm, description: e.target.value })} 
                      required
                    />
                  </div>
                </div>
              </div>

              {/* Section B: Sandbox overrides */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.sandbox_overrides')}</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <InputField 
                    label={t('admin.tasks.override_ram')} 
                    type="number" 
                    value={taskForm.ram_limit_mb} 
                    onChange={(e) => setTaskForm({ ...taskForm, ram_limit_mb: e.target.value })} 
                    placeholder="8192"
                  />
                  <InputField 
                    label={t('admin.tasks.override_timeout')} 
                    type="number" 
                    value={taskForm.time_limit_sec} 
                    onChange={(e) => setTaskForm({ ...taskForm, time_limit_sec: e.target.value })} 
                    placeholder="300"
                  />
                  <div className="flex items-center gap-2 h-full pt-6">
                    <ToggleField 
                      label={t('admin.tasks.requires_gpu_worker_node')}
                      id="task-gpu-req"
                      checked={taskForm.gpu_required}
                      onChange={(e) => setTaskForm({ ...taskForm, gpu_required: e.target.checked })}
                    />
                  </div>
                </div>
              </div>

              {/* Section C: Docker Environment */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.docker_config')}</h3>
                <div className="flex flex-col gap-4">
                  <InputField 
                    label={t('admin.tasks.base_image')} 
                    value={taskForm.base_docker_image} 
                    onChange={(e) => setTaskForm({ ...taskForm, base_docker_image: e.target.value })} 
                    placeholder={t('admin.tasks.base_image_placeholder')}
                  />
                  <InputField 
                    label={t('admin.tasks.apt_packages')} 
                    value={taskForm.apt_packages} 
                    onChange={(e) => setTaskForm({ ...taskForm, apt_packages: e.target.value })} 
                    placeholder={t('admin.tasks.apt_packages_placeholder')}
                  />
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-slate-300">{t('admin.tasks.pip_requirements')}</label>
                    <textarea 
                      rows="3" 
                      className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-xs font-mono"
                      value={taskForm.pip_requirements} 
                      onChange={(e) => setTaskForm({ ...taskForm, pip_requirements: e.target.value })} 
                      placeholder={t('admin.tasks.pip_requirements_placeholder')}
                    />
                  </div>
                </div>
              </div>

              {/* Section D: Rules engine */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.ast_rules')}</h3>
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap gap-6">
                    <ToggleField 
                      label={t('admin.tasks.require_submit_comment')}
                      id="rule-tag"
                      checked={taskForm.require_submit_tag}
                      onChange={(e) => setTaskForm({ ...taskForm, require_submit_tag: e.target.checked })}
                    />
                    <ToggleField 
                      label={t('admin.tasks.ban_magic_commands')}
                      id="rule-magic"
                      checked={taskForm.ban_magic_commands}
                      onChange={(e) => setTaskForm({ ...taskForm, ban_magic_commands: e.target.checked })}
                    />
                  </div>
                  <InputField 
                    label={t('admin.tasks.banned_libraries')} 
                    value={taskForm.banned_imports} 
                    onChange={(e) => setTaskForm({ ...taskForm, banned_imports: e.target.value })} 
                    placeholder={t('admin.tasks.banned_libraries_placeholder')}
                  />
                </div>
              </div>

              {/* Section E: Data Integration (Hugging Face) */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.hf_dataset_metrics')}</h3>
                <div className="flex flex-col gap-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <InputField 
                      label={t('admin.tasks.public_train_dataset')} 
                      value={taskForm.hf_train_repo} 
                      onChange={(e) => setTaskForm({ ...taskForm, hf_train_repo: e.target.value })} 
                      placeholder={t('admin.tasks.public_train_dataset_placeholder')}
                    />
                    <InputField 
                      label={t('admin.tasks.private_eval_dataset')} 
                      value={taskForm.hf_eval_repo} 
                      onChange={(e) => setTaskForm({ ...taskForm, hf_eval_repo: e.target.value })} 
                      placeholder={t('admin.tasks.private_eval_dataset_placeholder')}
                    />
                  </div>
                  <InputField 
                    label={t('admin.tasks.hf_api_key')} 
                    type="password"
                    value={taskForm.hf_api_key} 
                    onChange={(e) => setTaskForm({ ...taskForm, hf_api_key: e.target.value })} 
                    placeholder={t('admin.tasks.hf_api_key_placeholder')}
                  />
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-semibold text-slate-300">
                      {t('admin.tasks.public_eval_split_percentage', { percentage: taskForm.public_eval_percentage })}
                    </label>
                    <input 
                      type="range" 
                      min="0" 
                      max="100" 
                      value={taskForm.public_eval_percentage} 
                      onChange={(e) => setTaskForm({ ...taskForm, public_eval_percentage: parseInt(e.target.value) })}
                      className="w-full accent-indigo-600 h-1.5 bg-slate-900 rounded-lg cursor-pointer border border-white/5"
                    />
                  </div>
                  <InputField 
                    label={t('admin.tasks.metrics_config_json')} 
                    value={taskForm.metrics_config} 
                    onChange={(e) => setTaskForm({ ...taskForm, metrics_config: e.target.value })} 
                    placeholder='{"accuracy": {"weight": 1.0, "higher_is_better": true}}'
                  />
                </div>
              </div>

              {/* Section F: Optional Rate Limits */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.optional_rate_limits')}</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <InputField 
                    label={t('admin.tasks.max_submissions')} 
                    type="number"
                    value={taskForm.max_submissions_per_period} 
                    onChange={(e) => setTaskForm({ ...taskForm, max_submissions_per_period: e.target.value })} 
                    placeholder={t('admin.tasks.max_submissions_placeholder')}
                  />
                  <InputField 
                    label={t('admin.tasks.submission_period_hours')} 
                    type="number"
                    value={taskForm.submission_period_hours} 
                    onChange={(e) => setTaskForm({ ...taskForm, submission_period_hours: e.target.value })} 
                    placeholder={t('admin.tasks.submission_period_placeholder')}
                  />
                </div>
              </div>

              {/* Section G: Config files */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.upload_scripts_notebooks')}</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  
                  {/* Evaluator script */}
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-slate-300">{t('admin.tasks.evaluator_script_label')}</label>
                    <input 
                      type="file" 
                      accept=".py" 
                      onChange={(e) => setEvaluatorFile(e.target.files[0])}
                      className="text-xs text-slate-400 border border-white/5 p-2 bg-slate-950 rounded-lg"
                    />
                  </div>

                  {/* Baseline Notebook */}
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-slate-300">{t('admin.tasks.baseline_notebook_label')}</label>
                    <input 
                      type="file" 
                      accept=".ipynb" 
                      onChange={(e) => setBaselineFile(e.target.files[0])}
                      className="text-xs text-slate-400 border border-white/5 p-2 bg-slate-950 rounded-lg"
                    />
                  </div>

                  {/* Solution Notebook */}
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-slate-300">{t('admin.tasks.solution_notebook_label')}</label>
                    <input 
                      type="file" 
                      accept=".ipynb" 
                      onChange={(e) => setSolutionFile(e.target.files[0])}
                      className="text-xs text-slate-400 border border-white/5 p-2 bg-slate-950 rounded-lg"
                    />
                  </div>

                </div>

                <div className="mt-4 p-4 rounded-lg bg-slate-900/50 border border-white/5 text-xs text-slate-300">
                  <details className="group">
                    <summary className="font-semibold text-indigo-400 hover:text-indigo-300 cursor-pointer flex items-center justify-between">
                      <span>{t('admin.tasks.show_custom_evaluator')}</span>
                      <span className="transition-transform group-open:rotate-180">▼</span>
                    </summary>
                    <div className="mt-3 text-slate-400 space-y-2">
                      <p>
                        {t('admin.tasks.custom_evaluator_help')}
                      </p>
                      <CodeHighlight code={CUSTOM_EVALUATOR_TEMPLATE} />
                    </div>
                  </details>
                </div>
              </div>

              {/* Section H: Resource Files (Optional) */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.resource_files_title')}</h3>
                
                {/* File list update */}
                {editingTask && editingTask.files && (
                  <div className="mb-4">
                    <span className="text-xs text-slate-400 block mb-2 font-semibold">{t('admin.tasks.current_resource_files')}</span>
                    <div className="flex flex-col gap-2">
                      {(Array.isArray(editingTask.files) 
                        ? editingTask.files 
                        : (typeof editingTask.files === 'string' && editingTask.files.trim() !== ''
                            ? JSON.parse(editingTask.files) 
                            : [])
                      ).map(f => {
                        const isDeleted = (editingTask.filesToDelete || []).includes(f.filename);
                        return (
                          <div key={f.filename} className="flex justify-between items-center p-2.5 bg-slate-950 border border-white/5 rounded-lg text-xs">
                            <span style={{ textDecoration: isDeleted ? 'line-through' : 'none', color: isDeleted ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                              {f.filename} ({t('challenge.kb', { count: Math.round(f.size_bytes / 1024) })})
                            </span>
                            <button
                              type="button"
                              onClick={() => {
                                const current = editingTask.filesToDelete || [];
                                const next = current.includes(f.filename) 
                                  ? current.filter(x => x !== f.filename) 
                                  : [...current, f.filename];
                                setEditingTask({ ...editingTask, filesToDelete: next });
                              }}
                              className="text-xs text-brand-rose bg-transparent border-0 cursor-pointer font-bold"
                            >
                              {isDeleted ? t('admin.tasks.undo_delete') : t('admin.stages.delete')}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div className="flex flex-col gap-2">
                  <input 
                    type="file" 
                    multiple 
                    onChange={(e) => setTaskFiles(Array.from(e.target.files))}
                    className="text-xs text-slate-400 border border-white/5 p-3.5 bg-slate-950 rounded-lg w-full"
                  />
                  <p className="text-[10px] text-slate-500">{t('admin.tasks.press_cmd_ctrl')}</p>
                </div>
              </div>

              <div className="flex gap-4 border-t border-white/5 pt-6 mt-4">
                <Button type="submit" variant="primary">
                  {isCreatingTask ? t('admin.tasks.create_task_btn') : t('admin.stages.save_changes_btn')}
                </Button>
                <Button variant="secondary" onClick={() => { setIsCreatingTask(false); setEditingTask(null); }}>
                  {t('common.cancel')}
                </Button>
              </div>

            </form>
          </div>
        )}

        {/* 3. CREATE NEW COMPETITIONS */}
        {adminSubTab === 'challenge-config' && (currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
            <h2 className="text-xl font-bold text-white mb-6">{t('admin.create_new_challenge')}</h2>
            <form onSubmit={handleCreateChallenge} className="flex flex-col gap-4">
              <InputField 
                label={t('admin.competition_title')} 
                value={newChallenge.title} 
                onChange={(e) => setNewChallenge({ ...newChallenge, title: e.target.value })} 
                required 
              />
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-300">{t('admin.description')}</label>
                <textarea 
                  rows="4" 
                  className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-sm font-sans"
                  value={newChallenge.description} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, description: e.target.value })} 
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <InputField 
                  label={t('admin.daily_limits')} 
                  type="number"
                  value={newChallenge.max_eval_requests} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, max_eval_requests: parseInt(e.target.value) })} 
                  required 
                />
                <InputField 
                  label={t('admin.ram_limit_override')} 
                  type="number"
                  value={newChallenge.ram_limit_mb} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, ram_limit_mb: parseInt(e.target.value) })} 
                  required 
                />
                <InputField 
                  label={t('admin.time_limit_override')} 
                  type="number"
                  value={newChallenge.time_limit_sec} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, time_limit_sec: parseInt(e.target.value) })} 
                  required 
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <InputField 
                  label={t('admin.stages.start_time_label')} 
                  type="datetime-local"
                  value={newChallenge.start_time} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, start_time: e.target.value })} 
                  required
                />
                <InputField 
                  label={t('admin.stages.end_time_label')} 
                  type="datetime-local"
                  value={newChallenge.end_time} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, end_time: e.target.value })} 
                  required
                />
                <SelectField
                  label={t('admin.timezone_choose')}
                  value={newChallenge.timezone}
                  onChange={(val) => setNewChallenge({ ...newChallenge, timezone: val })}
                  options={TIMEZONES}
                  required
                />
              </div>
              <div className="flex flex-col gap-3 mt-2.5">
                <ToggleField 
                  label={t('admin.requires_gpu_workers')}
                  id="create-gpu-req"
                  checked={newChallenge.gpu_required}
                  onChange={(e) => setNewChallenge({ ...newChallenge, gpu_required: e.target.checked })}
                />
                <ToggleField 
                  label={t('admin.double_blind_eval')}
                  id="create-double-blind"
                  checked={newChallenge.double_blind !== false}
                  onChange={(e) => setNewChallenge({ ...newChallenge, double_blind: e.target.checked })}
                />
                <ToggleField 
                  label={t('admin.freeze_label')}
                  id="create-is-frozen"
                  checked={newChallenge.is_frozen || false}
                  onChange={(e) => setNewChallenge({ ...newChallenge, is_frozen: e.target.checked })}
                />
              </div>
              <Button type="submit" variant="primary" className="w-fit mt-4">{t('admin.create_competition_btn')}</Button>
            </form>
          </div>
        )}

        {/* 4. COMPETITOR REGISTRATION MODULE (JURY/ADMIN) */}
        {adminSubTab === 'competitor-reg' && (
          <div className="flex flex-col gap-8 animate-fadein">
            
            {/* Registration Workspace */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
              {editingUser ? (
                /* Edit Competitor Form */
                <div className="bg-[#0d0e18] border border-indigo-500/20 p-8 rounded-2xl lg:col-span-1">
                  <h2 className="text-lg font-bold text-white mb-2">{t('admin.competitor_reg.edit_competitor_details')}</h2>
                  <p className="text-slate-400 text-xs mb-6">{t('admin.competitor_reg.updating_account', { username: editingUser.username })}</p>
                  
                  <form onSubmit={handleUpdateUserSubmit} className="flex flex-col gap-4">
                    <div className="grid grid-cols-2 gap-4">
                      <InputField 
                        label={t('admin.competitor_reg.first_name')} 
                        value={editUserForm.name} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, name: e.target.value })} 
                        required 
                      />
                      <InputField 
                        label={t('admin.competitor_reg.last_name')} 
                        value={editUserForm.surname} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, surname: e.target.value })} 
                        required 
                      />
                    </div>
                    
                    <div className="grid grid-cols-3 gap-4">
                      <InputField 
                        label={t('admin.competitor_reg.grade')} 
                        value={editUserForm.grade} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, grade: e.target.value })} 
                      />
                      <InputField 
                        label={t('admin.competitor_reg.school')} 
                        value={editUserForm.school} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, school: e.target.value })} 
                      />
                      <InputField 
                        label={t('admin.competitor_reg.city')} 
                        value={editUserForm.city} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, city: e.target.value })} 
                      />
                    </div>

                    <InputField 
                      label={t('admin.competitor_reg.system_username')} 
                      value={editUserForm.username} 
                      onChange={(e) => setEditUserForm({ ...editUserForm, username: e.target.value })} 
                      required 
                    />

                    <InputField 
                      label={t('admin.competitor_reg.email_address')} 
                      type="email"
                      value={editUserForm.email} 
                      onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })} 
                      placeholder={t('admin.competitor_reg.email_placeholder')}
                    />

                    <SelectField 
                      label={t('admin.competitor_reg.assign_competition')} 
                      value={editUserForm.challenge_id} 
                      onChange={(val) => setEditUserForm({ ...editUserForm, challenge_id: val })} 
                      required 
                      options={[
                        { value: "", label: t('admin.competitor_reg.assign_competition_choose') },
                        ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                      ]}
                    />

                    <div className="mt-2.5">
                      <ToggleField 
                        label={t('admin.competitor_reg.anonymous_help')}
                        id="edit-is-anonymous"
                        checked={editUserForm.is_anonymous}
                        onChange={(e) => setEditUserForm({ ...editUserForm, is_anonymous: e.target.checked })}
                      />
                    </div>

                    {isEditDisabled && (
                      <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                        {t('admin.competitor_reg.competition_started_warning')}
                      </div>
                    )}
                    <div className="flex gap-2.5 mt-2">
                      <Button type="submit" variant="primary" className="flex-1" disabled={isEditDisabled}>{t('admin.stages.save_changes_btn')}</Button>
                      <Button type="button" variant="secondary" onClick={() => setEditingUser(null)}>{t('common.cancel')}</Button>
                    </div>
                  </form>
                </div>
              ) : (
                <>
                  {/* Form Manual */}
                  <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                    <h2 className="text-lg font-bold text-white mb-2">{t('admin.competitor_reg.manual_competitor_registration')}</h2>
                    <p className="text-slate-400 text-xs mb-6">{t('admin.competitor_reg.manual_registration_desc')}</p>
                    
                    <form onSubmit={handleRegisterCompetitor} className="flex flex-col gap-4">
                      <div className="grid grid-cols-2 gap-4">
                        <InputField 
                          label={t('admin.competitor_reg.first_name')} 
                          value={newCompetitor.name} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, name: e.target.value })} 
                          required 
                        />
                        <InputField 
                          label={t('admin.competitor_reg.last_name')} 
                          value={newCompetitor.surname} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, surname: e.target.value })} 
                          required 
                        />
                      </div>
                      <div className="grid grid-cols-3 gap-4">
                        <InputField 
                          label={t('admin.competitor_reg.grade')} 
                          value={newCompetitor.grade} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, grade: e.target.value })} 
                        />
                        <InputField 
                          label={t('admin.competitor_reg.school')} 
                          value={newCompetitor.school} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, school: e.target.value })} 
                        />
                        <InputField 
                          label={t('admin.competitor_reg.city')} 
                          value={newCompetitor.city} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, city: e.target.value })} 
                        />
                      </div>
                      
                      <SelectField 
                        label={t('admin.competitor_reg.assign_competition')} 
                        value={newCompetitor.challenge_id} 
                        onChange={(val) => setNewCompetitor({ ...newCompetitor, challenge_id: val })} 
                        required 
                        options={[
                          { value: "", label: t('admin.competitor_reg.assign_competition_choose') },
                          ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                        ]}
                      />

                      <div className="mt-2.5">
                        <ToggleField 
                          label={t('admin.competitor_reg.anonymous_help')}
                          id="register-is-anonymous"
                          checked={newCompetitor.is_anonymous}
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, is_anonymous: e.target.checked })}
                        />
                      </div>

                      {isManualRegisterDisabled && (
                        <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                          {t('admin.competitor_reg.competition_started_warning')}
                        </div>
                      )}
                      <Button type="submit" variant="primary" className="mt-2" disabled={isManualRegisterDisabled}>{t('admin.competitor_reg.generate_credentials')}</Button>
                    </form>

                    {generatedCredentials && (
                      <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
                        <h3 className="font-bold text-sm text-indigo-300">{t('admin.competitor_reg.competitor_account_generated')}</h3>
                        <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                          <div><strong>{t('admin.competitor_reg.competitor_label')}</strong> {generatedCredentials.name} {generatedCredentials.surname}</div>
                          <div className="pt-2"><strong>{t('admin.competitor_reg.generated_username')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedCredentials.username}</code></div>
                          <div><strong>{t('admin.competitor_reg.generated_password')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedCredentials.password}</code></div>
                          <p className="text-[10px] text-slate-500 mt-2 font-medium">{t('admin.competitor_reg.share_credentials_help')}</p>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Form CSV upload */}
                  <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                    <h2 className="text-lg font-bold text-white mb-2">{t('admin.competitor_reg.import_competitors_csv')}</h2>
                    <p className="text-slate-400 text-xs mb-6">{t('admin.competitor_reg.csv_import_desc')}</p>
                    
                    <form onSubmit={handleCSVImport} className="flex flex-col gap-4">
                      <SelectField 
                        label={t('admin.competitor_reg.target_competition_challenge')} 
                        value={csvChallengeId} 
                        onChange={(val) => setCsvChallengeId(val)} 
                        required 
                        options={[
                          { value: "", label: t('admin.competitor_reg.assign_competition_choose') },
                          ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                        ]}
                      />

                      <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold text-slate-300">{t('admin.competitor_reg.choose_csv_file')}</label>
                        <input 
                          type="file" 
                          accept=".csv" 
                          onChange={(e) => setCsvFile(e.target.files[0])}
                          className="text-xs text-slate-400 border border-white/5 p-3.5 bg-slate-900 rounded-lg cursor-pointer"
                          required
                        />
                      </div>

                      {isCSVImportDisabled && (
                        <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                          {t('admin.competitor_reg.bulk_import_started_warning')}
                        </div>
                      )}
                      <Button type="submit" variant="accent" disabled={csvImporting || isCSVImportDisabled}>
                        {csvImporting ? t('admin.competitor_reg.importing_bulk_data') : t('admin.competitor_reg.upload_parse_csv')}
                      </Button>
                    </form>

                    {importedCompetitors.length > 0 && (
                      <div className="mt-6 p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3">
                        <h3 className="font-bold text-sm text-emerald-400">{t('admin.competitor_reg.successfully_imported_count', { count: importedCompetitors.length })}</h3>
                        <div className="max-h-60 overflow-y-auto pr-1">
                          <table className="w-full text-left border-collapse text-[10px]">
                            <thead>
                              <tr className="border-b border-white/5 text-slate-400">
                                <th className="py-1.5">{t('admin.competitor_reg.competitor_table_header')}</th>
                                <th className="py-1.5">{t('admin.competitor_reg.username_table_header')}</th>
                                <th className="py-1.5">{t('admin.competitor_reg.password_table_header')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {importedCompetitors.map((item, idx) => (
                                <tr key={idx} className="border-b border-white/5 text-slate-300">
                                  <td className="py-1.5 font-semibold">{item.name} {item.surname}</td>
                                  <td className="py-1.5 font-mono">{item.generated_username}</td>
                                  <td className="py-1.5 font-mono font-bold text-indigo-400">{item.generated_password}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* List Registered Competitors */}
            <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
              <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
                <div>
                  <h2 className="text-lg font-bold text-white">{t('admin.competitor_reg.registered_competitors')}</h2>
                  <p className="text-slate-400 text-xs">{t('admin.competitor_reg.unmasking_desc')}</p>
                </div>
                <div className="flex items-center gap-3.5 flex-wrap">
                  {(currentUser.role === 'admin' || challenges.some(c => !isChallengeStarted(c.id))) && (
                    <Button 
                      variant="secondary" 
                      size="sm"
                      onClick={handleBulkResetPasswords}
                    >
                      {t('admin.competitor_reg.reset_all_passwords')}
                    </Button>
                  )}
                  <InputField 
                    placeholder={currentUser.role === 'jury' && selectedChallenge && isChallengeStarted(selectedChallenge.id) ? t('admin.competitor_reg.search_alias_only_placeholder') : t('admin.competitor_reg.search_competitor_placeholder')} 
                    value={competitorSearch} 
                    onChange={(e) => setCompetitorSearch(e.target.value)} 
                    className="max-w-xs w-full"
                  />
                </div>
              </div>

              {resetCredentials && (
                <div className="mb-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5 animate-fadein">
                  <div className="flex justify-between items-center">
                    <h3 className="font-bold text-sm text-indigo-300 font-sans">{t('admin.competitor_reg.password_reset_succeeded')}</h3>
                    <button 
                      onClick={() => setResetCredentials(null)} 
                      className="text-xs font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
                    >
                      {t('admin.competitor_reg.clear')}
                    </button>
                  </div>
                  <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                    <div><strong>{t('admin.competitor_reg.account_username')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{resetCredentials.username}</code></div>
                    <div><strong>{t('admin.competitor_reg.new_generated_password')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{resetCredentials.password}</code></div>
                    <p className="text-[10px] text-slate-500 mt-2 font-medium">{t('admin.competitor_reg.share_credentials_help')}</p>
                  </div>
                </div>
              )}

              {bulkResetCredentials.length > 0 && (
                <div className="mb-6 p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3 animate-fadein">
                  <div className="flex justify-between items-center">
                    <h3 className="font-bold text-sm text-emerald-400 font-sans">{t('admin.competitor_reg.generated_passwords_bulk_title', { count: bulkResetCredentials.length })}</h3>
                    <button 
                      onClick={() => setBulkResetCredentials([])} 
                      className="text-xs font-bold text-emerald-400 hover:underline bg-transparent border-0 cursor-pointer"
                    >
                      {t('admin.competitor_reg.clear_list')}
                    </button>
                  </div>
                  <div className="max-h-60 overflow-y-auto pr-1">
                    <table className="w-full text-left border-collapse text-[10px]">
                      <thead>
                        <tr className="border-b border-white/5 text-slate-400 font-semibold">
                          <th className="py-1.5">{t('admin.competitor_reg.competitor_table_header')}</th>
                          <th className="py-1.5">{t('admin.competitor_reg.username_table_header')}</th>
                          <th className="py-1.5">{t('admin.competitor_reg.new_password_table_header')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {bulkResetCredentials.map((item, idx) => (
                          <tr key={idx} className="border-b border-white/5 text-slate-300">
                            <td className="py-1.5 font-semibold">{item.name} {item.surname}</td>
                            <td className="py-1.5 font-mono">{item.username}</td>
                            <td className="py-1.5 font-mono font-bold text-indigo-400">{item.password}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {filteredCompetitors.length === 0 ? (
                <div className="text-center py-8 text-slate-500 text-xs italic">
                  {t('admin.competitor_reg.no_competitors_found')}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t('admin.competitor_reg.alias_id_header')}</th>
                        <th>{t('admin.competitor_reg.real_name_header')}</th>
                        <th>{t('admin.competitor_reg.school_grade_header')}</th>
                        <th>{t('admin.competitor_reg.city_header')}</th>
                        <th>{t('admin.competitor_reg.system_username')}</th>
                        <th className="text-right">{t('admin.competitor_reg.actions_header')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCompetitors.map(comp => (
                        <tr key={comp.id}>
                          <td className="font-mono font-semibold text-indigo-400">{comp.alias_id}</td>
                          <td>
                            <div className="flex items-center gap-2">
                              <span>{comp.name ? `${comp.name} ${comp.surname || ''}` : <span className="text-slate-500 italic">{t('admin.competitor_reg.double_blind_badge')}</span>}</span>
                              {comp.is_anonymous && (
                                <span className="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 uppercase tracking-wider" title={t('admin.competitor_reg.requested_anonymity_title')}>{t('admin.competitor_reg.anon_badge')}</span>
                              )}
                            </div>
                          </td>
                          <td>{comp.school ? `${comp.school}${comp.grade ? ` (${t('leaderboard.grade_value', { grade: comp.grade })})` : ""}` : "—"}</td>
                          <td>{comp.city || "—"}</td>
                          <td className="font-mono text-slate-400">{comp.username || <span className="text-slate-500 italic">{t('admin.competitor_reg.hidden_badge')}</span>}</td>
                          <td style={{ textAlign: 'right' }}>
                            <div className="flex justify-end gap-3.5">
                              {(currentUser.role === 'admin' || !isChallengeStarted(comp.challenge_id)) && (
                                <>
                                  <button
                                    onClick={() => initEditUser(comp)}
                                    className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
                                  >
                                    {t('admin.competitor_reg.edit')}
                                  </button>
                                  <button
                                    onClick={() => handleResetUserPassword(comp.id, comp.name ? `${comp.name} ${comp.surname}` : comp.alias_id)}
                                    className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
                                  >
                                    {t('admin.competitor_reg.reset_pw_btn')}
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination
                    page={competitorsPage}
                    pages={competitorsPages}
                    total={competitorsTotal}
                    perPage={10}
                    onPageChange={setCompetitorsPage}
                    itemName={t('admin.competitor_reg.competitors')}
                  />
                </div>
              )}
            </div>

          </div>
        )}

        {/* 5. DATABASE BACKUP MANAGEMENT */}
        {adminSubTab === 'backups' && currentUser.role === 'admin' && (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
            <h2 className="text-xl font-bold text-white mb-2">{t('admin.backups.database_backups_security')}</h2>
            <p className="text-slate-400 text-xs mb-6">{t('admin.backups.database_backups_desc')}</p>
            
            <div className="bg-slate-900/40 border border-white/5 p-6 rounded-xl flex items-center justify-between gap-4 flex-wrap">
              <div>
                <h4 className="font-bold text-slate-200 text-sm">{t('admin.backups.download_postgres_backup')}</h4>
                <p className="text-slate-500 text-xs mt-1">{t('admin.backups.download_postgres_backup_desc')}</p>
              </div>
              <Button variant="accent" onClick={handleDownloadBackup}>{t('admin.backups.download_backup_dump_btn')}</Button>
            </div>
          </div>
        )}

        {/* 6. SYSTEM USER MANAGEMENT */}
        {adminSubTab === 'user-management' && currentUser.role === 'admin' && (
          <div className="flex flex-col gap-8 animate-fadein">
            
            <div className="flex flex-col gap-8">
              
              {/* Form Register Admin/Jury */}
              <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl w-full">
                <h2 className="text-lg font-bold text-white mb-2">{t('admin.user_mgmt.register_user_account')}</h2>
                <p className="text-slate-400 text-xs mb-6">{t('admin.user_mgmt.register_user_account_desc')}</p>
                
                <form onSubmit={handleRegisterUser} className="flex flex-col gap-4">
                  <InputField 
                    label={t('admin.user_mgmt.username_label')} 
                    value={newUser.username} 
                    onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} 
                    placeholder={t('admin.user_mgmt.username_placeholder_eg')}
                    required 
                  />
                  <InputField 
                    label={t('admin.competitor_reg.email_address')} 
                    type="email"
                    value={newUser.email} 
                    onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} 
                    placeholder={t('admin.user_mgmt.email_placeholder_eg')}
                  />
                  
                  <div className="grid grid-cols-2 gap-4">
                    <InputField 
                      label={t('admin.competitor_reg.first_name')} 
                      value={newUser.name} 
                      onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} 
                      required 
                    />
                    <InputField 
                      label={t('admin.competitor_reg.last_name')} 
                      value={newUser.surname} 
                      onChange={(e) => setNewUser({ ...newUser, surname: e.target.value })} 
                      required 
                    />
                  </div>

                  <SelectField 
                    label={t('admin.user_mgmt.role_label')} 
                    value={newUser.role} 
                    onChange={(val) => setNewUser({ ...newUser, role: val })} 
                    required 
                    options={[
                      { value: "competitor", label: t('admin.user_mgmt.role_competitor') },
                      { value: "jury", label: t('admin.user_mgmt.role_jury') }
                    ]}
                  />

                  {newUser.role === 'competitor' && (
                    <>
                      <div className="grid grid-cols-3 gap-2">
                        <InputField label={t('admin.competitor_reg.grade')} value={newUser.grade} onChange={(e) => setNewUser({ ...newUser, grade: e.target.value })} />
                        <InputField label={t('admin.competitor_reg.school')} value={newUser.school} onChange={(e) => setNewUser({ ...newUser, school: e.target.value })} />
                        <InputField label={t('admin.competitor_reg.city')} value={newUser.city} onChange={(e) => setNewUser({ ...newUser, city: e.target.value })} />
                      </div>
                      <SelectField 
                        label={t('admin.competitor_reg.assign_competition')} 
                        value={newUser.challenge_id} 
                        onChange={(val) => setNewUser({ ...newUser, challenge_id: val })} 
                        required 
                        options={[
                          { value: "", label: t('admin.competitor_reg.assign_competition_choose') },
                          ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                        ]}
                      />

                      <div className="mt-2.5">
                        <ToggleField 
                          label={t('admin.competitor_reg.anonymous_help')}
                          id="new-user-is-anonymous"
                          checked={newUser.is_anonymous}
                          onChange={(e) => setNewUser({ ...newUser, is_anonymous: e.target.checked })}
                        />
                      </div>
                    </>
                  )}

                  <Button type="submit" variant="primary" className="mt-2">{t('admin.user_mgmt.register_user_btn')}</Button>
                </form>

                {generatedUserCredentials && (
                  <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
                    <h3 className="font-bold text-sm text-indigo-300">{t('admin.user_mgmt.account_created_title', { role: t(`admin.user_mgmt.role_${generatedUserCredentials.role}`).toUpperCase() })}</h3>
                    <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                      <div><strong>{t('admin.user_mgmt.user_label')}</strong> {generatedUserCredentials.name} {generatedUserCredentials.surname}</div>
                      <div className="pt-2"><strong>{t('admin.user_mgmt.username_label_colon')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedUserCredentials.username}</code></div>
                      <div><strong>{t('admin.user_mgmt.password_label_colon')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedUserCredentials.password}</code></div>
                    </div>
                  </div>
                )}
              </div>

              {/* User accounts list */}
              <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl w-full">
                <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
                  <div>
                    <h2 className="text-lg font-bold text-white">{t('admin.user_mgmt.system_user_accounts')}</h2>
                    <p className="text-slate-400 text-xs">{t('admin.user_mgmt.system_user_accounts_desc')}</p>
                  </div>
                  <InputField 
                    placeholder={t('admin.user_mgmt.search_users_placeholder')} 
                    value={userSearch} 
                    onChange={(e) => setUserSearch(e.target.value)} 
                    className="max-w-xs w-full"
                  />
                </div>

                {filteredUsers.length === 0 ? (
                  <div className="text-center py-8 text-slate-500 text-xs italic">
                    {t('admin.user_mgmt.no_users_found')}
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>{t('admin.user_mgmt.username_header')}</th>
                          <th>{t('admin.competitor_reg.real_name_header')}</th>
                          <th>{t('admin.user_mgmt.role_header')}</th>
                          <th>{t('admin.user_mgmt.email_address_header')}</th>
                          <th className="text-right">{t('admin.competitor_reg.actions_header')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredUsers.map(user => (
                          <tr key={user.id}>
                            <td className="font-mono font-bold text-slate-200">{user.username}</td>
                            <td>
                              <div className="flex items-center gap-2">
                                <span>{user.name} {user.surname}</span>
                                {user.is_anonymous && (
                                  <span className="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 uppercase tracking-wider" title={t('admin.competitor_reg.requested_anonymity_title')}>{t('admin.competitor_reg.anon_badge')}</span>
                                )}
                              </div>
                            </td>
                            <td>
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${user.role === 'admin' ? 'border-rose-500/30 bg-rose-500/10 text-rose-400' : user.role === 'jury' ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-blue-500/30 bg-blue-500/10 text-blue-400'}`}>
                                {user.role.toUpperCase()}
                              </span>
                            </td>
                            <td>{user.email || "—"}</td>
                            <td style={{ textAlign: 'right' }}>
                              {user.id !== currentUser.id ? (
                                <button
                                  onClick={() => handleDeleteUser(user.id, user.username)}
                                  className="text-[11px] font-bold text-rose-400 hover:underline bg-transparent border-0 cursor-pointer"
                                >
                                  {t('admin.user_mgmt.delete_btn')}
                                </button>
                              ) : (
                                <span className="text-[10px] text-slate-500 font-semibold italic">{t('admin.user_mgmt.current_admin')}</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <Pagination
                      page={usersPage}
                      pages={usersPages}
                      total={usersTotal}
                      perPage={10}
                      onPageChange={setUsersPage}
                      itemName={t('admin.user_mgmt.users')}
                    />
                  </div>
                )}
              </div>

            </div>

          </div>
        )}

        {adminSubTab === 'workers-stats' && (currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <div className="flex flex-col gap-6 animate-fadein">
            {/* Header / Control Bar */}
            <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-wrap justify-between items-center gap-4">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">{t('admin.workers.system_resources')}</h2>
                <p className="text-slate-400 text-xs">
                  {t('admin.workers.monitoring_desc')}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {workerStatsLoading && (
                  <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
                )}
                <Button 
                  variant="secondary" 
                  onClick={fetchWorkerStats}
                  disabled={workerStatsLoading}
                  className="text-xs"
                >
                  {workerStatsLoading ? t('admin.workers.refreshing') : t('admin.workers.refresh_now')}
                </Button>
              </div>
            </div>

            {/* Error Message */}
            {workerStatsError && (
              <div className="bg-rose-500/10 border border-rose-500/20 p-4 rounded-xl text-rose-400 text-xs font-semibold">
                {t('admin.workers.error_retrieving_stats', { error: workerStatsError })}
              </div>
            )}

            {/* Host Server Resources */}
            {workerStats?.system && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* CPU Card */}
                <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
                  <div>
                    <h3 className="text-slate-400 font-bold text-xs uppercase tracking-wider mb-2">{t('admin.workers.cpu_utilization')}</h3>
                    <div className="flex items-baseline gap-2 mb-3">
                      <span className="text-2xl font-extrabold text-white">
                        {workerStats.system.load_avg?.[0]?.toFixed(2) || '0.00'}
                      </span>
                      <span className="text-slate-500 text-[10px]">{t('admin.workers.one_min_load')}</span>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-[10px] text-slate-500 font-bold mb-1">
                      <span>{t('admin.workers.load_trend')}</span>
                      <span>{t('admin.workers.cores', { count: workerStats.system.cpu_count })}</span>
                    </div>
                    <div className="flex gap-2 font-mono text-[10px] text-indigo-400 font-semibold bg-indigo-500/5 px-3 py-1.5 rounded-lg border border-indigo-500/10">
                      <span>{t('admin.workers.load_5m', { value: workerStats.system.load_avg?.[1]?.toFixed(2) || '0.00' })}</span>
                      <span className="text-slate-700">|</span>
                      <span>{t('admin.workers.load_15m', { value: workerStats.system.load_avg?.[2]?.toFixed(2) || '0.00' })}</span>
                    </div>
                  </div>
                </div>

                {/* RAM Memory Card */}
                <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
                  <div>
                    <h3 className="text-slate-400 font-bold text-xs uppercase tracking-wider mb-2">{t('admin.workers.memory_usage')}</h3>
                    <div className="flex items-baseline gap-2 mb-3">
                      <span className="text-2xl font-extrabold text-white">
                        {workerStats.system.memory?.percent_used || '0'}%
                      </span>
                      <span className="text-slate-500 text-[10px]">
                        {t('admin.workers.memory_used_total', { used: workerStats.system.memory?.used_gb || '0', total: workerStats.system.memory?.total_gb || '0' })}
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden mb-2">
                      <div 
                        className={`h-full rounded-full transition-all duration-500 ${
                          (workerStats.system.memory?.percent_used || 0) > 90 ? 'bg-rose-500' :
                          (workerStats.system.memory?.percent_used || 0) > 75 ? 'bg-amber-500' : 'bg-indigo-500'
                        }`}
                        style={{ width: `${Math.min(workerStats.system.memory?.percent_used || 0, 100)}%` }}
                      ></div>
                    </div>
                    <div className="flex justify-between text-[10px] text-slate-500 font-bold">
                      <span>{t('admin.workers.used', { count: workerStats.system.memory?.used_gb || '0' })}</span>
                      <span>{t('admin.workers.free', { count: workerStats.system.memory?.free_gb || '0' })}</span>
                    </div>
                  </div>
                </div>

                {/* Disk Space Card */}
                <div className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
                  <div>
                    <h3 className="text-slate-400 font-bold text-xs uppercase tracking-wider mb-2">{t('admin.workers.disk_capacity')}</h3>
                    <div className="flex items-baseline gap-2 mb-3">
                      <span className="text-2xl font-extrabold text-white">
                        {workerStats.system.disk?.percent_used || '0'}%
                      </span>
                      <span className="text-slate-500 text-[10px]">
                        {t('admin.workers.memory_used_total', { used: workerStats.system.disk?.used_gb || '0', total: workerStats.system.disk?.total_gb || '0' })}
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden mb-2">
                      <div 
                        className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                        style={{ width: `${Math.min(workerStats.system.disk?.percent_used || 0, 100)}%` }}
                      ></div>
                    </div>
                    <div className="flex justify-between text-[10px] text-slate-500 font-bold">
                      <span>{t('admin.workers.used', { count: workerStats.system.disk?.used_gb || '0' })}</span>
                      <span>{t('admin.workers.free', { count: workerStats.system.disk?.free_gb || '0' })}</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Workers Summary Row */}
            {workerStats && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
                  <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">{t('admin.workers.connected_workers_label')}</div>
                  <div className="text-xl font-extrabold text-white mt-1">{workerStats.connected_workers_count}</div>
                </div>
                <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
                  <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">{t('admin.workers.total_active_tasks')}</div>
                  <div className="text-xl font-extrabold text-indigo-400 mt-1">
                    {workerStats.workers?.reduce((sum, w) => sum + (w.active_tasks_count || 0), 0) || 0}
                  </div>
                </div>
                <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
                  <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">{t('admin.workers.reserved_tasks_label')}</div>
                  <div className="text-xl font-extrabold text-amber-400 mt-1">
                    {workerStats.workers?.reduce((sum, w) => sum + (w.reserved_tasks_count || 0), 0) || 0}
                  </div>
                </div>
                <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl text-center">
                  <div className="text-slate-500 text-[10px] font-bold uppercase tracking-wider">{t('admin.workers.tasks_processed_label')}</div>
                  <div className="text-xl font-extrabold text-emerald-400 mt-1">
                    {workerStats.workers?.reduce((sum, w) => sum + (w.total_tasks_processed || 0), 0) || 0}
                  </div>
                </div>
              </div>
            )}

            {/* System Info Footnote */}
            {workerStats?.system && (
              <div className="bg-slate-900/20 border border-white/5 px-4 py-2.5 rounded-xl flex flex-wrap gap-x-6 gap-y-2 text-[10px] text-slate-500 font-mono">
                <span><strong>{t('admin.workers.os')}</strong> {workerStats.system.os} {workerStats.system.platform_release}</span>
                <span><strong>{t('admin.workers.python')}</strong> {workerStats.system.python_version}</span>
              </div>
            )}

            {/* Workers Detailed List */}
            <div className="flex flex-col gap-4">
              <h3 className="text-sm font-bold text-white uppercase tracking-wider px-1">{t('admin.workers.connected_nodes_label')}</h3>

              {(!workerStats || workerStats.workers?.length === 0) ? (
                <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl text-center text-slate-500 text-xs italic">
                  {workerStatsLoading ? t('admin.workers.fetching_metrics') : t('admin.workers.no_active_workers_connected')}
                </div>
              ) : (
                workerStats.workers.map((worker) => (
                  <div key={worker.name} className="bg-[#0d0e18] border border-white/5 rounded-2xl overflow-hidden">
                    {/* Worker Header */}
                    <div className="bg-slate-900/40 border-b border-white/5 p-5 flex flex-wrap justify-between items-center gap-4">
                      <div className="flex items-center gap-3">
                        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        <h4 className="font-mono text-sm font-bold text-slate-200">{worker.name}</h4>
                      </div>
                      <div className="flex items-center gap-4 text-xs font-mono">
                        <div className="text-slate-500">
                          {t('admin.workers.pid_label')} <span className="text-slate-300 font-bold">{worker.pid || 'N/A'}</span>
                        </div>
                        <div className="text-slate-500">
                          {t('admin.workers.uptime_label', { time: '' })}<span className="text-indigo-400 font-bold">{formatUptime(worker.uptime)}</span>
                        </div>
                      </div>
                    </div>

                    {/* Worker Stats Body */}
                    <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
                      {/* Left: General Stats & Resource Usage */}
                      <div className="flex flex-col gap-4">
                        <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{t('admin.workers.capacity_resource_usage')}</h5>
                        <div className="bg-slate-900/20 border border-white/5 p-4 rounded-xl flex flex-col gap-3 text-xs">
                          <div className="flex justify-between">
                            <span className="text-slate-500">{t('admin.workers.concurrency_pool')}</span>
                            <span className="font-bold text-slate-300">{t('admin.workers.concurrency_pool_processes', { count: worker.pool_size })}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500">{t('admin.workers.processed_tasks')}</span>
                            <span className="font-bold text-emerald-400">{worker.total_tasks_processed}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500">{t('admin.workers.max_ram_usage')}</span>
                            <span className="font-bold text-slate-300">
                              {worker.rusage?.maxrss_mb ? `${worker.rusage.maxrss_mb} MB` : 'N/A'}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500">{t('admin.workers.cpu_time')}</span>
                            <span className="font-mono font-bold text-slate-300">
                              {worker.rusage?.utime_sec !== undefined ? `${worker.rusage.utime_sec.toFixed(2)}s` : 'N/A'}
                              {' / '}
                              {worker.rusage?.stime_sec !== undefined ? `${worker.rusage.stime_sec.toFixed(2)}s` : 'N/A'}
                            </span>
                          </div>
                        </div>

                        {/* Broker Details */}
                        <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mt-2">{t('admin.workers.broker_connection')}</h5>
                        <div className="bg-slate-900/20 border border-white/5 p-4 rounded-xl flex flex-col gap-2 font-mono text-[11px] text-slate-400">
                          <div><span className="text-slate-600">{t('admin.workers.transport')}</span> {worker.broker?.transport || 'N/A'}</div>
                          <div><span className="text-slate-600">{t('admin.workers.hostname')}</span> {worker.broker?.hostname || 'N/A'}</div>
                          <div><span className="text-slate-600">{t('admin.workers.port')}</span> {worker.broker?.port || 'N/A'}</div>
                        </div>
                      </div>

                      {/* Middle: Active & Reserved Tasks */}
                      <div className="lg:col-span-2 flex flex-col gap-4">
                        {/* Active Tasks */}
                        <div>
                          <div className="flex justify-between items-center mb-2">
                            <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{t('admin.workers.active_tasks', { count: worker.active_tasks_count })}</h5>
                            {worker.active_tasks_count > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 uppercase border border-indigo-500/20 animate-pulse">{t('admin.workers.running')}</span>}
                          </div>
                          
                          {worker.active_tasks?.length === 0 ? (
                            <div className="bg-slate-900/10 border border-white/5 p-4 rounded-xl text-center text-slate-500 text-xs italic">
                              {t('admin.workers.no_active_tasks')}
                            </div>
                          ) : (
                            <div className="bg-slate-900/20 border border-white/5 rounded-xl overflow-hidden">
                              <table className="w-full text-left border-collapse text-[10px]">
                                <thead>
                                  <tr className="bg-slate-900/50 text-slate-400 font-bold uppercase border-b border-white/5">
                                    <th className="p-3">{t('admin.workers.task_id_header')}</th>
                                    <th className="p-3">{t('admin.workers.task_name_header')}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {worker.active_tasks?.map((task) => (
                                    <tr key={task.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                                      <td className="p-3 font-mono text-slate-300 font-semibold">{task.id}</td>
                                      <td className="p-3 font-mono text-indigo-400">{task.name}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>

                        {/* Reserved Queue Tasks */}
                        <div className="mt-2">
                          <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">{t('admin.workers.reserved_queue', { count: worker.reserved_tasks_count })}</h5>
                          
                          {worker.reserved_tasks?.length === 0 ? (
                            <div className="bg-slate-900/10 border border-white/5 p-4 rounded-xl text-center text-slate-500 text-xs italic">
                              {t('admin.workers.queue_empty')}
                            </div>
                          ) : (
                            <div className="bg-slate-900/20 border border-white/5 rounded-xl overflow-hidden">
                              <table className="w-full text-left border-collapse text-[10px]">
                                <thead>
                                  <tr className="bg-slate-900/50 text-slate-400 font-bold uppercase border-b border-white/5">
                                    <th className="p-3">{t('admin.workers.task_id_header')}</th>
                                    <th className="p-3">{t('admin.workers.task_name_header')}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {worker.reserved_tasks?.map((task) => (
                                    <tr key={task.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                                      <td className="p-3 font-mono text-slate-300 font-semibold">{task.id}</td>
                                      <td className="p-3 font-mono text-amber-400">{task.name}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>

                        {/* Registered Capabilities */}
                        <div className="mt-2">
                          <h5 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">{t('admin.workers.registered_capabilities')}</h5>
                          <div className="flex flex-wrap gap-2">
                            {worker.registered_tasks?.length === 0 ? (
                              <span className="text-[10px] text-slate-500 italic">{t('admin.workers.no_capabilities')}</span>
                            ) : (
                              worker.registered_tasks?.map((taskName) => (
                                <span key={taskName} className="font-mono text-[9px] font-bold px-2 py-1 rounded bg-slate-900/60 text-slate-400 border border-white/5">
                                  {taskName}
                                </span>
                              ))
                            )}
                          </div>
                        </div>

                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

          </div>
        )}

      </div>
    </div>
  );
}
