import { http, HttpResponse } from 'msw';

const BASE = '/api';

const DEFAULT_USER = {
  id: 1,
  username: 'testuser',
  role: 'competitor',
  alias_id: 'Comp-001',
  name: 'Test',
  surname: 'User',
  grade: '10',
  school: 'Test School',
  city: 'Test City',
  challenge_id: 1,
  is_anonymous: false,
};

const DEFAULT_ADMIN = {
  id: 2,
  username: 'admin',
  role: 'admin',
  alias_id: 'Admin-001',
  name: 'Admin',
  surname: 'User',
};

const DEFAULT_CHALLENGE = {
  id: 1,
  title: 'Sample Challenge',
  description: 'A sample challenge for testing',
  max_eval_requests: 10,
  ram_limit_mb: 4096,
  time_limit_sec: 300,
  gpu_required: false,
  is_active: true,
  is_archived: false,
  scores_finalized: false,
  is_frozen: false,
  double_blind: true,
  start_time: new Date(Date.now() - 7200000).toISOString(),
  end_time: new Date(Date.now() + 7200000).toISOString(),
  timezone: 'UTC',
  status: 'active',
  num_tasks: 1,
};

const DEFAULT_WORKSPACE_IMAGE = {
  image_id: 'python-ml',
  name: 'Python ML (CPU)',
  description: 'pandas, pyarrow and scikit-learn',
  packages: [{ name: 'pandas', version: '2.2.3' }],
  default: true,
};

const DEFAULT_ENVIRONMENT = {
  id: 'env-1',
  challenge_id: 1,
  stage_id: null,
  stage_title: null,
  enabled: true,
  auto_publish: false,
  published_at: null,
  compute_kind: 'CPU',
  cpu_cores: 2,
  memory_gib: 8,
  workspace_gib: 10,
  data_gib: 1,
  disk_gib: 11,
  gpu_type: null,
  image_id: 'python-ml',
  image_name: 'Python ML (CPU)',
  image_digest: null,
  archive_until: new Date(Date.now() + 30 * 86_400_000).toISOString(),
  max_attendance: 3,
  starts_at: new Date(Date.now() - 7200000).toISOString(),
  ends_at: new Date(Date.now() + 7380000).toISOString(),
  asset_version: null,
  folders: ['sample-task'],
  status: {
    state: 'ready',
    published: false,
    progress: null,
    since: null,
    alert: false,
    code: null,
    message: null,
    limit: null,
    fetched_at: null,
  },
  phase: 'unpublished',
  auto_publish_at: null,
};

const DEFAULT_WORKSPACE_CATALOG = {
  images: [DEFAULT_WORKSPACE_IMAGE],
  profiles: [
    { id: 'cpu-compact', name: 'CPU Compact', cpu_cores: 2, memory_gib: 8 },
    { id: 'cpu-standard', name: 'CPU Standard', cpu_cores: 2, memory_gib: 12 },
  ],
  workspace_gib: { min: 10, max: 98, default: 10 },
  auto_publish_lead_hours: 24,
};

const DEFAULT_TASK = {
  id: 1,
  challenge_id: 1,
  title: 'Sample Task',
  folder_name: 'sample-task',
  evaluation_mode: 'notebook',
  emergency_upload_enabled: false,
  mode_locked: false,
  files_locked: false,
  description: 'A sample task',
  ram_limit_mb: 512,
  time_limit_sec: 300,
  gpu_required: false,
  base_docker_image: 'python:3.10-slim',
  files: [{ filename: 'data.csv', size: 1024 }],
  max_submissions_per_period: 10,
};

function isAdmin(request) {
  const auth = request.headers.get('Authorization');
  return auth && auth === 'Bearer admin-token';
}

function getAuthUser(request) {
  const auth = request.headers.get('Authorization');
  if (!auth) return null;
  const token = auth.replace('Bearer ', '');
  if (token === 'admin-token') return DEFAULT_ADMIN;
  if (token === 'user-token') return DEFAULT_USER;
  return null;
}

export const handlers = [
  // ── Health ──────────────────────────────────────────────────────────
  http.get(`${BASE}/health`, async () => {
    return HttpResponse.json({
      status: 'ok',
      checks: { database: 'connected', redis: 'connected' },
    });
  }),

  // ── CSRF ────────────────────────────────────────────────────────────
  http.get(`${BASE}/auth/csrf-token`, async () => {
    return HttpResponse.json({ csrf_token: 'test-csrf-token' });
  }),

  // ── Auth ────────────────────────────────────────────────────────────
  http.post(`${BASE}/auth/login`, async ({ request }) => {
    const body = /** @type {Record<string, string>} */ (await request.json());
    if (body.username === 'testuser' && body.password === 'testpass123') {
      return HttpResponse.json({
        message: 'Logged in successfully.',
        user: DEFAULT_USER,
      });
    }
    if (body.username === 'admin' && body.password === 'adminpass123') {
      return HttpResponse.json({
        message: 'Logged in successfully.',
        user: DEFAULT_ADMIN,
      });
    }
    return HttpResponse.json(
      { code: 'ERR_INVALID_CREDENTIALS', error: 'Invalid credentials.' },
      { status: 401 },
    );
  }),

  http.post(`${BASE}/auth/logout`, async () => {
    return HttpResponse.json({ message: 'Logged out.' });
  }),

  http.get(`${BASE}/auth/me`, async ({ request }) => {
    const user = getAuthUser(request);
    if (!user) {
      return HttpResponse.json(
        { code: 'ERR_UNAUTHORIZED', error: 'Unauthorized.' },
        { status: 401 },
      );
    }
    return HttpResponse.json({ user });
  }),

  // ── Challenges ──────────────────────────────────────────────────────
  http.get(`${BASE}/challenges`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(/** @type {string} */ (url.searchParams.get('page') || '1'));
    const isAdmin_ = isAdmin(request);
    const items = isAdmin_
      ? [DEFAULT_CHALLENGE, { ...DEFAULT_CHALLENGE, id: 2, title: 'Challenge 2' }]
      : [DEFAULT_CHALLENGE];
    return HttpResponse.json({ items, total: items.length, pages: 1, page });
  }),

  http.post(`${BASE}/challenges`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.get(`${BASE}/challenges/:id`, async ({ params }) => {
    const challenge = {
      ...DEFAULT_CHALLENGE,
      id: /** @type {string} */ (params.id),
      tasks: [DEFAULT_TASK],
      stages: [{ id: 'mock-stage-1', title: 'Stage 1', stage_number: 1 }],
    };
    return HttpResponse.json(challenge);
  }),

  http.put(`${BASE}/challenges/:id`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.delete(`${BASE}/challenges/:id`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.post(`${BASE}/challenges/:id/finalize`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.post(`${BASE}/challenges/:id/archive`, async () => {
    return HttpResponse.json({ message: 'Challenge archived.' });
  }),

  http.post(`${BASE}/challenges/:id/test-competition`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.get(`${BASE}/challenges/:id/export`, async () => {
    return HttpResponse.json({ title: 'Exported Challenge' });
  }),

  http.post(`${BASE}/challenges/import`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  // ── Leaderboard ─────────────────────────────────────────────────────
  http.get(`${BASE}/challenges/:id/leaderboard`, async () => {
    // A competitor's view: whitelisted user fields, and a Baseline row with no user
    return HttpResponse.json({
      leaderboard: [
        {
          rank: 1,
          user: { id: 1, alias_id: 'Comp-001', is_anonymous: false, manual_points: {} },
          task_scores: { 1: { public_score: 0.95, private_score: null, submission_id: 11 } },
          public_score: 0.95,
          private_score: null,
          total_points: 0,
          has_submitted: true,
          task_ranks: { 1: 1 },
          stage_ranks: {},
        },
        {
          rank: null,
          user: null,
          label: 'Baseline',
          is_baseline_entry: true,
          task_scores: { 1: { public_score: 0.9, private_score: null, submission_id: 10 } },
          public_score: 0.9,
          private_score: null,
          total_points: 0,
          has_submitted: true,
          task_ranks: { 1: null },
          stage_ranks: {},
          task_rows_before: { 1: 1 },
        },
      ],
      tasks: [DEFAULT_TASK],
      metric_name: 'accuracy',
      is_normalized: false,
    });
  }),

  http.post(`${BASE}/challenges/:id/manual-points`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  // ── Parse Notebook ──────────────────────────────────────────────────
  http.post(`${BASE}/challenges/:id/parse-notebook`, async () => {
    return HttpResponse.json({
      cells: [
        { id: 1, type: 'code', source: 'print("hello")' },
        { id: 2, type: 'markdown', source: '# Title' },
      ],
      filename: 'notebook.ipynb',
    });
  }),

  // ── Stages ──────────────────────────────────────────────────────────
  http.post(`${BASE}/challenges/:cid/stages`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.put(`${BASE}/challenges/:cid/stages/:sid`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.delete(`${BASE}/challenges/:cid/stages/:sid`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.post(`${BASE}/challenges/:cid/stages/:sid/finalize`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  // ── Tasks ───────────────────────────────────────────────────────────
  http.post(`${BASE}/challenges/:challengeId/tasks`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.get(`${BASE}/tasks/:id`, async () => {
    return HttpResponse.json(DEFAULT_TASK);
  }),

  http.put(`${BASE}/tasks/:id`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.delete(`${BASE}/tasks/:id`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.post(`${BASE}/tasks/:id/submit`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.post(`${BASE}/tasks/:id/submit-workspace`, async () => {
    return HttpResponse.json(
      {
        message: 'Submission received and queued for scoring.',
        submission_id: 2,
        status: 'queued',
      },
      { status: 202 },
    );
  }),

  http.post(`${BASE}/tasks/:id/submit-file`, async () => {
    return HttpResponse.json(
      {
        message: 'Submission received and queued for scoring.',
        submission_id: 3,
        status: 'queued',
      },
      { status: 202 },
    );
  }),

  http.post(`${BASE}/tasks/:id/workspace-notebook`, async () => {
    return HttpResponse.json({
      filename: 'solution.ipynb',
      cells: [{ id: 0, type: 'code', source: '# SUBMIT\nprint(1)' }],
    });
  }),

  http.put(`${BASE}/tasks/:id/emergency-upload`, async ({ request }) => {
    const body = /** @type {{ enabled?: boolean }} */ (await request.json());
    return HttpResponse.json({
      ...DEFAULT_TASK,
      evaluation_mode: 'file',
      emergency_upload_enabled: Boolean(body?.enabled),
    });
  }),

  http.get(`${BASE}/tasks/:id/submissions`, async () => {
    return HttpResponse.json({
      items: [
        {
          id: 1,
          task_id: 1,
          challenge_id: 1,
          user_id: 1,
          status: 'completed',
          public_score: 0.95,
          private_score: 0.92,
          created_at: new Date().toISOString(),
          is_final_selection: false,
        },
      ],
      total: 1,
      pages: 1,
    });
  }),

  http.get(`${BASE}/tasks/:id/download/:filename`, async () => {
    return new HttpResponse(new Blob(['test content']), {
      headers: { 'Content-Type': 'application/octet-stream' },
    });
  }),

  // ── Submissions ─────────────────────────────────────────────────────
  http.get(`${BASE}/submissions/:submissionId/files/:kind`, async ({ params }) => {
    const extension = params.kind === 'notebook' ? 'ipynb' : 'parquet';
    return new HttpResponse(new Blob(['test content']), {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': `attachment; filename="Quiet-Owl_sample-task_sub_${params.submissionId}.${extension}"`,
      },
    });
  }),

  http.get(`${BASE}/submissions/:submissionId`, async () => {
    return HttpResponse.json({
      id: 1,
      task_id: 1,
      challenge_id: 1,
      user_id: 1,
      status: 'completed',
      public_score: 0.95,
      private_score: 0.92,
      created_at: new Date().toISOString(),
      code_cells: [{ id: 1, type: 'code', source: 'print("hello")' }],
    });
  }),

  http.post(`${BASE}/submissions/:submissionId/select-final`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  // ── Admin Users ─────────────────────────────────────────────────────
  http.get(`${BASE}/admin/users`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(/** @type {string} */ (url.searchParams.get('page') || '1'));
    return HttpResponse.json({
      items: [DEFAULT_USER, DEFAULT_ADMIN],
      total: 2,
      pages: 1,
      page,
    });
  }),

  http.put(`${BASE}/admin/users/:userId`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.delete(`${BASE}/admin/users/:userId`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.post(`${BASE}/admin/users/:userId/reset-password`, async () => {
    return HttpResponse.json({ username: 'testuser', password: 'newpass123' });
  }),

  http.post(`${BASE}/admin/register-competitor`, async () => {
    return HttpResponse.json({ generated_username: 'comp-abc', generated_password: 'pass123' });
  }),

  http.post(`${BASE}/admin/register-user`, async () => {
    return HttpResponse.json({ generated_username: 'user-abc', generated_password: 'pass123' });
  }),

  http.post(`${BASE}/admin/import-competitors-csv`, async () => {
    return HttpResponse.json({
      competitors: [
        {
          name: 'Test',
          surname: 'User',
          generated_username: 'comp-abc',
          generated_password: 'pass123',
        },
      ],
    });
  }),

  http.get(`${BASE}/admin/challenges/:challengeId/download-scores-csv`, async () => {
    return new HttpResponse(new Blob(['score,alias\n0.95,Comp-001']), {
      headers: { 'Content-Type': 'text/csv' },
    });
  }),

  http.get(`${BASE}/admin/challenges/:challengeId/download-submissions-zip`, async () => {
    return new HttpResponse(new Blob(['zip content']), {
      headers: { 'Content-Type': 'application/zip' },
    });
  }),

  http.post(`${BASE}/admin/challenges/:challengeId/reset-all-passwords`, async () => {
    return HttpResponse.json({
      message: 'Reset passwords for 2 competitors.',
      reset_accounts: [
        { id: 'u1', username: 'comp_one', password: 'pass-one-1234', alias_id: 'Alias-1' },
        { id: 'u2', username: 'comp_two', password: 'pass-two-5678', alias_id: 'Alias-2' },
      ],
    });
  }),

  // ── Metrics ─────────────────────────────────────────────────────────
  http.get(`${BASE}/admin/metrics`, async () => {
    return HttpResponse.json({
      accuracy: { name: 'Accuracy', type: 'classification', higher_is_better: true },
      f1_score: { name: 'F1 Score', type: 'classification', higher_is_better: true },
    });
  }),

  // ── Status ──────────────────────────────────────────────────────────
  http.get(`${BASE}/status`, async () => {
    return HttpResponse.json({
      status: 'operational',
      components: { api: 'operational', scoring: 'operational' },
      updated_at: new Date().toISOString(),
    });
  }),

  http.get(`${BASE}/admin/system-status`, async () => {
    const now = new Date();
    return HttpResponse.json({
      status: 'degraded_performance',
      components: { api: 'operational', scoring: 'degraded_performance' },
      queues: [
        { name: 'evaluation_cpu', consumers: 1, queued: 3 },
        { name: 'evaluation_gpu', consumers: 0, queued: 0 },
      ],
      workers: [
        {
          name: 'celery@cpu-worker-1',
          type: 'cpu',
          queues: ['evaluation_cpu'],
          online: true,
          last_seen: new Date(now.getTime() - 12_000).toISOString(),
          concurrency: 4,
          cpu_cores: 8,
          ram_gb: 15.6,
          gpu_type: null,
          vram_gb: null,
        },
      ],
      submissions: {
        queued: 3,
        running: 1,
        oldest_queued_seconds: 95,
        completed_last_15m: 12,
        failed_last_15m: 1,
      },
      updated_at: now.toISOString(),
    });
  }),

  // ── Backups ─────────────────────────────────────────────────────────
  http.get(`${BASE}/admin/backups`, async () => {
    return HttpResponse.json({
      backups: [
        {
          filename: 'backup-2024-01-01.sql',
          size_mb: 1.5,
          created_at: new Date().toISOString(),
          type: 'manual',
        },
      ],
    });
  }),

  http.post(`${BASE}/admin/backups/force`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  http.delete(`${BASE}/admin/backups/:filename`, async () => {
    return HttpResponse.json({ ok: true });
  }),

  // ── nanoColab environments ──────────────────────────────────────────
  http.get(`${BASE}/environment/images`, async () => {
    return HttpResponse.json(DEFAULT_WORKSPACE_CATALOG);
  }),

  http.get(`${BASE}/challenges/:challengeId/environments`, async ({ params }) => {
    return HttpResponse.json({
      environments: [{ ...DEFAULT_ENVIRONMENT, challenge_id: params.challengeId }],
      setting_locked: false,
    });
  }),

  http.post(`${BASE}/challenges/:challengeId/environments/:environmentId/publish`, async () => {
    return HttpResponse.json({
      ...DEFAULT_ENVIRONMENT,
      published_at: new Date().toISOString(),
      status: { ...DEFAULT_ENVIRONMENT.status, state: 'ready', published: true },
    });
  }),

  http.post(`${BASE}/challenges/:challengeId/environments/:environmentId/extension`, async () => {
    return HttpResponse.json(DEFAULT_ENVIRONMENT);
  }),

  http.get(`${BASE}/challenges/:challengeId/environments/:environmentId/workspaces`, async () => {
    return HttpResponse.json({
      workspaces: [
        {
          user_id: 1,
          alias: 'Comp-001',
          username: 'testuser',
          opened: true,
          created_at: new Date().toISOString(),
          last_launched_at: new Date().toISOString(),
          last_submission_at: null,
          last_submission_status: null,
        },
      ],
    });
  }),

  http.get(`${BASE}/tasks/:taskId/environment`, async () => {
    return HttpResponse.json({
      status: 'ready',
      folder_name: 'sample-task',
      open_path: 'sample-task/solution.ipynb',
      starts_at: DEFAULT_CHALLENGE.start_time,
      ends_at: DEFAULT_CHALLENGE.end_time,
    });
  }),

  http.post(`${BASE}/tasks/:taskId/environment/launch`, async () => {
    return HttpResponse.json({
      launch_url: 'https://hub.example/hub/launch',
      launch_token: 'launch-token',
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      open_path: 'sample-task/solution.ipynb',
    });
  }),

  // ── Docs ────────────────────────────────────────────────────────────
  http.get(`${BASE}/docs/:tab`, async () => {
    return HttpResponse.json({ content: '# Documentation\n\nSample docs content.' });
  }),

  // ── Dead Letters ────────────────────────────────────────────────────
  http.get(`${BASE}/admin/dead-letters`, async () => {
    return HttpResponse.json([]);
  }),
];
