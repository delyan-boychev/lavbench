import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  X,
  Loader2,
  Clock,
  Settings,
  Activity,
  Snowflake,
  Flag,
  Archive,
  CalendarClock,
  Lock,
  Eye,
  CircleCheck,
  TriangleAlert,
  CircleAlert,
  CircleX,
  Wrench,
  Wifi,
  WifiOff,
  ServerCrash,
  Power,
  Upload,
  Hourglass,
  CircleHelp,
} from 'lucide-react';

const ICON = {
  completed: Check,
  failed: X,
  failed_infra: ServerCrash,
  running: Loader2,
  queued: Clock,
  building_env: Settings,
  running_inference: Loader2,
  evaluating: Settings,
  active: Activity,
  archived: Archive,
  not_started: Clock,
  future: CalendarClock,
  frozen: Snowflake,
  ended: Flag,
  finalized: Check,
  grading: Clock,
  internal: Lock,
  public: Eye,
  operational: CircleCheck,
  degraded_performance: TriangleAlert,
  partial_outage: CircleAlert,
  major_outage: CircleX,
  under_maintenance: Wrench,
  online: Wifi,
  stale: WifiOff,
  env_off: Power,
  env_uploading: Upload,
  env_preparing: Hourglass,
  env_ready: CircleCheck,
  env_problem: CircleAlert,
  env_unknown: CircleHelp,
  env_not_open: CalendarClock,
  env_closed: Lock,
};

const CONFIG = {
  completed: {
    style: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
    key: 'badge.completed',
  },
  failed: { style: 'border-rose-500/30 bg-rose-500/10 text-rose-400', key: 'badge.failed' },
  failed_infra: {
    style: 'border-orange-500/30 bg-orange-500/10 text-orange-400',
    key: 'badge.failed_infra',
  },
  running: { style: 'border-blue-500/30 bg-blue-500/10 text-blue-400', key: 'badge.running' },
  queued: { style: 'border-amber-500/30 bg-amber-500/10 text-amber-400', key: 'badge.queued' },
  building_env: {
    style: 'border-purple-500/30 bg-purple-500/10 text-purple-400',
    key: 'badge.building_env',
  },
  running_inference: {
    style: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-400',
    key: 'badge.running_inference',
  },
  evaluating: {
    style: 'border-indigo-500/30 bg-indigo-500/10 text-indigo-400',
    key: 'badge.evaluating',
  },
  active: {
    style: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400',
    key: 'badge.active',
  },
  archived: { style: 'border-slate-500/40 bg-slate-800/60 text-slate-400', key: 'badge.archived' },
  not_started: {
    style: 'border-blue-500/30 bg-blue-500/10 text-blue-400',
    key: 'badge.not_started',
  },
  future: {
    style: 'border-purple-500/30 bg-purple-500/10 text-purple-400',
    key: 'badge.future',
  },
  frozen: { style: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-400', key: 'badge.frozen' },
  ended: { style: 'border-amber-500/30 bg-amber-500/10 text-amber-400', key: 'badge.ended' },
  finalized: {
    style: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400',
    key: 'badge.finalized',
  },
  grading: {
    style: 'border-purple-500/30 bg-purple-500/10 text-purple-400',
    key: 'badge.grading',
  },
  internal: {
    style: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
    key: 'badge.internal',
  },
  public: {
    style: 'border-sky-500/30 bg-sky-500/10 text-sky-400',
    key: 'badge.public',
  },
  // Statuspage component statuses, from best to worst, plus maintenance
  operational: {
    style: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
    key: 'badge.operational',
  },
  degraded_performance: {
    style: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
    key: 'badge.degraded_performance',
  },
  partial_outage: {
    style: 'border-orange-500/30 bg-orange-500/10 text-orange-400',
    key: 'badge.partial_outage',
  },
  major_outage: {
    style: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
    key: 'badge.major_outage',
  },
  under_maintenance: {
    style: 'border-sky-500/30 bg-sky-500/10 text-sky-400',
    key: 'badge.under_maintenance',
  },
  online: {
    style: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
    key: 'badge.online',
  },
  stale: { style: 'border-amber-500/30 bg-amber-500/10 text-amber-400', key: 'badge.stale' },
  env_off: { style: 'border-slate-500/40 bg-slate-800/60 text-slate-400', key: 'badge.env_off' },
  env_uploading: {
    style: 'border-blue-500/30 bg-blue-500/10 text-blue-400',
    key: 'badge.env_uploading',
  },
  env_preparing: {
    style: 'border-indigo-500/30 bg-indigo-500/10 text-indigo-400',
    key: 'badge.env_preparing',
  },
  env_ready: {
    style: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
    key: 'badge.env_ready',
  },
  env_problem: {
    style: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
    key: 'badge.env_problem',
  },
  env_unknown: {
    style: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
    key: 'badge.env_unknown',
  },
  env_not_open: {
    style: 'border-purple-500/30 bg-purple-500/10 text-purple-400',
    key: 'badge.env_not_open',
  },
  env_closed: {
    style: 'border-slate-500/40 bg-slate-800/60 text-slate-400',
    key: 'badge.env_closed',
  },
  admin: { style: 'border-rose-500/30 bg-rose-500/10 text-rose-400', key: 'badge.admin' },
  jury: { style: 'border-amber-500/30 bg-amber-500/10 text-amber-400', key: 'badge.jury' },
  competitor: { style: 'border-blue-500/30 bg-blue-500/10 text-blue-400', key: 'badge.competitor' },
};

/**
 * @param {{ status: string, label?: string }} props `label` replaces the default text, e.g. with a percentage
 */
export default function Badge({ status, label = '' }) {
  const { t } = useTranslation();
  const cfg = CONFIG[status] || {
    style: 'border-slate-500/30 bg-slate-800 text-slate-400',
    key: null,
  };
  const StatusIcon = ICON[status];
  return (
    <span
      className={`text-[10px] font-bold px-2 py-0.5 rounded-full border inline-flex items-center gap-1 leading-none whitespace-nowrap ${cfg.style}`}
    >
      {StatusIcon && (
        <StatusIcon
          className={`w-3 h-3 ${status === 'running' || status === 'running_inference' ? 'animate-spin' : ''}`}
        />
      )}
      {label || (cfg.key ? t(cfg.key) : status?.toUpperCase())}
    </span>
  );
}
