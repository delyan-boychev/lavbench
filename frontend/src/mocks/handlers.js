import { http, HttpResponse } from 'msw'

const BASE = '/api'

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
}

const DEFAULT_ADMIN = {
  id: 2,
  username: 'admin',
  role: 'admin',
  alias_id: 'Admin-001',
  name: 'Admin',
  surname: 'User',
}

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
}

const DEFAULT_TASK = {
  id: 1,
  challenge_id: 1,
  title: 'Sample Task',
  description: 'A sample task',
  ram_limit_mb: 512,
  time_limit_sec: 300,
  gpu_required: false,
  base_docker_image: 'python:3.10-slim',
  files: [{ filename: 'data.csv', size: 1024 }],
  max_submissions_per_period: 10,
}

function isAdmin(request) {
  const auth = request.headers.get('Authorization')
  return auth && auth === 'Bearer admin-token'
}

function getAuthUser(request) {
  const auth = request.headers.get('Authorization')
  if (!auth) return null
  const token = auth.replace('Bearer ', '')
  if (token === 'admin-token') return DEFAULT_ADMIN
  if (token === 'user-token') return DEFAULT_USER
  return null
}

export const handlers = [
  // ── Health ──────────────────────────────────────────────────────────
  http.get(`${BASE}/health`, async () => {
    return HttpResponse.json({
      status: 'ok',
      checks: { database: 'connected', redis: 'connected' },
    })
  }),

  // ── CSRF ────────────────────────────────────────────────────────────
  http.get(`${BASE}/auth/csrf-token`, async () => {
    return HttpResponse.json({ csrf_token: 'test-csrf-token' })
  }),

  // ── Auth ────────────────────────────────────────────────────────────
  http.post(`${BASE}/auth/login`, async ({ request }) => {
    const body = /** @type {Record<string, string>} */ (await request.json())
    if (body.username === 'testuser' && body.password === 'testpass123') {
      return HttpResponse.json({
        message: 'Logged in successfully.',
        user: DEFAULT_USER,
      })
    }
    if (body.username === 'admin' && body.password === 'adminpass123') {
      return HttpResponse.json({
        message: 'Logged in successfully.',
        user: DEFAULT_ADMIN,
      })
    }
    return HttpResponse.json(
      { code: 'ERR_INVALID_CREDENTIALS', error: 'Invalid credentials.' },
      { status: 401 }
    )
  }),

  http.post(`${BASE}/auth/logout`, async () => {
    return HttpResponse.json({ message: 'Logged out.' })
  }),

  http.get(`${BASE}/auth/me`, async ({ request }) => {
    const user = getAuthUser(request)
    if (!user) {
      return HttpResponse.json(
        { code: 'ERR_UNAUTHORIZED', error: 'Unauthorized.' },
        { status: 401 }
      )
    }
    return HttpResponse.json({ user })
  }),

  // ── Challenges ──────────────────────────────────────────────────────
  http.get(`${BASE}/challenges`, async ({ request }) => {
    const url = new URL(request.url)
    const page = parseInt(/** @type {string} */ (url.searchParams.get('page') || '1'))
    const isAdmin_ = isAdmin(request)
    const items = isAdmin_
      ? [DEFAULT_CHALLENGE, { ...DEFAULT_CHALLENGE, id: 2, title: 'Challenge 2' }]
      : [DEFAULT_CHALLENGE]
    return HttpResponse.json({ items, total: items.length, pages: 1, page })
  }),

  http.post(`${BASE}/challenges`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.get(`${BASE}/challenges/:id`, async ({ params }) => {
    const challenge = {
      ...DEFAULT_CHALLENGE,
      id: parseInt(/** @type {string} */ (params.id)),
      tasks: [DEFAULT_TASK],
      stages: [{ id: 1, title: 'Stage 1', stage_number: 1 }],
    }
    return HttpResponse.json(challenge)
  }),

  http.put(`${BASE}/challenges/:id`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.delete(`${BASE}/challenges/:id`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.post(`${BASE}/challenges/:id/finalize`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.post(`${BASE}/challenges/:id/archive`, async () => {
    return HttpResponse.json({ message: 'Challenge archived.' })
  }),

  http.post(`${BASE}/challenges/:id/test-competition`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.get(`${BASE}/challenges/:id/export`, async () => {
    return HttpResponse.json({ title: 'Exported Challenge' })
  }),

  http.post(`${BASE}/challenges/import`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  // ── Leaderboard ─────────────────────────────────────────────────────
  http.get(`${BASE}/challenges/:id/leaderboard`, async () => {
    return HttpResponse.json({
      leaderboard: [
        { rank: 1, user_id: 1, alias_id: 'Comp-001', total_score: 95, total_time_ms: 120000 },
      ],
      tasks: [DEFAULT_TASK],
      metric_name: 'accuracy',
      is_normalized: false,
    })
  }),

  http.post(`${BASE}/challenges/:id/manual-points`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  // ── Parse Notebook ──────────────────────────────────────────────────
  http.post(`${BASE}/challenges/:id/parse-notebook`, async () => {
    return HttpResponse.json({
      cells: [
        { id: 1, type: 'code', source: 'print("hello")' },
        { id: 2, type: 'markdown', source: '# Title' },
      ],
      filename: 'notebook.ipynb',
    })
  }),

  // ── Stages ──────────────────────────────────────────────────────────
  http.post(`${BASE}/challenges/:cid/stages`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.put(`${BASE}/challenges/:cid/stages/:sid`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.delete(`${BASE}/challenges/:cid/stages/:sid`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.post(`${BASE}/challenges/:cid/stages/:sid/finalize`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  // ── Tasks ───────────────────────────────────────────────────────────
  http.post(`${BASE}/challenges/:challengeId/tasks`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.get(`${BASE}/tasks/:id`, async () => {
    return HttpResponse.json(DEFAULT_TASK)
  }),

  http.put(`${BASE}/tasks/:id`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.delete(`${BASE}/tasks/:id`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.post(`${BASE}/tasks/:id/submit`, async () => {
    return HttpResponse.json({ ok: true })
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
    })
  }),

  http.get(`${BASE}/tasks/:id/leaderboard`, async () => {
    return HttpResponse.json({
      leaderboard: [{ rank: 1, alias_id: 'Comp-001', score: 0.95 }],
    })
  }),

  http.get(`${BASE}/tasks/:id/download/:filename`, async () => {
    return new HttpResponse(new Blob(['test content']), {
      headers: { 'Content-Type': 'application/octet-stream' },
    })
  }),

  // ── Submissions ─────────────────────────────────────────────────────
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
    })
  }),

  http.post(`${BASE}/submissions/:submissionId/select-final`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  // ── Admin Users ─────────────────────────────────────────────────────
  http.get(`${BASE}/admin/users`, async ({ request }) => {
    const url = new URL(request.url)
    const page = parseInt(/** @type {string} */ (url.searchParams.get('page') || '1'))
    return HttpResponse.json({
      items: [DEFAULT_USER, DEFAULT_ADMIN],
      total: 2,
      pages: 1,
      page,
    })
  }),

  http.put(`${BASE}/admin/users/:userId`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.delete(`${BASE}/admin/users/:userId`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.post(`${BASE}/admin/users/:userId/reset-password`, async () => {
    return HttpResponse.json({ username: 'testuser', password: 'newpass123' })
  }),

  http.post(`${BASE}/admin/register-competitor`, async () => {
    return HttpResponse.json({ generated_username: 'comp-abc', generated_password: 'pass123' })
  }),

  http.post(`${BASE}/admin/register-user`, async () => {
    return HttpResponse.json({ generated_username: 'user-abc', generated_password: 'pass123' })
  }),

  http.post(`${BASE}/admin/import-competitors-csv`, async () => {
    return HttpResponse.json({
      competitors: [{ name: 'Test', surname: 'User', generated_username: 'comp-abc', generated_password: 'pass123' }],
    })
  }),

  http.get(`${BASE}/admin/challenges/:challengeId/download-scores-csv`, async () => {
    return new HttpResponse(new Blob(['score,alias\n0.95,Comp-001']), {
      headers: { 'Content-Type': 'text/csv' },
    })
  }),

  http.get(`${BASE}/admin/challenges/:challengeId/download-submissions-zip`, async () => {
    return new HttpResponse(new Blob(['zip content']), {
      headers: { 'Content-Type': 'application/zip' },
    })
  }),

  http.post(`${BASE}/admin/challenges/:challengeId/reset-all-passwords`, async () => {
    return HttpResponse.json({
      reset_accounts: [{ name: 'Test', surname: 'User', username: 'comp-abc', password: 'newpass' }],
    })
  }),

  // ── Metrics ─────────────────────────────────────────────────────────
  http.get(`${BASE}/admin/metrics`, async () => {
    return HttpResponse.json({
      accuracy: { name: 'Accuracy', type: 'classification', higher_is_better: true },
      f1_score: { name: 'F1 Score', type: 'classification', higher_is_better: true },
    })
  }),

  // ── Workers ─────────────────────────────────────────────────────────
  http.get(`${BASE}/admin/workers/stats`, async () => {
    return HttpResponse.json({
      connected_workers_count: 2,
      workers: [
        { name: 'worker-1', pid: 1234, uptime: 3600, pool_size: 4, active_tasks_count: 1 },
        { name: 'worker-2', pid: 5678, uptime: 1800, pool_size: 4, active_tasks_count: 0 },
      ],
      system: { load_avg: [0.5, 0.3, 0.2], cpu_count: 8, memory: { total_gb: 16, available_gb: 12 } },
    })
  }),

  http.get(`${BASE}/worker-status`, async () => {
    return HttpResponse.json({ status: 'online', clusters: [] })
  }),

  // ── Backups ─────────────────────────────────────────────────────────
  http.get(`${BASE}/admin/backups`, async () => {
    return HttpResponse.json({
      backups: [
        { filename: 'backup-2024-01-01.sql', size_mb: 1.5, created_at: new Date().toISOString(), type: 'manual' },
      ],
    })
  }),

  http.post(`${BASE}/admin/backups/force`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  http.delete(`${BASE}/admin/backups/:filename`, async () => {
    return HttpResponse.json({ ok: true })
  }),

  // ── Docs ────────────────────────────────────────────────────────────
  http.get(`${BASE}/docs/:tab`, async () => {
    return HttpResponse.json({ content: '# Documentation\n\nSample docs content.' })
  }),

  // ── Dead Letters ────────────────────────────────────────────────────
  http.get(`${BASE}/admin/dead-letters`, async () => {
    return HttpResponse.json([])
  }),
]
