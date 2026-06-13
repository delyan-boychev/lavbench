import React, { useState } from 'react';
import { useAuth } from '../../AuthContext';
import { useApp } from '../../context/AppContext';
import ChallengeService from '../../services/ChallengeService';
import TaskService from '../../services/TaskService';
import Button from '../ui/Button';

export default function NotebookSubmit({ task, challenge }) {
  const { currentUser, token } = useAuth();
  const { showToast } = useApp();

  const [cells, setCells] = useState([]);
  const [selectedCellIds, setSelectedCellIds] = useState([]);
  const [fileName, setFileName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const isCompetitor = currentUser?.role === 'competitor';
  const isClosed = !challenge?.is_active || challenge?.is_archived;

  // Admin/Jury: show info panel only
  if (!isCompetitor) {
    return (
      <div className="surface" style={{ padding: '22px 26px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: 'var(--warning)', display: 'inline-block'
          }} />
          <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--warning)' }}>
            Judge / Admin Session Active
          </h3>
        </div>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          Submission is restricted to registered competitors. Use the Admin Panel to register competitors and manage tasks.
        </p>
      </div>
    );
  }

  if (isClosed) {
    return (
      <div className="surface" style={{ padding: '22px 26px' }}>
        <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--danger)', marginBottom: 6 }}>
          Competition Closed
        </h3>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          This competition is no longer accepting submissions.
        </p>
      </div>
    );
  }

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.name.endsWith('.ipynb')) {
      showToast('Only .ipynb files are supported.', 'error');
      return;
    }
    setUploading(true);
    setSelectedCellIds([]);
    setCells([]);
    try {
      const res = await ChallengeService.parseNotebook(challenge.id, file);
      if (res.ok) {
        setCells(res.data.cells || []);
        setFileName(res.data.filename);
        showToast(`Parsed ${res.data.cells?.length || 0} cells from "${res.data.filename}".`);
      } else {
        showToast(res.data?.error || 'Failed to parse notebook.', 'error');
      }
    } catch {
      showToast('Network error parsing notebook.', 'error');
    } finally {
      setUploading(false);
    }
  };

  const toggleCell = (id) => {
    setSelectedCellIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const handleSubmit = async () => {
    if (selectedCellIds.length === 0) {
      showToast('Select at least one cell to submit.', 'error');
      return;
    }
    const selected = cells.filter(c => selectedCellIds.includes(c.id));
    setSubmitting(true);
    try {
      const res = await TaskService.submit(task.id, selected);
      if (res.ok) {
        showToast('Submission queued for evaluation!');
        setCells([]);
        setSelectedCellIds([]);
        setFileName('');
      } else {
        showToast(res.data?.error || 'Submission failed.', 'error');
      }
    } catch {
      showToast('Network error during submission.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="surface" style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          Submit Solution
        </h3>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          {challenge.max_eval_requests} submissions/day limit
        </span>
      </div>

      {/* Upload zone */}
      <div className="file-drop-zone">
        <input
          type="file"
          accept=".ipynb"
          id="notebook-upload"
          style={{ display: 'none' }}
          onChange={handleUpload}
        />
        <label htmlFor="notebook-upload" style={{ cursor: 'pointer' }}>
          {uploading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: 'var(--text-secondary)' }}>
              <div className="animate-spin" style={{ width: 16, height: 16, border: '2px solid var(--border)', borderTopColor: 'var(--accent)', borderRadius: '50%' }} />
              Parsing notebook...
            </div>
          ) : fileName ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--accent)' }}>📓 {fileName}</span>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Click to replace</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <svg width="28" height="28" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" style={{ color: 'var(--text-muted)' }}>
                <path strokeLinecap="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Upload Jupyter Notebook (.ipynb)</span>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Click or drag & drop</span>
            </div>
          )}
        </label>
      </div>

      {/* Cell picker */}
      {cells.length > 0 && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <h4 style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Select Cells ({selectedCellIds.length}/{cells.filter(c => c.type === 'code').length} code cells)
            </h4>
            <button
              onClick={() => setSelectedCellIds(cells.filter(c => c.type === 'code').map(c => c.id))}
              className="btn btn-ghost btn-sm"
            >
              Select all code
            </button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 300, overflowY: 'auto' }}>
            {cells.map((cell, idx) => {
              const isCode = cell.type === 'code';
              const isSelected = selectedCellIds.includes(cell.id);
              return (
                <div
                  key={cell.id}
                  onClick={() => isCode && toggleCell(cell.id)}
                  style={{
                    display: 'flex', gap: 10, alignItems: 'flex-start',
                    padding: '8px 12px',
                    background: isSelected ? 'var(--accent-soft)' : 'var(--bg-elevated)',
                    border: `1px solid ${isSelected ? 'var(--accent-border)' : 'var(--border)'}`,
                    borderRadius: 'var(--radius-sm)',
                    cursor: isCode ? 'pointer' : 'default',
                    opacity: isCode ? 1 : 0.5,
                    transition: 'all 0.12s ease',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => isCode && toggleCell(cell.id)}
                    disabled={!isCode}
                    style={{ marginTop: 2, accentColor: 'var(--accent)', flexShrink: 0 }}
                    readOnly
                  />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
                      <span style={{
                        fontSize: '0.68rem', fontWeight: 700,
                        color: isCode ? 'var(--accent)' : 'var(--text-muted)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                      }}>
                        [{idx}] {cell.type}
                      </span>
                    </div>
                    <pre className="code-panel" style={{
                      padding: '6px 10px', fontSize: '0.72rem', maxHeight: 80,
                      overflow: 'hidden', borderRadius: 'var(--radius-xs)',
                    }}>
                      {(cell.source || '').slice(0, 300)}{cell.source?.length > 300 ? '...' : ''}
                    </pre>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Submit */}
      {cells.length > 0 && (
        <Button
          onClick={handleSubmit}
          disabled={submitting || selectedCellIds.length === 0}
          size="lg"
          className="w-full"
        >
          {submitting ? (
            <>
              <div className="animate-spin" style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%' }} />
              Submitting...
            </>
          ) : (
            `Submit ${selectedCellIds.length} cell${selectedCellIds.length !== 1 ? 's' : ''} for Evaluation`
          )}
        </Button>
      )}
    </div>
  );
}
