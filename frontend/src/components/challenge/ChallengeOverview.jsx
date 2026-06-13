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
    return `${getPart('year')}-${getPart('month')}-${getPart('day')} ${getPart('hour')}:${getPart('minute')} (${timezone || 'UTC'})`;
  } catch (err) {
    const d = new Date(dateStr);
    const pad = (n) => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())} (Local)`;
  }
};

export default function ChallengeOverview({ challenge }) {
  if (!challenge) return null;

  const getStatus = () => {
    if (challenge.is_archived) return 'archived';
    if (challenge.scores_finalized) return 'finalized';
    if (challenge.is_frozen) return 'frozen';
    
    const now = new Date();
    const startTime = challenge.start_time ? new Date(challenge.start_time) : null;
    const endTime = challenge.end_time ? new Date(challenge.end_time) : null;
    
    if (startTime && now < startTime) return 'not_started';
    if (endTime && now > endTime) return 'ended';
    
    return 'active';
  };

  const status = getStatus();
  const hasStarted = status !== 'not_started';

  return (
    <div className="surface" style={{ padding: '24px 28px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <h1 style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {challenge.title}
        </h1>
        <Badge status={status} />
      </div>

      {challenge.description && (
        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 18, lineHeight: 1.65 }}>
          {challenge.description}
        </p>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginBottom: 20, fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <span><strong>Start:</strong> {formatDateTime(challenge.start_time, challenge.timezone)}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span><strong>End:</strong> {formatDateTime(challenge.end_time, challenge.timezone)}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <StatCard label="Daily Limit" value={`${challenge.max_eval_requests} submissions`} />
        <StatCard label="RAM Limit" value={`${(challenge.ram_limit_mb / 1024).toFixed(0)} GB`} />
        <StatCard label="Time Limit" value={`${challenge.time_limit_sec}s`} />
        <StatCard label="Hardware" value={challenge.gpu_required ? 'GPU Cluster' : 'CPU Only'} accent={challenge.gpu_required ? 'var(--accent)' : undefined} />
        <StatCard label="Tasks" value={challenge.num_tasks !== undefined ? challenge.num_tasks : (challenge.tasks ? challenge.tasks.length : 0)} />
      </div>

      {hasStarted && challenge.stages && challenge.stages.length > 0 && (
        <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
          <h2 style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            Competition Stages
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[...challenge.stages].sort((a, b) => a.stage_number - b.stage_number).map(st => {
              const now = new Date();
              const start = new Date(st.start_time);
              const end = new Date(st.end_time);
              let statusText = 'Upcoming';
              let statusColor = 'var(--text-muted)';
              if (now >= start && now <= end) {
                statusText = 'Active Now';
                statusColor = 'var(--info)';
              } else if (now > end) {
                statusText = 'Ended';
                statusColor = 'var(--accent)';
              }
              if (st.is_finalized) {
                statusText = `Finalized (${st.finalize_type})`;
                statusColor = 'var(--success)';
              }

              return (
                <div key={st.id} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)',
                  padding: '10px 14px',
                  fontSize: '0.8rem'
                }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                      Stage {st.stage_number}: {st.title}
                    </span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      {formatDateTime(st.start_time, challenge.timezone)} to {formatDateTime(st.end_time, challenge.timezone)}
                    </span>
                  </div>
                  <span style={{ fontWeight: 700, color: statusColor, fontSize: '0.75rem', textTransform: 'uppercase' }}>
                    {statusText}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
