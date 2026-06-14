import React from 'react';
import EmptyState from '../ui/EmptyState';
import { useTranslation } from 'react-i18next';
import { FolderIcon } from '../ui/icons';

export default function TaskSidebar({ tasks, selectedTask, onSelect }) {
  const { t } = useTranslation();

  if (!tasks || tasks.length === 0) {
    return (
      <EmptyState 
        minHeight={120} 
        message={t('challenge.no_tasks_published')}
        icon={
          <svg width="28" height="28" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
            <path strokeLinecap="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
        }
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
        {t('challenge.tasks_with_count', { count: tasks.length })}
      </div>
      {tasks.map((task, idx) => {
        const isSelected = selectedTask?.id === task.id;
        return (
          <button
            key={task.id}
            id={`task-btn-${task.id}`}
            onClick={() => onSelect(task)}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              padding: '12px 14px',
              background: isSelected ? 'var(--accent-soft)' : 'var(--bg-surface)',
              border: `1px solid ${isSelected ? 'var(--accent-border)' : 'var(--border)'}`,
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'all 0.15s ease',
              width: '100%',
            }}
            onMouseEnter={e => { if (!isSelected) { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.borderColor = 'var(--border-hover)'; } }}
            onMouseLeave={e => { if (!isSelected) { e.currentTarget.style.background = 'var(--bg-surface)'; e.currentTarget.style.borderColor = 'var(--border)'; } }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{
                fontSize: '0.68rem', fontWeight: 700,
                color: isSelected ? 'var(--accent)' : 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.05em',
              }}>
                {t('challenge.task_number', { number: idx + 1 })}
              </span>
              {task.files?.length > 0 && (
                <span style={{
                  fontSize: '0.68rem', color: 'var(--info)',
                  background: 'var(--info-soft)', border: '1px solid var(--info-border)',
                  padding: '1px 6px', borderRadius: 'var(--radius-xs)',
                }}>
                    <FolderIcon className="w-3.5 h-3.5 inline mr-1" />{task.files.length}
                </span>
              )}
            </div>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.4 }}>
              {task.title}
            </span>
            {task.description && (
              <span style={{
                fontSize: '0.75rem', color: 'var(--text-secondary)',
                overflow: 'hidden', display: '-webkit-box',
                WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                lineHeight: 1.5,
              }}>
                {task.description.replace(/[#*`_]/g, '').slice(0, 100)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
