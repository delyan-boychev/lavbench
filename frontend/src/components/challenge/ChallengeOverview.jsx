import React from 'react';
import Badge from '../ui/Badge';
import { useTranslation } from 'react-i18next';
import { formatDateTime } from '../../utils/formatDate';

function StatCard({ label, value, accent = undefined }) {
  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '12px 16px',
      }}
    >
      <div
        style={{
          fontSize: '0.7rem',
          color: 'var(--text-muted)',
          fontWeight: 600,
          marginBottom: 4,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: '0.9rem', fontWeight: 600, color: accent || 'var(--text-primary)' }}>
        {value}
      </div>
    </div>
  );
}

export default function ChallengeOverview({ challenge }) {
  const { t } = useTranslation();
  const [nowMs, setNowMs] = React.useState(() => Date.now());

  React.useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  if (!challenge) return null;

  const getStatus = () => {
    if (challenge.is_archived) return 'archived';
    if (challenge.is_frozen) return 'frozen';
    if (challenge.scores_finalized && challenge.reveal_results) return 'public';
    if (challenge.scores_finalized && !challenge.reveal_results) return 'internal';

    const startTime = challenge.start_time ? new Date(challenge.start_time).getTime() : null;
    const endTime = challenge.end_time ? new Date(challenge.end_time).getTime() : null;

    if (startTime && nowMs < startTime) return 'future';
    if (endTime && nowMs > endTime) return 'grading';

    return 'active';
  };

  const status = getStatus();
  const hasStarted = status !== 'future';

  const renderStartTimer = () => {
    if (!challenge.start_time || status !== 'future') return null;

    const timeUntilMs = new Date(challenge.start_time).getTime() - nowMs;
    if (timeUntilMs <= 0) return null;

    const totalSecs = Math.ceil(timeUntilMs / 1000);
    const days = Math.floor(totalSecs / 86400);
    const hours = Math.floor((totalSecs % 86400) / 3600);
    const minutes = Math.floor((totalSecs % 3600) / 60);
    const seconds = totalSecs % 60;

    const totalMinutes = timeUntilMs / 60000;
    let color = '#a855f7';
    let isFlashing = false;

    if (totalMinutes <= 5) {
      color = '#c084fc';
      isFlashing = true;
    } else if (totalMinutes <= 30) {
      color = '#c084fc';
    }

    const timeStr =
      days > 0
        ? `${days}d ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
        : `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 16px',
          background: 'rgba(168, 85, 247, 0.08)',
          border: '1px solid rgba(168, 85, 247, 0.2)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.85rem',
          fontWeight: 700,
          color: color,
          userSelect: 'none',
          transition: 'all 0.2s ease',
          marginBottom: 12,
          width: 'fit-content',
        }}
        className={isFlashing ? 'animate-flash-purple' : ''}
        title={t('nav.starts_in_title')}
      >
        <svg
          width="15"
          height="15"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth="2.5"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <span>
          {t('challenge.starts_in')}: {timeStr}
        </span>
      </div>
    );
  };

  return (
    <div className="surface" style={{ padding: '24px 28px' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 12,
          marginBottom: 12,
        }}
      >
        <h1 style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {challenge.title}
        </h1>
        <Badge status={status} />
      </div>

      {renderStartTimer()}

      {challenge.description && (
        <p
          style={{
            fontSize: '0.875rem',
            color: 'var(--text-secondary)',
            marginBottom: 18,
            lineHeight: 1.65,
          }}
        >
          {challenge.description}
        </p>
      )}

      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 20,
          marginBottom: 20,
          fontSize: '0.8125rem',
          color: 'var(--text-secondary)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg
            width="14"
            height="14"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
            />
          </svg>
          <span>
            <strong>{t('challenge.start')}</strong>{' '}
            {formatDateTime(challenge.start_time, challenge.timezone)}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg
            width="14"
            height="14"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span>
            <strong>{t('challenge.end')}</strong>{' '}
            {formatDateTime(challenge.end_time, challenge.timezone)}
          </span>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: 10,
          paddingTop: 16,
          borderTop: '1px solid var(--border)',
        }}
      >
        <StatCard
          label={t('challenge.daily_limit_label')}
          value={t('challenge.submissions_count', { count: challenge.max_eval_requests })}
        />
        <StatCard
          label={t('challenge.ram_limit_label')}
          value={t('challenge.gb', { count: (challenge.ram_limit_mb / 1024).toFixed(0) })}
        />
        <StatCard
          label={t('challenge.time_limit_label')}
          value={t('challenge.seconds_short', { count: challenge.time_limit_sec })}
        />
        <StatCard
          label={t('challenge.hardware_label')}
          value={challenge.gpu_required ? t('challenge.gpu_cluster') : t('challenge.cpu_only')}
          accent={challenge.gpu_required ? 'var(--accent)' : undefined}
        />
        <StatCard
          label={t('challenge.tasks_label')}
          value={
            challenge.num_tasks !== undefined
              ? challenge.num_tasks
              : challenge.tasks
                ? challenge.tasks.length
                : 0
          }
        />
      </div>

      {hasStarted && challenge.stages && challenge.stages.length > 0 && (
        <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
          <h2
            style={{
              fontSize: '0.85rem',
              fontWeight: 700,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              marginBottom: 12,
            }}
          >
            {t('challenge.competition_stages')}
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[...challenge.stages]
              .sort((a, b) => a.stage_number - b.stage_number)
              .map((st) => {
                const now = new Date();
                const start = new Date(st.start_time);
                const end = new Date(st.end_time);
                let stageStatus;
                if (st.is_finalized && st.reveal_results) {
                  stageStatus = 'public';
                } else if (st.is_finalized && !st.reveal_results) {
                  stageStatus = 'internal';
                } else if (now < start) {
                  stageStatus = 'future';
                } else if (now > end) {
                  stageStatus = 'grading';
                } else {
                  stageStatus = 'active';
                }

                return (
                  <div
                    key={st.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-md)',
                      padding: '10px 14px',
                      fontSize: '0.8rem',
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                        {t('challenge.stage_title', { number: st.stage_number, title: st.title })}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        {t('challenge.stage_time_range', {
                          start: formatDateTime(st.start_time, challenge.timezone),
                          end: formatDateTime(st.end_time, challenge.timezone),
                        })}
                      </span>
                    </div>
                    <Badge status={stageStatus} />
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
