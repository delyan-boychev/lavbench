import React from 'react';
import Badge from '../ui/Badge';

function StatCard({ label, value, accent }) {
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-md)',
      padding: '12px 16px',
    }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: '0.9rem', fontWeight: 600, color: accent || 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

export default function ChallengeOverview({ challenge }) {
  if (!challenge) return null;
  return (
    <div className="surface" style={{ padding: '24px 28px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <h1 style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {challenge.title}
        </h1>
        <Badge status={challenge.is_archived ? 'archived' : 'active'} />
      </div>

      {challenge.description && (
        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 18, lineHeight: 1.65 }}>
          {challenge.description}
        </p>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <StatCard label="Daily Limit" value={`${challenge.max_eval_requests} submissions`} />
        <StatCard label="RAM Limit" value={`${(challenge.ram_limit_mb / 1024).toFixed(0)} GB`} />
        <StatCard label="Time Limit" value={`${challenge.time_limit_sec}s`} />
        <StatCard label="Hardware" value={challenge.gpu_required ? 'GPU Cluster' : 'CPU Only'} accent={challenge.gpu_required ? 'var(--accent)' : undefined} />
        {challenge.tasks && (
          <StatCard label="Tasks" value={challenge.tasks.length} />
        )}
      </div>
    </div>
  );
}
