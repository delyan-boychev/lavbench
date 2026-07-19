import React from 'react';
import { useTranslation } from 'react-i18next';
import { Clock } from 'lucide-react';

/**
 * CountdownTimer Component
 * Encapsulates the 1-second interval ticker and rendering logic for challenge timer display,
 * preventing unnecessary top-level Navbar re-renders.
 *
 * @param {object} props
 * @param {object} props.selectedChallenge
 */
export default function CountdownTimer({ selectedChallenge }) {
  const { t } = useTranslation();
  const [nowMs, setNowMs] = React.useState(() => Date.now());

  React.useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const activeStage = React.useMemo(() => {
    if (!selectedChallenge?.stages || selectedChallenge.stages.length === 0) return null;
    const now = nowMs;
    const graceMs = (selectedChallenge.deadline_grace_period_seconds || 60) * 1000;
    return selectedChallenge.stages.find((st) => {
      const start = new Date(st.start_time).getTime();
      const end = new Date(st.end_time).getTime();
      return now >= start && now <= end + graceMs && !st.is_finalized;
    });
  }, [selectedChallenge, nowMs]);

  const upcomingStage = React.useMemo(() => {
    if (!selectedChallenge?.stages || selectedChallenge.stages.length === 0 || activeStage)
      return null;
    const now = nowMs;
    const upcoming = selectedChallenge.stages.filter((st) => {
      const start = new Date(st.start_time).getTime();
      return start > now;
    });
    if (upcoming.length === 0) return null;
    return upcoming.sort(
      (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
    )[0];
  }, [selectedChallenge, activeStage, nowMs]);

  const timeRemainingMs = React.useMemo(() => {
    const now = nowMs;
    if (activeStage) {
      return new Date(activeStage.end_time).getTime() - now;
    }
    if (selectedChallenge?.end_time) {
      const start = new Date(selectedChallenge.start_time).getTime();
      const end = new Date(selectedChallenge.end_time).getTime();
      const graceMs = (selectedChallenge.deadline_grace_period_seconds || 60) * 1000;
      if (now >= start && now <= end + graceMs && !selectedChallenge.scores_finalized) {
        return end - now;
      }
    }
    return null;
  }, [activeStage, selectedChallenge, nowMs]);

  const timeUntilStartMs = React.useMemo(() => {
    if (!selectedChallenge?.start_time) return null;
    const start = new Date(selectedChallenge.start_time).getTime();
    const diff = start - nowMs;
    if (diff <= 0) return null;
    if (selectedChallenge.is_archived || selectedChallenge.scores_finalized) return null;
    return diff;
  }, [selectedChallenge, nowMs]);

  const timeUntilStageStartMs = React.useMemo(() => {
    if (upcomingStage) {
      return new Date(upcomingStage.start_time).getTime() - nowMs;
    }
    return null;
  }, [upcomingStage, nowMs]);

  if (timeRemainingMs !== null) {
    const graceMs = (selectedChallenge?.deadline_grace_period_seconds || 60) * 1000;
    const isGracePeriod = timeRemainingMs < 0;

    let color = '#10b981'; // Green
    let isFlashing = false;

    if (isGracePeriod) {
      color = '#f97316'; // Amber/Orange
      isFlashing = true;
    } else {
      const minutesLeft = timeRemainingMs / 60000;
      if (minutesLeft <= 5) {
        color = '#ef4444'; // Red
        isFlashing = true;
      } else if (minutesLeft <= 15) {
        color = '#ef4444'; // Red
      } else if (minutesLeft <= 30) {
        color = '#f59e0b'; // Yellow
      }
    }

    let timeStr;
    if (isGracePeriod) {
      const remainingGraceSecs = Math.ceil((graceMs + timeRemainingMs) / 1000);
      timeStr = `${remainingGraceSecs}s`;
    } else {
      const totalSecs = Math.ceil(timeRemainingMs / 1000);
      const hours = Math.floor(totalSecs / 3600);
      const minutes = Math.floor((totalSecs % 3600) / 60);
      const seconds = totalSecs % 60;
      timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    const labelStr = isGracePeriod
      ? t('nav.grace_period')
      : activeStage
        ? t('nav.stage_time_left', { stage: activeStage.stage_number })
        : t('nav.time_left');

    const titleStr = isGracePeriod
      ? t('nav.grace_period_title')
      : activeStage
        ? t('nav.stage_time_left_title', { stage: activeStage.stage_number })
        : t('nav.time_left_title');

    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 12px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.78rem',
          fontWeight: 700,
          color: color,
          userSelect: 'none',
          transition: 'all 0.2s ease',
        }}
        className={isFlashing ? 'animate-flash-red' : ''}
        title={titleStr}
      >
        <Clock size={13} strokeWidth={2.5} />
        <span>
          {labelStr}: {timeStr}
        </span>
      </div>
    );
  }

  if (timeUntilStageStartMs !== null && upcomingStage) {
    const totalSecs = Math.ceil(timeUntilStageStartMs / 1000);
    const hours = Math.floor(totalSecs / 3600);
    const minutes = Math.floor((totalSecs % 3600) / 60);
    const seconds = totalSecs % 60;
    const totalMinutes = timeUntilStageStartMs / 60000;

    let color = '#a855f7'; // Purple
    let isFlashing = false;

    if (totalMinutes <= 5) {
      color = '#c084fc';
      isFlashing = true;
    } else if (totalMinutes <= 30) {
      color = '#c084fc';
    }

    const timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 12px',
          background: 'rgba(168, 85, 247, 0.08)',
          border: '1px solid rgba(168, 85, 247, 0.2)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.78rem',
          fontWeight: 700,
          color: color,
          userSelect: 'none',
          transition: 'all 0.2s ease',
        }}
        className={isFlashing ? 'animate-flash-purple' : ''}
        title={t('nav.stage_starts_in_title', { stage: upcomingStage.stage_number })}
      >
        <Clock size={13} strokeWidth={2.5} />
        <span>
          {t('nav.stage_starts_in', { stage: upcomingStage.stage_number })}: {timeStr}
        </span>
      </div>
    );
  }

  if (timeUntilStartMs !== null) {
    const totalSecs = Math.ceil(timeUntilStartMs / 1000);
    const hours = Math.floor(totalSecs / 3600);
    const minutes = Math.floor((totalSecs % 3600) / 60);
    const seconds = totalSecs % 60;
    const totalMinutes = timeUntilStartMs / 60000;

    let color = '#a855f7';
    let isFlashing = false;

    if (totalMinutes <= 5) {
      color = '#c084fc';
      isFlashing = true;
    } else if (totalMinutes <= 30) {
      color = '#c084fc';
    }

    const timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 12px',
          background: 'rgba(168, 85, 247, 0.08)',
          border: '1px solid rgba(168, 85, 247, 0.2)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '0.78rem',
          fontWeight: 700,
          color: color,
          userSelect: 'none',
          transition: 'all 0.2s ease',
        }}
        className={isFlashing ? 'animate-flash-purple' : ''}
        title={t('nav.starts_in_title')}
      >
        <Clock size={13} strokeWidth={2.5} />
        <span>
          {t('nav.starts_in')}: {timeStr}
        </span>
      </div>
    );
  }

  return null;
}
