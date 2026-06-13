import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../ui/MarkdownComponents';
import TaskService from '../../services/TaskService';

function FileCard({ file, taskId, token }) {
  const handleDownload = () => {
    const url = TaskService.getDownloadUrl(taskId, file.filename);
    const a = document.createElement('a');
    a.href = url;
    a.download = file.filename;
    // Attach token as query param isn't ideal — use fetch + blob for authenticated download
    fetch(url, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(r => r.blob())
      .then(blob => {
        const objUrl = URL.createObjectURL(blob);
        a.href = objUrl;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(objUrl);
      });
  };

  const sizeMB = file.size_bytes ? (file.size_bytes / (1024 * 1024)).toFixed(2) : null;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '9px 14px',
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)',
      gap: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--accent)', flexShrink: 0 }}>
          <path strokeLinecap="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {file.filename}
        </span>
        {sizeMB && (
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', flexShrink: 0 }}>{sizeMB} MB</span>
        )}
      </div>
      <button className="btn btn-ghost btn-sm" onClick={handleDownload} title={`Download ${file.filename}`}>
        <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
        Download
      </button>
    </div>
  );
}

export default function TaskDetail({ task, token }) {
  if (!task) return null;

  let files = [];
  try {
    files = typeof task.files === 'string' ? JSON.parse(task.files) : (task.files || []);
  } catch { files = []; }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Task title + meta */}
      <div className="surface" style={{ padding: '22px 26px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: task.description ? 18 : 0 }}>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-primary)' }}>{task.title}</h2>
        </div>

        {task.description && (
          <div className="prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {task.description}
            </ReactMarkdown>
          </div>
        )}

        {task.evaluator_script_path && (
          <div style={{
            marginTop: 18,
            padding: '12px 16px',
            background: 'rgba(99, 102, 241, 0.08)',
            border: '1px solid rgba(99, 102, 241, 0.2)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.75rem',
            color: 'var(--text-secondary)',
            lineHeight: '1.4'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, fontWeight: 700, color: 'var(--accent)' }}>
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              <span>Jury Custom Evaluator Active</span>
            </div>
            <p>
              This task uses a custom evaluator. Please ensure your submission defines the entry-point function signatures specified in the task description or the downloadable Baseline Notebook.
            </p>
          </div>
        )}
      </div>

      {/* Rules & Configuration */}
      <div className="surface" style={{ padding: '18px 22px' }}>
        <h3 style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 14 }}>
          Rules & Configuration
        </h3>
        
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
          {/* Resources & Limits */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <h4 style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Resource Limits</h4>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <strong>RAM Limit:</strong> {task.ram_limit_mb ? `${task.ram_limit_mb} MB` : '8192 MB (default)'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <strong>Time Limit:</strong> {task.time_limit_sec ? `${task.time_limit_sec}s` : '300s (default)'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <strong>GPU Required:</strong> {task.gpu_required === true ? 'Yes' : task.gpu_required === false ? 'No' : 'Challenge Default'}
            </div>
          </div>

          {/* Submission Rules */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <h4 style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Execution Rules</h4>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <strong>Require <code># SUBMIT</code> tag:</strong> {task.require_submit_tag ? 'Yes' : 'No'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <strong>Ban Magic Commands:</strong> {task.ban_magic_commands ? 'Yes' : 'No'}
            </div>
            {task.banned_imports && (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                <strong>Banned Libraries:</strong> <code style={{ color: 'var(--danger)' }}>{task.banned_imports}</code>
              </div>
            )}
          </div>

          {/* Rate Limits & Dataset */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <h4 style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Dataset & Submissions</h4>
            {task.hf_train_repo && (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                <strong>Public Train Repo:</strong> <a href={`https://huggingface.co/${task.hf_train_repo}`} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>{task.hf_train_repo}</a>
              </div>
            )}
            {task.max_submissions_per_period && task.submission_period_hours && (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                <strong>Task Rate Limit:</strong> {task.max_submissions_per_period} subs / {task.submission_period_hours}h
              </div>
            )}
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <strong>Public Split:</strong> {task.public_eval_percentage}% of Private Dataset
            </div>
          </div>
        </div>
      </div>

      {/* Files */}
      {files.length > 0 && (
        <div className="surface" style={{ padding: '18px 22px' }}>
          <h3 style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            Task Files ({files.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {files.map(f => (
              <FileCard key={f.filename} file={f} taskId={task.id} token={token} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
