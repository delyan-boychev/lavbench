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

// Modular Child Components & Service Layer
import WorkersStats from '../components/admin/WorkersStats';
import BackupManager from '../components/admin/BackupManager';
import UserManager from '../components/admin/UserManager';
import CompetitorManager from '../components/admin/CompetitorManager';
import ChallengeConfig from '../components/admin/ChallengeConfig';

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

export const formatMetricName = (name) => {
  if (!name) return '';
  
  const specialWords = {
    f1: 'F1',
    rmse: 'RMSE',
    mae: 'MAE',
    mse: 'MSE',
    fid: 'FID',
    oks: 'OKS',
    pck: 'PCK',
    snr: 'SNR',
    ssim: 'SSIM',
    psnr: 'PSNR',
    mrr: 'MRR',
    ndcg: 'NDCG',
    map: 'mAP',
    iou: 'IoU',
    chrf: 'chrF',
    bleu: 'BLEU',
    rouge: 'ROUGE',
    meteor: 'METEOR',
    ter: 'TER',
    auc: 'AUC',
    roc: 'ROC',
    mape: 'MAPE',
    ae: 'AE',
    bertscore: 'BERTScore',
    is: 'IS',
    lpips: 'LPIPS',
    niqe: 'NIQE',
    lsd: 'LSD',
    nisqa: 'NISQA',
    pesq: 'PESQ',
    sdr: 'SDR',
    si: 'SI',
  };

  let formatted = name.replace(/_/g, ' ');

  if (formatted.toLowerCase() === 'map 50 95') {
    return 'mAP 50-95';
  }

  return formatted
    .split(' ')
    .map(word => {
      const lower = word.toLowerCase();
      if (specialWords[lower] !== undefined) {
        return specialWords[lower];
      }
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(' ');
};

const TASK_TYPE_METRICS = {
  classification: [
    "accuracy",
    "f1_macro",
    "f1_micro",
    "f1_weighted",
    "precision",
    "precision_macro",
    "precision_micro",
    "precision_weighted",
    "recall",
    "recall_macro",
    "recall_micro",
    "recall_weighted",
    "cohen_kappa",
    "matthews_corrcoef"
  ],
  probabilistic: ["auc_roc", "logloss", "brier_score"],
  regression: ["rmse", "mae", "r_squared", "mape", "median_ae"],
  ner_tagging: ["seqeval_f1", "seqeval_precision", "seqeval_recall"],
  translation_summ: ["bleu", "rouge_l", "meteor", "bertscore", "chrf", "ter"],
  qa_extractive: ["exact_match", "f1"],
  object_detection: ["map_50", "map_75", "map_50_95", "recall"],
  segmentation: ["mean_iou", "dice", "pixel_accuracy"],
  keypoints: ["oks", "pck"],
  image_generation: ["psnr", "ssim", "mse", "fid", "is", "clip_score", "lpips", "niqe"],
  audio_generation: ["snr", "mse", "mel_lsd", "nisqa", "pesq", "si_sdr"],
  retrieval: ["ndcg_k", "ndcg_5", "ndcg_10", "ndcg_20", "mrr", "recall_k", "recall_5", "recall_10", "recall_20"],
  clustering: ["adjusted_rand_index", "normalized_mutual_info", "adjusted_mutual_info", "v_measure"]
};

const TASK_TYPE_COLUMNS = {
  classification: ["id", "label"],
  probabilistic: ["id", "label"],
  regression: ["id", "value"],
  ner_tagging: ["id", "labels"],
  translation_summ: ["id", "text"],
  qa_extractive: ["id", "answer"],
  object_detection: ["id", "boxes"],
  segmentation: ["id", "mask"],
  keypoints: ["id", "keypoints"],
  image_generation: ["id", "image"],
  audio_generation: ["id", "audio"],
  retrieval: ["query_id", "doc_id"],
  clustering: ["id", "cluster_id"]
};

const getTaskTypeSchemasHelp = (t) => ({
  classification: {
    name: t('admin.tasks.modality_group.classification'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "label", type: "integer/string", desc: t('admin.tasks.schemas.classification.label') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "label", type: "integer/string", desc: t('admin.tasks.schemas.classification.gt_label') }
    ]
  },
  probabilistic: {
    name: t('admin.tasks.modality_group.probabilistic'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "score", type: "float", desc: t('admin.tasks.schemas.probabilistic.score') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "label", type: "integer (0 or 1)", desc: t('admin.tasks.schemas.probabilistic.gt_label') }
    ]
  },
  regression: {
    name: t('admin.tasks.modality_group.regression'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "value", type: "float", desc: t('admin.tasks.schemas.regression.value') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "value", type: "float", desc: t('admin.tasks.schemas.regression.gt_value') }
    ]
  },
  ner_tagging: {
    name: t('admin.tasks.modality_group.ner_tagging'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "labels", type: "list of strings", desc: t('admin.tasks.schemas.ner_tagging.labels') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "labels", type: "list of strings", desc: t('admin.tasks.schemas.ner_tagging.gt_labels') }
    ]
  },
  translation_summ: {
    name: t('admin.tasks.modality_group.translation_summ'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "text", type: "string", desc: t('admin.tasks.schemas.translation_summ.text') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "text", type: "string", desc: t('admin.tasks.schemas.translation_summ.gt_text') }
    ]
  },
  qa_extractive: {
    name: t('admin.tasks.modality_group.qa_extractive'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "answer", type: "string", desc: t('admin.tasks.schemas.qa_extractive.answer') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "answer", type: "string", desc: t('admin.tasks.schemas.qa_extractive.gt_answer') }
    ]
  },
  object_detection: {
    name: t('admin.tasks.modality_group.object_detection'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "boxes", type: "list of structs", desc: t('admin.tasks.schemas.object_detection.boxes') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "boxes", type: "list of structs", desc: t('admin.tasks.schemas.object_detection.gt_boxes') }
    ]
  },
  segmentation: {
    name: t('admin.tasks.modality_group.segmentation'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "mask", type: "binary/bytes", desc: t('admin.tasks.schemas.segmentation.mask') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "mask", type: "binary/bytes", desc: t('admin.tasks.schemas.segmentation.gt_mask') }
    ]
  },
  keypoints: {
    name: t('admin.tasks.modality_group.keypoints'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "keypoints", type: "list of coordinate pairs", desc: t('admin.tasks.schemas.keypoints.keypoints') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "keypoints", type: "list of coordinate pairs", desc: t('admin.tasks.schemas.keypoints.gt_keypoints') }
    ]
  },
  image_generation: {
    name: t('admin.tasks.modality_group.image_generation'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "image", type: "binary/bytes", desc: t('admin.tasks.schemas.image_generation.image') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "image", type: "binary/bytes", desc: t('admin.tasks.schemas.image_generation.gt_image') }
    ]
  },
  audio_generation: {
    name: t('admin.tasks.modality_group.audio_generation'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "audio", type: "binary/bytes", desc: t('admin.tasks.schemas.audio_generation.audio') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "audio", type: "binary/bytes", desc: t('admin.tasks.schemas.audio_generation.gt_audio') }
    ]
  },
  retrieval: {
    name: t('admin.tasks.modality_group.retrieval'),
    sub_cols: [
      { name: "query_id", type: "integer/string", desc: t('admin.tasks.schemas.common.query_id_desc') },
      { name: "doc_id", type: "integer/string", desc: t('admin.tasks.schemas.retrieval.doc_id') },
      { name: "score", type: "float", desc: t('admin.tasks.schemas.retrieval.score') }
    ],
    label_cols: [
      { name: "query_id", type: "integer/string", desc: t('admin.tasks.schemas.common.query_id_desc') },
      { name: "doc_id", type: "integer/string", desc: t('admin.tasks.schemas.retrieval.gt_doc_id') }
    ]
  },
  clustering: {
    name: t('admin.tasks.modality_group.clustering'),
    sub_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_matching') },
      { name: "cluster_id", type: "integer/string", desc: t('admin.tasks.schemas.clustering.cluster_id') }
    ],
    label_cols: [
      { name: "id", type: "integer/string", desc: t('admin.tasks.schemas.common.id_desc') },
      { name: "label", type: "integer/string", desc: t('admin.tasks.schemas.clustering.gt_label') }
    ]
  }
});

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
    task_type: '',
    ram_limit_mb: '',
    time_limit_sec: '',
    gpu_required: true,
    base_docker_image: '',
    apt_packages: '',
    pip_requirements: '',
    require_submit_tag: false,
    ban_magic_commands: false,
    banned_imports: '',
    whitelisted_imports: '',
    metrics_config: '',
    hf_train_repo: '',
    hf_eval_repo: '',
    hf_datasets_raw: '',
    hf_models_raw: '',
    hf_api_key: '',
    public_eval_percentage: 30,
    max_submissions_per_period: '',
    submission_period_hours: '',
    stage_id: ''
  });

  // Task Upload Files
  const [taskFiles, setTaskFiles] = useState([]);
  const [baselineFile, setBaselineFile] = useState(null);

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
      task_type: '',
      ram_limit_mb: '',
      time_limit_sec: '',
      gpu_required: true,
      base_docker_image: '',
      apt_packages: '',
      pip_requirements: '',
      require_submit_tag: false,
      ban_magic_commands: false,
      banned_imports: '',
      whitelisted_imports: '',
      metrics_config: '{"accuracy": {"weight": 1.0, "higher_is_better": true}}',
      hf_train_repo: '',
      hf_eval_repo: '',
      hf_datasets_raw: '',
      hf_models_raw: '',
      hf_api_key: '',
      public_eval_percentage: 30,
      max_submissions_per_period: '',
      submission_period_hours: '',
      stage_id: ''
    });
    setTaskFiles([]);
    setBaselineFile(null);
    setIsCreatingTask(true);
  };

  const initEditTask = (task) => {
    setTaskForm({
      title: task.title || '',
      description: task.description || '',
      task_type: task.task_type || '',
      ram_limit_mb: task.ram_limit_mb !== null ? task.ram_limit_mb : '',
      time_limit_sec: task.time_limit_sec !== null ? task.time_limit_sec : '',
      gpu_required: task.gpu_required !== null ? task.gpu_required : true,
      base_docker_image: task.base_docker_image || '',
      apt_packages: task.apt_packages || '',
      pip_requirements: task.pip_requirements || '',
      require_submit_tag: task.require_submit_tag || false,
      ban_magic_commands: task.ban_magic_commands || false,
      banned_imports: task.banned_imports || '',
      whitelisted_imports: task.whitelisted_imports || '',
      metrics_config: task.metrics_config ? JSON.stringify(task.metrics_config) : '',
      hf_train_repo: task.hf_train_repo || '',
      hf_eval_repo: task.hf_eval_repo || '',
      hf_datasets_raw: task.hf_datasets ? (Array.isArray(task.hf_datasets) ? task.hf_datasets.join(', ') : '') : '',
      hf_models_raw: task.hf_models ? (Array.isArray(task.hf_models) ? task.hf_models.join(', ') : '') : '',
      hf_api_key: '', // Keep empty for input security
      public_eval_percentage: task.public_eval_percentage || 30,
      max_submissions_per_period: task.max_submissions_per_period !== null ? task.max_submissions_per_period : '',
      submission_period_hours: task.submission_period_hours !== null ? task.submission_period_hours : '',
      stage_id: task.stage_id !== null && task.stage_id !== undefined ? task.stage_id.toString() : ''
    });
    setEditingTask(task);
    setTaskFiles([]);
    setBaselineFile(null);
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
    formData.append("task_type", taskForm.task_type || '');
    let cleanMetricsConfig = taskForm.metrics_config;
    try {
      const parsed = JSON.parse(taskForm.metrics_config);
      if (parsed && typeof parsed === 'object') {
        Object.keys(parsed).forEach(k => {
          if (parsed[k] && parsed[k].options_raw !== undefined) {
            delete parsed[k].options_raw;
          }
        });
        cleanMetricsConfig = JSON.stringify(parsed);
      }
    } catch (e) {}
    formData.append("metrics_config", cleanMetricsConfig);
    
    formData.append("hf_train_repo", taskForm.hf_train_repo);
    formData.append("hf_eval_repo", taskForm.hf_eval_repo);
    if (taskForm.hf_api_key) formData.append("hf_api_key", taskForm.hf_api_key);
    formData.append("public_eval_percentage", taskForm.public_eval_percentage);
    
    formData.append("whitelisted_imports", taskForm.whitelisted_imports);
    const datasetsArray = taskForm.hf_datasets_raw 
      ? taskForm.hf_datasets_raw.split(',').map(s => s.trim()).filter(Boolean) 
      : [];
    formData.append("hf_datasets", JSON.stringify(datasetsArray));

    const modelsArray = taskForm.hf_models_raw 
      ? taskForm.hf_models_raw.split(',').map(s => s.trim()).filter(Boolean) 
      : [];
    formData.append("hf_models", JSON.stringify(modelsArray));
    
    if (taskForm.max_submissions_per_period) formData.append("max_submissions_per_period", taskForm.max_submissions_per_period);
    if (taskForm.submission_period_hours) formData.append("submission_period_hours", taskForm.submission_period_hours);
    if (taskForm.stage_id !== undefined && taskForm.stage_id !== null) formData.append("stage_id", taskForm.stage_id);

    // Regular task resource files (up to 5)
    taskFiles.forEach((file, idx) => {
      formData.append(`file_${idx}`, file);
    });

    // Special uploads
    if (baselineFile) formData.append("baseline_notebook", baselineFile);

    return formData;
  };

  // Submit Task Creation
  const handleSaveCreateTask = async (e) => {
    e.preventDefault();
    if (!selectedChallenge) return;
    if (!taskForm.task_type) {
      showToast("Please select a Task Type / Modality Group.", 'rose');
      return;
    }
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
    if (!taskForm.task_type) {
      showToast("Please select a Task Type / Modality Group.", 'rose');
      return;
    }
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
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <InputField 
                      label={t('admin.tasks.banned_libraries')} 
                      value={taskForm.banned_imports} 
                      onChange={(e) => setTaskForm({ ...taskForm, banned_imports: e.target.value })} 
                      placeholder={t('admin.tasks.banned_libraries_placeholder')}
                    />
                    <InputField 
                      label={t('admin.tasks.whitelisted_libraries_label')} 
                      value={taskForm.whitelisted_imports} 
                      onChange={(e) => setTaskForm({ ...taskForm, whitelisted_imports: e.target.value })} 
                      placeholder={t('admin.tasks.whitelisted_libraries_placeholder')}
                    />
                  </div>
                </div>
              </div>

              {/* Section E: Data Integration (Hugging Face) */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">{t('admin.tasks.hf_dataset_metrics')}</h3>
                <div className="flex flex-col gap-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <InputField 
                      label={t('admin.tasks.hf_datasets_label')} 
                      value={taskForm.hf_datasets_raw} 
                      onChange={(e) => setTaskForm({ ...taskForm, hf_datasets_raw: e.target.value })} 
                      placeholder={t('admin.tasks.hf_datasets_placeholder')}
                    />
                    <InputField 
                      label={t('admin.tasks.hf_models_label')} 
                      value={taskForm.hf_models_raw} 
                      onChange={(e) => setTaskForm({ ...taskForm, hf_models_raw: e.target.value })} 
                      placeholder={t('admin.tasks.hf_models_placeholder')}
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
                  <div className="flex flex-col gap-1">
                    <label htmlFor="task-type-select" className="text-xs font-semibold text-slate-300">{t('admin.tasks.task_type_label')}</label>
                    <select
                      id="task-type-select"
                      value={taskForm.task_type || ''}
                      onChange={(e) => {
                        const newType = e.target.value;
                        let defaultMetrics = "";
                        if (newType && TASK_TYPE_METRICS[newType]) {
                          const firstMetric = TASK_TYPE_METRICS[newType][0];
                          defaultMetrics = JSON.stringify({ [firstMetric]: { weight: 1.0 } });
                        }
                        setTaskForm({ ...taskForm, task_type: newType, metrics_config: defaultMetrics });
                      }}
                      className="text-xs text-slate-200 border border-white/5 p-2 bg-slate-950 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    >
                      <option value="">{t('admin.tasks.select_modality_group')}</option>
                      <option value="classification">{t('admin.tasks.modality_group.classification')}</option>
                      <option value="probabilistic">{t('admin.tasks.modality_group.probabilistic')}</option>
                      <option value="regression">{t('admin.tasks.modality_group.regression')}</option>
                      <option value="ner_tagging">{t('admin.tasks.modality_group.ner_tagging')}</option>
                      <option value="translation_summ">{t('admin.tasks.modality_group.translation_summ')}</option>
                      <option value="qa_extractive">{t('admin.tasks.modality_group.qa_extractive')}</option>
                      <option value="object_detection">{t('admin.tasks.modality_group.object_detection')}</option>
                      <option value="segmentation">{t('admin.tasks.modality_group.segmentation')}</option>
                      <option value="keypoints">{t('admin.tasks.modality_group.keypoints')}</option>
                      <option value="image_generation">{t('admin.tasks.modality_group.image_generation')}</option>
                      <option value="audio_generation">{t('admin.tasks.modality_group.audio_generation')}</option>
                      <option value="retrieval">{t('admin.tasks.modality_group.retrieval')}</option>
                      <option value="clustering">{t('admin.tasks.modality_group.clustering')}</option>
                    </select>
                  </div>

                  {taskForm.task_type && TASK_TYPE_METRICS[taskForm.task_type] && (() => {
                    let metricsObj = {};
                    try { metricsObj = JSON.parse(taskForm.metrics_config) || {}; } catch(e) {}
                    const selectedCount = Object.keys(metricsObj).length;

                    return (
                      <div data-testid="modality-metrics-config" className="flex flex-col gap-2 border border-white/5 p-3 bg-slate-950 rounded-lg">
                        <div className="flex justify-between items-center">
                          <span className="text-xs font-semibold text-indigo-400">{t('admin.tasks.modality_metrics_title')}</span>
                          <span className="text-[10px] text-slate-400 font-medium">{t('admin.tasks.modality_metrics_selected', { count: selectedCount })}</span>
                        </div>
                        {selectedCount >= 5 && (
                          <span className="text-[10px] text-amber-500 font-semibold mt-0.5">{t('admin.tasks.modality_metrics_limit_reached')}</span>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-1">
                          {TASK_TYPE_METRICS[taskForm.task_type].map((mName) => {
                            const isChecked = mName in metricsObj;
                            const currentWeight = isChecked ? (metricsObj[mName].weight !== undefined ? metricsObj[mName].weight : 1.0) : 1.0;

                            return (
                              <div key={mName} className={`flex flex-col gap-2 p-2.5 rounded border border-white/5 bg-slate-900/50 ${(!isChecked && selectedCount >= 5) ? 'opacity-40' : ''}`}>
                                <div className="flex items-center justify-between w-full">
                                  <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                                    <input
                                      type="checkbox"
                                      checked={isChecked}
                                      disabled={!isChecked && selectedCount >= 5}
                                      onChange={(e) => {
                                        let updatedObj = { ...metricsObj };
                                        if (e.target.checked) {
                                          let defaultOpts = {};
                                          if (mName === 'chrf') {
                                            defaultOpts = { beta: 3 };
                                          } else if (mName === 'pck') {
                                            defaultOpts = { threshold: 0.05 };
                                          } else if (mName === 'ndcg_k' || mName === 'recall_k') {
                                            defaultOpts = { k: 10 };
                                          }
                                          updatedObj[mName] = { weight: 1.0, options: defaultOpts };
                                        } else {
                                          delete updatedObj[mName];
                                        }
                                        setTaskForm({ ...taskForm, metrics_config: JSON.stringify(updatedObj) });
                                      }}
                                      className="accent-indigo-600 rounded disabled:cursor-not-allowed"
                                    />
                                    <span>{formatMetricName(mName)}</span>
                                  </label>
                                  {isChecked && (
                                    <div className="flex items-center gap-1">
                                      <span className="text-[10px] text-slate-400">{t('admin.tasks.modality_metrics_weight')}</span>
                                      <input
                                        type="number"
                                        step="0.1"
                                        min="0"
                                        value={currentWeight}
                                        onChange={(e) => {
                                          let updatedObj = { ...metricsObj };
                                          if (updatedObj[mName]) {
                                            updatedObj[mName].weight = parseFloat(e.target.value) || 0;
                                          }
                                          setTaskForm({ ...taskForm, metrics_config: JSON.stringify(updatedObj) });
                                        }}
                                        className="w-16 text-center text-xs bg-slate-950 border border-white/5 rounded text-slate-200 p-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                      />
                                    </div>
                                  )}
                                </div>
                                {isChecked && (
                                  (mName === 'chrf' || mName === 'pck' || mName === 'ndcg_k' || mName === 'recall_k') && (
                                    <div className="flex flex-col gap-1 pl-5 border-t border-white/5 pt-1.5 mt-0.5">
                                      {mName === 'chrf' && (
                                        <div className="flex items-center justify-between w-full">
                                          <span className="text-[10px] text-slate-400">{t('admin.tasks.modality_metrics_beta', 'Beta')}</span>
                                          <select
                                            aria-label="Beta"
                                            value={metricsObj[mName].options?.beta ?? 3}
                                            onChange={(e) => {
                                              let updatedObj = { ...metricsObj };
                                              if (updatedObj[mName]) {
                                                updatedObj[mName].options = {
                                                  ...updatedObj[mName].options,
                                                  beta: parseInt(e.target.value) || 3
                                                };
                                              }
                                              setTaskForm({ ...taskForm, metrics_config: JSON.stringify(updatedObj) });
                                            }}
                                            className="w-20 text-center text-xs bg-slate-950 border border-white/5 rounded text-slate-200 p-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                          >
                                            <option value="1">1</option>
                                            <option value="2">2</option>
                                            <option value="3">3</option>
                                          </select>
                                        </div>
                                      )}
                                      {mName === 'pck' && (
                                        <div className="flex items-center justify-between w-full">
                                          <span className="text-[10px] text-slate-400">{t('admin.tasks.modality_metrics_threshold', 'Threshold')}</span>
                                          <select
                                            aria-label="Threshold"
                                            value={metricsObj[mName].options?.threshold ?? 0.05}
                                            onChange={(e) => {
                                              let updatedObj = { ...metricsObj };
                                              if (updatedObj[mName]) {
                                                updatedObj[mName].options = {
                                                  ...updatedObj[mName].options,
                                                  threshold: parseFloat(e.target.value) || 0.05
                                                };
                                              }
                                              setTaskForm({ ...taskForm, metrics_config: JSON.stringify(updatedObj) });
                                            }}
                                            className="w-20 text-center text-xs bg-slate-950 border border-white/5 rounded text-slate-200 p-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                          >
                                            <option value="0.01">0.01</option>
                                            <option value="0.02">0.02</option>
                                            <option value="0.05">0.05</option>
                                            <option value="0.1">0.1</option>
                                            <option value="0.15">0.15</option>
                                            <option value="0.2">0.2</option>
                                          </select>
                                        </div>
                                      )}
                                      {(mName === 'ndcg_k' || mName === 'recall_k') && (
                                        <div className="flex items-center justify-between w-full">
                                          <span className="text-[10px] text-slate-400">{t('admin.tasks.modality_metrics_k', 'K')}</span>
                                          <select
                                            aria-label="K"
                                            value={metricsObj[mName].options?.k ?? 10}
                                            onChange={(e) => {
                                              let updatedObj = { ...metricsObj };
                                              if (updatedObj[mName]) {
                                                updatedObj[mName].options = {
                                                  ...updatedObj[mName].options,
                                                  k: parseInt(e.target.value) || 10
                                                };
                                              }
                                              setTaskForm({ ...taskForm, metrics_config: JSON.stringify(updatedObj) });
                                            }}
                                            className="w-20 text-center text-xs bg-slate-950 border border-white/5 rounded text-slate-200 p-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                          >
                                            <option value="5">5</option>
                                            <option value="10">10</option>
                                            <option value="20">20</option>
                                            <option value="50">50</option>
                                            <option value="100">100</option>
                                          </select>
                                        </div>
                                      )}
                                    </div>
                                  )
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}

                  {taskForm.task_type && getTaskTypeSchemasHelp(t)[taskForm.task_type] && (() => {
                    const help = getTaskTypeSchemasHelp(t)[taskForm.task_type];
                    return (
                      <div className="flex flex-col gap-3 border border-white/5 p-4 bg-slate-950 rounded-lg">
                        <span className="text-xs font-semibold text-indigo-400">{t('admin.tasks.modality_schemas_title')}</span>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-1">
                          <div className="flex flex-col gap-2 p-3 rounded-lg border border-white/5 bg-slate-900/40">
                            <span className="text-xs font-bold text-slate-200">📦 {t('admin.tasks.modality_schemas_submission')}</span>
                            <div className="flex flex-col gap-1.5 mt-1 animate-fadein">
                              {help.sub_cols.map(c => (
                                <div key={c.name} className="flex flex-col text-[11px] border-b border-white/5 pb-1 last:border-b-0">
                                  <div className="flex justify-between">
                                    <code className="text-indigo-300 font-bold">{c.name}</code>
                                    <span className="text-slate-400 italic">({c.type})</span>
                                  </div>
                                  <span className="text-slate-300 mt-0.5">{c.desc}</span>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="flex flex-col gap-2 p-3 rounded-lg border border-white/5 bg-slate-900/40">
                            <span className="text-xs font-bold text-slate-200">🎯 {t('admin.tasks.modality_schemas_ground_truth')}</span>
                            <div className="flex flex-col gap-1.5 mt-1 animate-fadein">
                              {help.label_cols.map(c => (
                                <div key={c.name} className="flex flex-col text-[11px] border-b border-white/5 pb-1 last:border-b-0">
                                  <div className="flex justify-between">
                                    <code className="text-indigo-300 font-bold">{c.name}</code>
                                    <span className="text-slate-400 italic">({c.type})</span>
                                  </div>
                                  <span className="text-slate-300 mt-0.5">{c.desc}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                        <div className="text-[11px] text-slate-400 mt-1">
                          {t('admin.tasks.modality_schemas_note')}
                        </div>
                      </div>
                    );
                  })()}
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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  
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
          <ChallengeConfig
            handleCreateChallenge={handleCreateChallenge}
            newChallenge={newChallenge}
            setNewChallenge={setNewChallenge}
            timezones={TIMEZONES}
          />
        )}

        {/* 4. COMPETITOR REGISTRATION MODULE (JURY/ADMIN) */}
        {adminSubTab === 'competitor-reg' && (
          <CompetitorManager
            editingUser={editingUser}
            setEditingUser={setEditingUser}
            editUserForm={editUserForm}
            setEditUserForm={setEditUserForm}
            handleUpdateUserSubmit={handleUpdateUserSubmit}
            challenges={challenges}
            isEditDisabled={isEditDisabled}
            newCompetitor={newCompetitor}
            setNewCompetitor={setNewCompetitor}
            handleRegisterCompetitor={handleRegisterCompetitor}
            isManualRegisterDisabled={isManualRegisterDisabled}
            generatedCredentials={generatedCredentials}
            csvChallengeId={csvChallengeId}
            setCsvChallengeId={setCsvChallengeId}
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
          />
        )}

        {/* 5. DATABASE BACKUP MANAGEMENT */}
        {adminSubTab === 'backups' && currentUser.role === 'admin' && (
          <BackupManager handleDownloadBackup={handleDownloadBackup} />
        )}

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
          />
        )}

        {/* 7. WORKERS MONITORING MODULE */}
        {adminSubTab === 'workers-stats' && (currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <WorkersStats
            workerStats={workerStats}
            workerStatsLoading={workerStatsLoading}
            workerStatsError={workerStatsError}
            fetchWorkerStats={fetchWorkerStats}
            formatUptime={formatUptime}
          />
        )}

      </div>
    </div>
  );
}
