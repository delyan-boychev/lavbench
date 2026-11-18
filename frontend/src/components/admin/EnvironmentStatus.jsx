import React from 'react';
import { useTranslation } from 'react-i18next';
import { Flag } from 'lucide-react';
import Badge from '../ui/Badge';
import { useApiErrorText } from '../../hooks/useApiError';
import { formatTimeAgo } from '../../utils/formatUnits';

const STATES = new Set(['off', 'uploading', 'preparing', 'ready', 'problem', 'unknown']);

function minutesSince(iso, nowMs) {
  const since = Date.parse(iso);
  if (Number.isNaN(since)) return null;
  return Math.max(1, Math.round(((nowMs ?? Date.now()) - since) / 60_000));
}

function badgeLabel(status, t, nowMs) {
  if (status.state === 'uploading' && status.progress != null) {
    return t('environment.status.uploading_progress', { progress: status.progress });
  }
  if (status.state === 'preparing' && status.since) {
    const minutes = minutesSince(status.since, nowMs);
    if (minutes !== null) return t('environment.status.preparing_for', { minutes });
  }
  return '';
}

// The jury gets the code without nanoColab's message; admins get both
// Only these codes carry nanoColab's own text; LavBench's other messages repeat the translation
const NANOCOLAB_MESSAGE_CODES = new Set([
  'ERR_ENVIRONMENT_SYNC_FAILED',
  'ERR_ENVIRONMENT_PACKAGE_FAILED',
]);

function problemLines(status, t, formatApiError) {
  const summary = formatApiError(
    {
      code: status.code,
      error: status.message,
      limit: status.limit,
      detail: status.detail,
      folder: status.folder,
      reason: status.reason,
    },
    'environment.status.problem_unknown',
  );
  const details =
    NANOCOLAB_MESSAGE_CODES.has(status.code) && status.message && status.message !== summary
      ? t('environment.status.details', { message: status.message })
      : '';
  return [summary, details].filter(Boolean);
}

/** "Checked 20 seconds ago", or "Last update 5 minutes ago" while the status is out of date. */
function freshnessLine(status, state, t, locale, nowMs) {
  const fetched = Date.parse(status?.fetched_at);
  if (Number.isNaN(fetched)) return '';
  const ago = formatTimeAgo(Math.max(0, ((nowMs ?? Date.now()) - fetched) / 1000), locale);
  return state === 'unknown'
    ? t('environment.status.last_update', { ago })
    : t('environment.status.checked', { ago });
}

/**
 * The admin and jury status chip of an environment, with the problem text and its age under it.
 * `nowMs` is the parent's clock, so the ages move on as it ticks.
 * @param {{ status: { state: string, published?: boolean, progress?: number | null, since?: string | null, alert?: boolean, code?: string | null, message?: string | null, limit?: string | null, detail?: string | null, folder?: string | null, reason?: string | null, fetched_at?: string | null }, nowMs?: number }} props
 */
export default function EnvironmentStatus({ status, nowMs = undefined }) {
  const { t, i18n } = useTranslation();
  const formatApiError = useApiErrorText();
  const state = STATES.has(status?.state) ? status.state : 'unknown';
  const lines = state === 'problem' ? problemLines(status, t, formatApiError) : [];
  const freshness = freshnessLine(status, state, t, i18n.language || 'en', nowMs);

  return (
    <div className="flex flex-col gap-1 min-w-0" data-testid="environment-status">
      <span className="inline-flex items-center gap-1.5">
        <Badge status={`env_${state}`} label={badgeLabel({ ...status, state }, t, nowMs)} />
        {status?.alert && (
          <Flag className="w-3.5 h-3.5 text-rose-400 shrink-0" aria-hidden="true" />
        )}
      </span>
      {status?.alert && (
        <p className="text-[11px] text-rose-400">{t('environment.status.alert')}</p>
      )}
      {lines.map((line) => (
        <p
          key={line}
          className={`text-[11px] break-words ${state === 'problem' ? 'text-rose-400' : 'text-slate-400'}`}
        >
          {line}
        </p>
      ))}
      {freshness && <p className="text-[11px] text-slate-400">{freshness}</p>}
    </div>
  );
}
