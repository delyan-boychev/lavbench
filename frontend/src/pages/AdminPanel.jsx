import React, { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { useApp } from '../context/AppContext';
import InputField from '../components/ui/InputField';
import Button from '../components/ui/Button';
import SelectField from '../components/ui/SelectField';
import Pagination from '../components/ui/Pagination';

export default function AdminPanel() {
  const { token, currentUser } = useAuth();
  const { 
    challenges, 
    selectedChallenge, 
    setSelectedChallengeById, 
    fetchChallenges, 
    showToast 
  } = useApp();

  const API_BASE = '/api';

  // Sub tab navigation
  const [adminSubTab, setAdminSubTab] = useState('competition-mgmt');

  const formatDateTimeLocal = (dateStr) => {
    if (!dateStr) return '';
    return dateStr.substring(0, 16);
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
    freeze_time: ''
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
    submission_period_hours: ''
  });

  // Task Upload Files
  const [taskFiles, setTaskFiles] = useState([]);
  const [evaluatorFile, setEvaluatorFile] = useState(null);
  const [baselineFile, setBaselineFile] = useState(null);
  const [solutionFile, setSolutionFile] = useState(null);

  // Manual Competitor Register State
  const [newCompetitor, setNewCompetitor] = useState({
    name: '',
    surname: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: ''
  });
  const [generatedCredentials, setGeneratedCredentials] = useState(null);

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
    challenge_id: ''
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
    challenge_id: ''
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
        showToast('Competition created successfully!');
        setNewChallenge({
          title: '',
          description: '',
          max_eval_requests: 10,
          ram_limit_mb: 8192,
          time_limit_sec: 300,
          gpu_required: true,
          start_time: '',
          end_time: '',
          freeze_time: ''
        });
        fetchChallenges();
        fetchPaginatedChallenges();
        setAdminSubTab('competition-mgmt');
      } else {
        showToast(data.error || 'Failed to create competition.', 'rose');
      }
    } catch (err) {
      showToast('Network error creating competition.', 'rose');
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
        showToast('Competition updated successfully!');
        fetchChallenges();
        fetchPaginatedChallenges();
        return { success: true };
      } else {
        showToast(data.error || 'Failed to update competition.', 'rose');
        return { success: false };
      }
    } catch (err) {
      showToast('Network error updating competition.', 'rose');
      return { success: false };
    }
  };

  // Handle Competition delete
  const handleDeleteChallenge = async (id, title) => {
    if (!window.confirm(`Are you sure you want to permanently delete competition "${title}"? This deletes all associated tasks, submissions and pseudonyms.`)) {
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Competition "${title}" deleted.`);
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || 'Failed to delete competition.', 'rose');
      }
    } catch (err) {
      showToast('Network error deleting competition.', 'rose');
    }
  };

  // Handle finalize scores
  const handleFinalize = async (id) => {
    if (!window.confirm("Finalize scores? This reveals private scores and real names on the leaderboard.")) return;
    try {
      const res = await fetch(`${API_BASE}/challenges/${id}/finalize`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        showToast("Scores finalized and de-anonymized!");
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || "Failed to finalize scores.", "rose");
      }
    } catch (e) {
      showToast("Network error finalising scores.", "rose");
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
        showToast(data.message);
        fetchChallenges();
        fetchPaginatedChallenges();
      } else {
        showToast(data.error || "Failed to archive challenge.", "rose");
      }
    } catch (e) {
      showToast("Network error.", "rose");
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
      submission_period_hours: ''
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
      submission_period_hours: task.submission_period_hours !== null ? task.submission_period_hours : ''
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

    // Regular task resource files (up to 5)
    taskFiles.forEach((file, idx) => {
      formData.append(`file_${idx}`, file);
    });

    // Special uploads
    if (evaluatorFile) formData.append("evaluator_script", evaluatorFile);
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
        showToast('Task created successfully!');
        fetchChallenges();
        setIsCreatingTask(false);
      } else {
        showToast(data.error || 'Failed to create task.', 'rose');
      }
    } catch (err) {
      showToast('Network error creating task.', 'rose');
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
        showToast('Task updated successfully!');
        fetchChallenges();
        setEditingTask(null);
      } else {
        showToast(data.error || 'Failed to update task.', 'rose');
      }
    } catch (err) {
      showToast('Network error updating task.', 'rose');
    }
  };

  // Delete Task
  const handleDeleteTask = async (taskId, title) => {
    if (!window.confirm(`Permanently delete task "${title}"? This deletes all submissions.`)) return;
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        showToast(`Task "${title}" deleted.`);
        fetchChallenges();
      } else {
        const data = await res.json();
        showToast(data.error || 'Failed to delete task.', 'rose');
      }
    } catch (e) {
      showToast('Network error.', 'rose');
    }
  };

  // Manual Competitor Registration
  const handleRegisterCompetitor = async (e) => {
    e.preventDefault();
    if (!newCompetitor.challenge_id) {
      showToast('Select a target competition.', 'rose');
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
        setNewCompetitor({ name: '', surname: '', grade: '', school: '', city: '', challenge_id: '' });
        showToast('Competitor registered!');
        fetchCompetitors();
      } else {
        showToast(data.error || 'Failed to register.', 'rose');
      }
    } catch {
      showToast('Network error.', 'rose');
    }
  };

  // User Administration Registration
  const handleRegisterUser = async (e) => {
    e.preventDefault();
    if (newUser.role === 'competitor' && !newUser.challenge_id) {
      showToast('Select a target competition for competitor role.', 'rose');
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
        showToast('User registered successfully!');
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
          challenge_id: ''
        });
        fetchUsers();
      } else {
        showToast(data.error || 'Failed to register user.', 'rose');
      }
    } catch {
      showToast('Network error.', 'rose');
    }
  };

  // Delete User
  const handleDeleteUser = async (userId, username) => {
    if (!window.confirm(`Permanently delete user "${username}"? All submissions are deleted.`)) return;
    try {
      const res = await fetch(`${API_BASE}/admin/users/${userId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        showToast(`User "${username}" deleted.`);
        fetchUsers();
      } else {
        const data = await res.json();
        showToast(data.error || 'Failed to delete user.', 'rose');
      }
    } catch {
      showToast('Network error.', 'rose');
    }
  };

  // CSV Competitors Import
  const handleCSVImport = async (e) => {
    e.preventDefault();
    if (!csvChallengeId) {
      showToast('Select target competition.', 'rose');
      return;
    }
    if (!csvFile) {
      showToast('Select a CSV file.', 'rose');
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
        showToast(`Imported ${data.competitors?.length || 0} competitors successfully!`);
        setImportedCompetitors(data.competitors || []);
        setCsvFile(null);
        fetchCompetitors();
      } else {
        showToast(data.error || 'Failed to import CSV.', 'rose');
      }
    } catch {
      showToast('Network error.', 'rose');
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
        showToast(errData.error || 'Backup failed.', 'rose');
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
      showToast('Backup SQL downloaded.');
    } catch {
      showToast('Backup failed.', 'rose');
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
        showToast(errData.error || 'Failed to download scores.', 'rose');
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
      showToast('Scores CSV downloaded.');
    } catch {
      showToast('Failed to download scores.', 'rose');
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
        showToast(errData.error || 'Failed to download submissions.', 'rose');
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
      showToast('Submissions ZIP downloaded.');
    } catch {
      showToast('Failed to download submissions.', 'rose');
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
      challenge_id: user.challenge_id ? user.challenge_id.toString() : ''
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
          challenge_id: editUserForm.challenge_id === "" ? "" : parseInt(editUserForm.challenge_id)
        })
      });
      const data = await res.json();
      if (res.ok) {
        showToast('Competitor updated successfully!');
        setEditingUser(null);
        fetchUsers();
        fetchCompetitors();
      } else {
        showToast(data.error || 'Failed to update competitor.', 'rose');
      }
    } catch {
      showToast('Network error updating competitor.', 'rose');
    }
  };

  const filteredUsers = allUsers;
  const fontFilteredCompetitors = competitorsList; // keep simple naming
  const filteredCompetitors = competitorsList;

  // Render components
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start animate-fadein">
      
      {/* Sidebar Control Submenu */}
      <div className="bg-[#0d0e18] border border-white/5 p-5 rounded-2xl flex flex-col gap-1.5">
        <h2 className="text-xs font-extrabold uppercase text-slate-400 tracking-wider mb-3 px-2">Jury Control Hub</h2>
        
        {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <button 
            onClick={() => { setAdminSubTab('competition-mgmt'); setIsCreatingTask(false); setEditingTask(null); }}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'competition-mgmt' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Manage Competitions & Tasks
          </button>
        )}

        {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <button 
            onClick={() => setAdminSubTab('challenge-config')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'challenge-config' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Create Competition
          </button>
        )}
        
        <button 
          onClick={() => setAdminSubTab('competitor-reg')}
          className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'competitor-reg' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          Competitor Registrations
        </button>

        {currentUser.role === 'admin' && (
          <button 
            onClick={() => setAdminSubTab('backups')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'backups' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Database Backup
          </button>
        )}

        {currentUser.role === 'admin' && (
          <button 
            onClick={() => setAdminSubTab('user-management')}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${adminSubTab === 'user-management' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            User Management
          </button>
        )}
      </div>

      {/* Main Workspace Work Areas */}
      <div className="lg:col-span-3">

        {/* 1. COMPETITION & TASK CONFIGURATION */}
        {adminSubTab === 'competition-mgmt' && !isCreatingTask && !editingTask && (
          <div className="flex flex-col gap-6">
            
            {editingChallenge ? (
              <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                <div className="flex justify-between items-center mb-6">
                  <h2 className="text-xl font-bold text-white">Edit Competition: {editingChallenge.title}</h2>
                  <button 
                    onClick={() => setEditingChallenge(null)}
                    className="text-xs font-bold text-rose-400 hover:underline bg-transparent border-0 cursor-pointer"
                  >
                    Cancel
                  </button>
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
                    label="Title" 
                    value={editingChallenge.title} 
                    onChange={(e) => setEditingChallenge({ ...editingChallenge, title: e.target.value })} 
                    required 
                  />
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-slate-300">Description</label>
                    <textarea 
                      rows="4" 
                      className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-sm font-sans"
                      value={editingChallenge.description} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, description: e.target.value })} 
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <InputField 
                      label="Max Daily Submissions" 
                      type="number"
                      value={editingChallenge.max_eval_requests} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, max_eval_requests: parseInt(e.target.value) })} 
                      required 
                    />
                    <InputField 
                      label="RAM Limit (MB)" 
                      type="number"
                      value={editingChallenge.ram_limit_mb} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, ram_limit_mb: parseInt(e.target.value) })} 
                      required 
                    />
                    <InputField 
                      label="Time Limit (sec)" 
                      type="number"
                      value={editingChallenge.time_limit_sec} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, time_limit_sec: parseInt(e.target.value) })} 
                      required 
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <InputField 
                      label="Start Time" 
                      type="datetime-local"
                      value={formatDateTimeLocal(editingChallenge.start_time)} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, start_time: e.target.value })} 
                    />
                    <InputField 
                      label="End Time" 
                      type="datetime-local"
                      value={formatDateTimeLocal(editingChallenge.end_time)} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, end_time: e.target.value })} 
                    />
                    <InputField 
                      label="Leaderboard Freeze Time" 
                      type="datetime-local"
                      value={formatDateTimeLocal(editingChallenge.freeze_time)} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, freeze_time: e.target.value })} 
                    />
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <input 
                      type="checkbox" 
                      id="edit-gpu"
                      checked={editingChallenge.gpu_required} 
                      onChange={(e) => setEditingChallenge({ ...editingChallenge, gpu_required: e.target.checked })}
                      className="accent-indigo-600 h-4 w-4"
                    />
                    <label htmlFor="edit-gpu" className="text-xs font-semibold text-slate-300">Requires GPU Sandbox Execution</label>
                  </div>
                  <div className="flex gap-3 mt-4">
                    <Button type="submit" variant="primary">Save Changes</Button>
                    <Button onClick={() => setEditingChallenge(null)} variant="secondary">Cancel</Button>
                  </div>
                </form>
              </div>
            ) : (
              <div className="flex flex-col gap-6">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h1 className="text-xl font-bold text-white">Active Competitions</h1>
                  <Button variant="primary" onClick={initCreateTask}>+ Add Task</Button>
                </div>
                
                {paginatedChallengesList.length === 0 ? (
                  <p className="text-xs text-slate-500 italic">No competitions created yet.</p>
                ) : (
                  paginatedChallengesList.map(c => (
                    <div key={c.id} className="bg-[#0d0e18] border border-white/5 p-6 rounded-2xl flex flex-col gap-4">
                      <div className="flex flex-wrap justify-between items-start gap-4">
                        <div>
                          <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            {c.title}
                            {c.is_archived && <span className="text-[10px] bg-slate-800 border border-white/5 text-slate-400 px-2 py-0.5 rounded-full font-bold">Archived</span>}
                          </h2>
                          <p className="text-xs text-slate-400 mt-1">{c.description || "No description provided."}</p>
                        </div>
                        
                        <div className="flex flex-wrap gap-2">
                          <Button variant="secondary" onClick={() => setEditingChallenge(c)}>Edit</Button>
                          <Button 
                            variant="secondary" 
                            onClick={() => handleArchiveToggle(c.id)}
                          >
                            {c.is_archived ? "Restore" : "Archive"}
                          </Button>
                          {c.scores_finalized ? (
                            <>
                              <span className="text-[10px] font-bold border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 px-2.5 py-1.5 rounded-lg flex items-center">Finalized</span>
                              <Button variant="accent" onClick={() => handleDownloadScores(c.id, c.title)}>
                                Download CSV Scores
                              </Button>
                              <Button variant="accent" onClick={() => handleDownloadSubmissionsZip(c.id, c.title)}>
                                Download Submissions ZIP
                              </Button>
                            </>
                          ) : (
                            <Button variant="primary" onClick={() => handleFinalize(c.id)}>Finalize standings</Button>
                          )}
                          <Button variant="danger" onClick={() => handleDeleteChallenge(c.id, c.title)}>Delete</Button>
                        </div>
                      </div>

                      <div className="border-t border-white/5 pt-4 mt-2">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Tasks in this Competition ({c.tasks ? c.tasks.length : 0})</h3>
                        {c.tasks?.length === 0 ? (
                          <p className="text-xs text-slate-500 italic">No tasks created yet.</p>
                        ) : (
                          <div className="flex flex-col gap-2">
                            {c.tasks?.map(t => (
                              <div key={t.id} className="flex justify-between items-center p-3.5 bg-slate-900/60 border border-white/5 rounded-xl text-xs">
                                <div>
                                  <span className="font-bold text-slate-200">{t.title}</span>
                                  <span className="text-[10px] text-slate-500 ml-2">Public Eval split: {t.public_eval_percentage || 30}%</span>
                                </div>
                                <div className="flex gap-2">
                                  <Button variant="secondary" onClick={() => initEditTask(t)}>Edit Config</Button>
                                  <Button variant="danger" onClick={() => handleDeleteTask(t.id, t.title)}>Delete</Button>
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

        {/* 2. TASK EDITING OR CREATION (The Sandbox + HF + Rules form) */}
        {(isCreatingTask || editingTask) && (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
            <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4">
              <h2 className="text-xl font-bold text-white">
                {isCreatingTask ? `Create Task under: ${selectedChallenge?.title}` : `Edit Task: ${editingTask?.title}`}
              </h2>
              <Button variant="secondary" onClick={() => { setIsCreatingTask(false); setEditingTask(null); }}>Cancel</Button>
            </div>
            
            <form onSubmit={isCreatingTask ? handleSaveCreateTask : handleSaveUpdateTask} className="flex flex-col gap-6">
              
              {/* Section A: General */}
              <div>
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">A. General Settings</h3>
                <div className="flex flex-col gap-4">
                  <InputField 
                    label="Task Title" 
                    value={taskForm.title} 
                    onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} 
                    required 
                  />
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-slate-300">Task Description (Supports Markdown)</label>
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
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">B. Sandbox Execution Overrides (Optional)</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <InputField 
                    label="Override RAM Limit (MB)" 
                    type="number" 
                    value={taskForm.ram_limit_mb} 
                    onChange={(e) => setTaskForm({ ...taskForm, ram_limit_mb: e.target.value })} 
                    placeholder="8192"
                  />
                  <InputField 
                    label="Override Timeout Limit (sec)" 
                    type="number" 
                    value={taskForm.time_limit_sec} 
                    onChange={(e) => setTaskForm({ ...taskForm, time_limit_sec: e.target.value })} 
                    placeholder="300"
                  />
                  <div className="flex items-center gap-2 h-full pt-6">
                    <input 
                      type="checkbox" 
                      id="task-gpu-req" 
                      checked={taskForm.gpu_required} 
                      onChange={(e) => setTaskForm({ ...taskForm, gpu_required: e.target.checked })} 
                      className="accent-indigo-600 h-4 w-4 cursor-pointer"
                    />
                    <label htmlFor="task-gpu-req" className="text-xs font-semibold text-slate-300 cursor-pointer">Requires GPU Worker Node</label>
                  </div>
                </div>
              </div>

              {/* Section C: Docker Environment */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">C. Granular Docker Environment Config</h3>
                <div className="flex flex-col gap-4">
                  <InputField 
                    label="Base Image" 
                    value={taskForm.base_docker_image} 
                    onChange={(e) => setTaskForm({ ...taskForm, base_docker_image: e.target.value })} 
                    placeholder="python:3.10-slim or pytorch/pytorch:2.0.0-cuda11.7-cudnn8-runtime"
                  />
                  <InputField 
                    label="APT System Packages (comma-separated)" 
                    value={taskForm.apt_packages} 
                    onChange={(e) => setTaskForm({ ...taskForm, apt_packages: e.target.value })} 
                    placeholder="libgl1-mesa-glx, ffmpeg, libgomp1"
                  />
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold text-slate-300">PIP Packages requirements.txt content</label>
                    <textarea 
                      rows="3" 
                      className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-xs font-mono"
                      value={taskForm.pip_requirements} 
                      onChange={(e) => setTaskForm({ ...taskForm, pip_requirements: e.target.value })} 
                      placeholder="scikit-learn&#10;opencv-python&#10;transformers"
                    />
                  </div>
                </div>
              </div>

              {/* Section D: Rules engine */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">D. AST Code Rule Engine</h3>
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap gap-6">
                    <div className="flex items-center gap-2">
                      <input 
                        type="checkbox" 
                        id="rule-tag"
                        checked={taskForm.require_submit_tag}
                        onChange={(e) => setTaskForm({ ...taskForm, require_submit_tag: e.target.checked })}
                        className="accent-indigo-600 h-4 w-4 cursor-pointer"
                      />
                      <label htmlFor="rule-tag" className="text-xs font-semibold text-slate-300 cursor-pointer">Require "# SUBMIT" comment block tag (Score 0 if missing)</label>
                    </div>
                    <div className="flex items-center gap-2">
                      <input 
                        type="checkbox" 
                        id="rule-magic"
                        checked={taskForm.ban_magic_commands}
                        onChange={(e) => setTaskForm({ ...taskForm, ban_magic_commands: e.target.checked })}
                        className="accent-indigo-600 h-4 w-4 cursor-pointer"
                      />
                      <label htmlFor="rule-magic" className="text-xs font-semibold text-slate-300 cursor-pointer">Ban Jupyter magic command symbols (!) or (%) (Score 0 if found)</label>
                    </div>
                  </div>
                  <InputField 
                    label="Banned Libraries list (comma-separated, checked via AST imports)" 
                    value={taskForm.banned_imports} 
                    onChange={(e) => setTaskForm({ ...taskForm, banned_imports: e.target.value })} 
                    placeholder="os, sys, subprocess, requests, urllib"
                  />
                </div>
              </div>

              {/* Section E: Data Integration (Hugging Face) */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">E. Hugging Face Dataset & Metrics config</h3>
                <div className="flex flex-col gap-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <InputField 
                      label="Public Train Dataset Repo" 
                      value={taskForm.hf_train_repo} 
                      onChange={(e) => setTaskForm({ ...taskForm, hf_train_repo: e.target.value })} 
                      placeholder="huggingface-user/my-public-train-set"
                    />
                    <InputField 
                      label="Private Evaluation Dataset Repo" 
                      value={taskForm.hf_eval_repo} 
                      onChange={(e) => setTaskForm({ ...taskForm, hf_eval_repo: e.target.value })} 
                      placeholder="huggingface-user/my-private-eval-set"
                    />
                  </div>
                  <InputField 
                    label="HF API Key Token (Securely Encrypted)" 
                    type="password"
                    value={taskForm.hf_api_key} 
                    onChange={(e) => setTaskForm({ ...taskForm, hf_api_key: e.target.value })} 
                    placeholder="hf_xxxxxxxxxxxxxxxxxxxxxx"
                  />
                  <div className="flex flex-col gap-2">
                    <label className="text-xs font-semibold text-slate-300">
                      Public Evaluation Split Percentage: <strong className="text-indigo-400">{taskForm.public_eval_percentage}%</strong>
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
                    label="Metrics Configuration (JSON format)" 
                    value={taskForm.metrics_config} 
                    onChange={(e) => setTaskForm({ ...taskForm, metrics_config: e.target.value })} 
                    placeholder='{"accuracy": {"weight": 1.0, "higher_is_better": true}}'
                  />
                </div>
              </div>

              {/* Section F: Optional Rate Limits */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">F. Optional Rate Limits</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <InputField 
                    label="Max Submissions limit" 
                    type="number"
                    value={taskForm.max_submissions_per_period} 
                    onChange={(e) => setTaskForm({ ...taskForm, max_submissions_per_period: e.target.value })} 
                    placeholder="e.g. 5"
                  />
                  <InputField 
                    label="Submission limit period (Hours)" 
                    type="number"
                    value={taskForm.submission_period_hours} 
                    onChange={(e) => setTaskForm({ ...taskForm, submission_period_hours: e.target.value })} 
                    placeholder="e.g. 24"
                  />
                </div>
              </div>

              {/* Section G: Config files */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">G. Upload Scripts & Notebooks</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  
                  {/* Evaluator script */}
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-slate-300">Evaluator script (evaluator.py)</label>
                    <input 
                      type="file" 
                      accept=".py" 
                      onChange={(e) => setEvaluatorFile(e.target.files[0])}
                      className="text-xs text-slate-400 border border-white/5 p-2 bg-slate-950 rounded-lg"
                    />
                  </div>

                  {/* Baseline Notebook */}
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-slate-300">Baseline Notebook (baseline.ipynb)</label>
                    <input 
                      type="file" 
                      accept=".ipynb" 
                      onChange={(e) => setBaselineFile(e.target.files[0])}
                      className="text-xs text-slate-400 border border-white/5 p-2 bg-slate-950 rounded-lg"
                    />
                  </div>

                  {/* Solution Notebook */}
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-slate-300">Solution Notebook (solution.ipynb)</label>
                    <input 
                      type="file" 
                      accept=".ipynb" 
                      onChange={(e) => setSolutionFile(e.target.files[0])}
                      className="text-xs text-slate-400 border border-white/5 p-2 bg-slate-950 rounded-lg"
                    />
                  </div>

                </div>
              </div>

              {/* Section H: Resource Files (Optional) */}
              <div className="border-t border-white/5 pt-6">
                <h3 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-3">H. Resource Files (Up to 5 files, Max 25MB each)</h3>
                
                {/* File list update */}
                {editingTask && editingTask.files && (
                  <div className="mb-4">
                    <span className="text-xs text-slate-400 block mb-2 font-semibold">Current resource files:</span>
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
                              {f.filename} ({Math.round(f.size_bytes / 1024)} KB)
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
                              {isDeleted ? "Undo Delete" : "Delete"}
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
                  <p className="text-[10px] text-slate-500">Press Cmd/Ctrl to choose multiple files.</p>
                </div>
              </div>

              <div className="flex gap-4 border-t border-white/5 pt-6 mt-4">
                <Button type="submit" variant="primary">
                  {isCreatingTask ? "Create Task" : "Save Changes"}
                </Button>
                <Button variant="secondary" onClick={() => { setIsCreatingTask(false); setEditingTask(null); }}>
                  Cancel
                </Button>
              </div>

            </form>
          </div>
        )}

        {/* 3. CREATE NEW COMPETITIONS */}
        {adminSubTab === 'challenge-config' && (currentUser.role === 'admin' || currentUser.role === 'jury') && (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
            <h2 className="text-xl font-bold text-white mb-6">Create New Competition Challenge</h2>
            <form onSubmit={handleCreateChallenge} className="flex flex-col gap-4">
              <InputField 
                label="Competition Title" 
                value={newChallenge.title} 
                onChange={(e) => setNewChallenge({ ...newChallenge, title: e.target.value })} 
                required 
              />
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-300">Description</label>
                <textarea 
                  rows="4" 
                  className="w-full px-3 py-2 bg-slate-900 border border-white/5 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all duration-200 text-sm font-sans"
                  value={newChallenge.description} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, description: e.target.value })} 
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <InputField 
                  label="Daily Limits (Submissions/day)" 
                  type="number"
                  value={newChallenge.max_eval_requests} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, max_eval_requests: parseInt(e.target.value) })} 
                  required 
                />
                <InputField 
                  label="RAM Limit override (MB)" 
                  type="number"
                  value={newChallenge.ram_limit_mb} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, ram_limit_mb: parseInt(e.target.value) })} 
                  required 
                />
                <InputField 
                  label="Time limit override (sec)" 
                  type="number"
                  value={newChallenge.time_limit_sec} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, time_limit_sec: parseInt(e.target.value) })} 
                  required 
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <InputField 
                  label="Start Time" 
                  type="datetime-local"
                  value={newChallenge.start_time} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, start_time: e.target.value })} 
                />
                <InputField 
                  label="End Time" 
                  type="datetime-local"
                  value={newChallenge.end_time} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, end_time: e.target.value })} 
                />
                <InputField 
                  label="Leaderboard Freeze Time" 
                  type="datetime-local"
                  value={newChallenge.freeze_time} 
                  onChange={(e) => setNewChallenge({ ...newChallenge, freeze_time: e.target.value })} 
                />
              </div>
              <div className="flex items-center gap-2 mt-2">
                <input 
                  type="checkbox" 
                  id="create-gpu-req" 
                  checked={newChallenge.gpu_required}
                  onChange={(e) => setNewChallenge({ ...newChallenge, gpu_required: e.target.checked })}
                  className="accent-indigo-600 h-4 w-4 cursor-pointer"
                />
                <label htmlFor="create-gpu-req" className="text-xs font-semibold text-slate-300 cursor-pointer select-none">Requires GPU Workers</label>
              </div>
              <Button type="submit" variant="primary" className="w-fit mt-4">Create Competition</Button>
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
                  <h2 className="text-lg font-bold text-white mb-2">Edit Competitor Details</h2>
                  <p className="text-slate-400 text-xs mb-6">Updating account: <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{editingUser.username}</code></p>
                  
                  <form onSubmit={handleUpdateUserSubmit} className="flex flex-col gap-4">
                    <div className="grid grid-cols-2 gap-4">
                      <InputField 
                        label="First Name" 
                        value={editUserForm.name} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, name: e.target.value })} 
                        required 
                      />
                      <InputField 
                        label="Last Name" 
                        value={editUserForm.surname} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, surname: e.target.value })} 
                        required 
                      />
                    </div>
                    
                    <div className="grid grid-cols-3 gap-4">
                      <InputField 
                        label="Grade" 
                        value={editUserForm.grade} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, grade: e.target.value })} 
                      />
                      <InputField 
                        label="School" 
                        value={editUserForm.school} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, school: e.target.value })} 
                      />
                      <InputField 
                        label="City" 
                        value={editUserForm.city} 
                        onChange={(e) => setEditUserForm({ ...editUserForm, city: e.target.value })} 
                      />
                    </div>

                    <InputField 
                      label="System Username" 
                      value={editUserForm.username} 
                      onChange={(e) => setEditUserForm({ ...editUserForm, username: e.target.value })} 
                      required 
                    />

                    <InputField 
                      label="Email Address" 
                      type="email"
                      value={editUserForm.email} 
                      onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })} 
                      placeholder="competitor@competition.ai"
                    />

                    <InputField 
                      label="New Password (leave blank to keep current)" 
                      type="password"
                      value={editUserForm.password} 
                      onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })} 
                      placeholder="••••••••"
                    />

                    <SelectField 
                      label="Assign Competition" 
                      value={editUserForm.challenge_id} 
                      onChange={(e) => setEditUserForm({ ...editUserForm, challenge_id: e.target.value })} 
                      required 
                      options={[
                        { value: "", label: "-- Choose Competition --" },
                        ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                      ]}
                    />

                    <div className="flex gap-2.5 mt-2">
                      <Button type="submit" variant="primary" className="flex-1">Save Changes</Button>
                      <Button type="button" variant="secondary" onClick={() => setEditingUser(null)}>Cancel</Button>
                    </div>
                  </form>
                </div>
              ) : (
                <>
                  {/* Form Manual */}
                  <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                    <h2 className="text-lg font-bold text-white mb-2">Manual Competitor Registration</h2>
                    <p className="text-slate-400 text-xs mb-6">Generates secure, randomized login credentials and assigned alias ID.</p>
                    
                    <form onSubmit={handleRegisterCompetitor} className="flex flex-col gap-4">
                      <div className="grid grid-cols-2 gap-4">
                        <InputField 
                          label="First Name" 
                          value={newCompetitor.name} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, name: e.target.value })} 
                          required 
                        />
                        <InputField 
                          label="Last Name" 
                          value={newCompetitor.surname} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, surname: e.target.value })} 
                          required 
                        />
                      </div>
                      <div className="grid grid-cols-3 gap-4">
                        <InputField 
                          label="Grade" 
                          value={newCompetitor.grade} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, grade: e.target.value })} 
                        />
                        <InputField 
                          label="School" 
                          value={newCompetitor.school} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, school: e.target.value })} 
                        />
                        <InputField 
                          label="City" 
                          value={newCompetitor.city} 
                          onChange={(e) => setNewCompetitor({ ...newCompetitor, city: e.target.value })} 
                        />
                      </div>
                      
                      <SelectField 
                        label="Assign to Competition Challenge" 
                        value={newCompetitor.challenge_id} 
                        onChange={(e) => setNewCompetitor({ ...newCompetitor, challenge_id: e.target.value })} 
                        required 
                        options={[
                          { value: "", label: "-- Choose Competition --" },
                          ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                        ]}
                      />

                      <Button type="submit" variant="primary" className="mt-2">Generate Credentials</Button>
                    </form>

                    {generatedCredentials && (
                      <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
                        <h3 className="font-bold text-sm text-indigo-300">Competitor account generated!</h3>
                        <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                          <div><strong>Competitor:</strong> {generatedCredentials.name} {generatedCredentials.surname}</div>
                          <div className="pt-2"><strong>Generated Username:</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedCredentials.username}</code></div>
                          <div><strong>Generated Password:</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedCredentials.password}</code></div>
                          <p className="text-[10px] text-slate-500 mt-2 font-medium">Please copy these credentials and share them with the student securely.</p>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Form CSV upload */}
                  <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
                    <h2 className="text-lg font-bold text-white mb-2">Import Competitors CSV</h2>
                    <p className="text-slate-400 text-xs mb-6">Bulk upload competitors using a CSV file. Expected columns: `name`, `surname`, `grade`, `school`, `city`.</p>
                    
                    <form onSubmit={handleCSVImport} className="flex flex-col gap-4">
                      <SelectField 
                        label="Target Competition Challenge" 
                        value={csvChallengeId} 
                        onChange={(e) => setCsvChallengeId(e.target.value)} 
                        required 
                        options={[
                          { value: "", label: "-- Choose Competition --" },
                          ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                        ]}
                      />

                      <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold text-slate-300">Choose CSV File</label>
                        <input 
                          type="file" 
                          accept=".csv" 
                          onChange={(e) => setCsvFile(e.target.files[0])}
                          className="text-xs text-slate-400 border border-white/5 p-3.5 bg-slate-900 rounded-lg cursor-pointer"
                          required
                        />
                      </div>

                      <Button type="submit" variant="accent" disabled={csvImporting}>
                        {csvImporting ? "Importing Bulk Data..." : "Upload & Parse CSV"}
                      </Button>
                    </form>

                    {importedCompetitors.length > 0 && (
                      <div className="mt-6 p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3">
                        <h3 className="font-bold text-sm text-emerald-400">Successfully Imported {importedCompetitors.length} Competitors</h3>
                        <div className="max-h-60 overflow-y-auto pr-1">
                          <table className="w-full text-left border-collapse text-[10px]">
                            <thead>
                              <tr className="border-b border-white/5 text-slate-400">
                                <th className="py-1.5">Competitor</th>
                                <th className="py-1.5">Username</th>
                                <th className="py-1.5">Password</th>
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
                  <h2 className="text-lg font-bold text-white">Registered Competitors</h2>
                  <p className="text-slate-400 text-xs">Pseudonym aliases mapped to real user details for unmasking checks.</p>
                </div>
                <InputField 
                  placeholder="Search competitor..." 
                  value={competitorSearch} 
                  onChange={(e) => setCompetitorSearch(e.target.value)} 
                  className="max-w-xs w-full"
                />
              </div>

              {filteredCompetitors.length === 0 ? (
                <div className="text-center py-8 text-slate-500 text-xs italic">
                  No competitors found matching your search.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Alias ID</th>
                        <th>Real Name</th>
                        <th>School / Grade</th>
                        <th>City</th>
                        <th>System Username</th>
                        <th style={{ textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCompetitors.map(comp => (
                        <tr key={comp.id}>
                          <td className="font-mono font-semibold text-indigo-400">{comp.alias_id}</td>
                          <td>{comp.name} {comp.surname}</td>
                          <td>{comp.school || "—"}{comp.grade ? ` (Grade ${comp.grade})` : ""}</td>
                          <td>{comp.city || "—"}</td>
                          <td className="font-mono text-slate-400">{comp.username}</td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              onClick={() => initEditUser(comp)}
                              className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
                            >
                              Edit
                            </button>
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
                    itemName="competitors"
                  />
                </div>
              )}
            </div>

          </div>
        )}

        {/* 5. DATABASE BACKUP MANAGEMENT */}
        {adminSubTab === 'backups' && currentUser.role === 'admin' && (
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
            <h2 className="text-xl font-bold text-white mb-2">Database Backups & Security</h2>
            <p className="text-slate-400 text-xs mb-6">Download a complete PostgreSQL database dump for disaster recovery, migrations or compliance.</p>
            
            <div className="bg-slate-900/40 border border-white/5 p-6 rounded-xl flex items-center justify-between gap-4 flex-wrap">
              <div>
                <h4 className="font-bold text-slate-200 text-sm">Download Postgres DB Backup</h4>
                <p className="text-slate-500 text-xs mt-1">Generates an instant `.sql` backup file via `pg_dump` stream.</p>
              </div>
              <Button variant="accent" onClick={handleDownloadBackup}>Download Backup Dump File</Button>
            </div>
          </div>
        )}

        {/* 6. SYSTEM USER MANAGEMENT */}
        {adminSubTab === 'user-management' && currentUser.role === 'admin' && (
          <div className="flex flex-col gap-8 animate-fadein">
            
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
              
              {/* Form Register Admin/Jury */}
              <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl lg:col-span-1">
                <h2 className="text-lg font-bold text-white mb-2">Register User Account</h2>
                <p className="text-slate-400 text-xs mb-6">Manually register a Jury/Judge or Competitor account.</p>
                
                <form onSubmit={handleRegisterUser} className="flex flex-col gap-4">
                  <InputField 
                    label="Username" 
                    value={newUser.username} 
                    onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} 
                    placeholder="e.g. jury_sarah"
                    required 
                  />
                  <InputField 
                    label="Email Address" 
                    type="email"
                    value={newUser.email} 
                    onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} 
                    placeholder="sarah@competition.ai"
                  />
                  <InputField 
                    label="Password (optional, auto-generated if empty)" 
                    type="password"
                    value={newUser.password} 
                    onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} 
                    placeholder="••••••••"
                  />
                  
                  <div className="grid grid-cols-2 gap-4">
                    <InputField 
                      label="First Name" 
                      value={newUser.name} 
                      onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} 
                      required 
                    />
                    <InputField 
                      label="Last Name" 
                      value={newUser.surname} 
                      onChange={(e) => setNewUser({ ...newUser, surname: e.target.value })} 
                      required 
                    />
                  </div>

                  <SelectField 
                    label="Role" 
                    value={newUser.role} 
                    onChange={(e) => setNewUser({ ...newUser, role: e.target.value })} 
                    required 
                    options={[
                      { value: "competitor", label: "Competitor" },
                      { value: "jury", label: "Jury / Judge" }
                    ]}
                  />

                  {newUser.role === 'competitor' && (
                    <>
                      <div className="grid grid-cols-3 gap-2">
                        <InputField label="Grade" value={newUser.grade} onChange={(e) => setNewUser({ ...newUser, grade: e.target.value })} />
                        <InputField label="School" value={newUser.school} onChange={(e) => setNewUser({ ...newUser, school: e.target.value })} />
                        <InputField label="City" value={newUser.city} onChange={(e) => setNewUser({ ...newUser, city: e.target.value })} />
                      </div>
                      <SelectField 
                        label="Assign Competition" 
                        value={newUser.challenge_id} 
                        onChange={(e) => setNewUser({ ...newUser, challenge_id: e.target.value })} 
                        required 
                        options={[
                          { value: "", label: "-- Choose Competition --" },
                          ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
                        ]}
                      />
                    </>
                  )}

                  <Button type="submit" variant="primary" className="mt-2">Register User</Button>
                </form>

                {generatedUserCredentials && (
                  <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
                    <h3 className="font-bold text-sm text-indigo-300">{generatedUserCredentials.role.toUpperCase()} Account created!</h3>
                    <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                      <div><strong>User:</strong> {generatedUserCredentials.name} {generatedUserCredentials.surname}</div>
                      <div className="pt-2"><strong>Username:</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedUserCredentials.username}</code></div>
                      <div><strong>Password:</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedUserCredentials.password}</code></div>
                    </div>
                  </div>
                )}
              </div>

              {/* User accounts list */}
              <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl lg:col-span-2">
                <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
                  <div>
                    <h2 className="text-lg font-bold text-white">System User Accounts</h2>
                    <p className="text-slate-400 text-xs">Jury and Competitor system users.</p>
                  </div>
                  <InputField 
                    placeholder="Search users..." 
                    value={userSearch} 
                    onChange={(e) => setUserSearch(e.target.value)} 
                    className="max-w-xs w-full"
                  />
                </div>

                {filteredUsers.length === 0 ? (
                  <div className="text-center py-8 text-slate-500 text-xs italic">
                    No users found matching your search.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Username</th>
                          <th>Real Name</th>
                          <th>Role</th>
                          <th>Email Address</th>
                          <th style={{ textAlign: 'right' }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredUsers.map(user => (
                          <tr key={user.id}>
                            <td className="font-mono font-bold text-slate-200">{user.username}</td>
                            <td>{user.name} {user.surname}</td>
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
                                  Delete
                                </button>
                              ) : (
                                <span className="text-[10px] text-slate-500 font-semibold italic">Current Admin</span>
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
                      itemName="users"
                    />
                  </div>
                )}
              </div>

            </div>

          </div>
        )}

      </div>
    </div>
  );
}
