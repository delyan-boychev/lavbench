import React from 'react';
import { useTranslation } from 'react-i18next';
import { CheckIcon, CrossIcon, SpinnerIcon, ClockIcon, GearIcon, DotIcon, SnowflakeIcon, FlagIcon } from './icons';

const ICON = {
  completed:        CheckIcon,
  failed:           CrossIcon,
  running:          SpinnerIcon,
  queued:           ClockIcon,
  building_env:     GearIcon,
  running_inference: SpinnerIcon,
  evaluating:       GearIcon,
  active:           DotIcon,
  archived:         DotIcon,
  not_started:      ClockIcon,
  frozen:           SnowflakeIcon,
  ended:            FlagIcon,
  finalized:        CheckIcon,
};

const CONFIG = {
  completed:        { style: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400", key: "badge.completed" },
  failed:           { style: "border-rose-500/30 bg-rose-500/10 text-rose-400", key: "badge.failed" },
  running:          { style: "border-blue-500/30 bg-blue-500/10 text-blue-400", key: "badge.running" },
  queued:           { style: "border-amber-500/30 bg-amber-500/10 text-amber-400", key: "badge.queued" },
  building_env:     { style: "border-purple-500/30 bg-purple-500/10 text-purple-400", key: "badge.building_env" },
  running_inference:{ style: "border-cyan-500/30 bg-cyan-500/10 text-cyan-400", key: "badge.running_inference" },
  evaluating:       { style: "border-indigo-500/30 bg-indigo-500/10 text-indigo-400", key: "badge.evaluating" },
  active:           { style: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400", key: "badge.active" },
  archived:         { style: "border-slate-500/40 bg-slate-800/60 text-slate-400", key: "badge.archived" },
  not_started:      { style: "border-blue-500/30 bg-blue-500/10 text-blue-400", key: "badge.not_started" },
  frozen:           { style: "border-cyan-500/30 bg-cyan-500/10 text-cyan-400", key: "badge.frozen" },
  ended:            { style: "border-amber-500/30 bg-amber-500/10 text-amber-400", key: "badge.ended" },
  finalized:        { style: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400", key: "badge.finalized" },
  admin:            { style: "border-rose-500/30 bg-rose-500/10 text-rose-400", key: "badge.admin" },
  jury:             { style: "border-amber-500/30 bg-amber-500/10 text-amber-400", key: "badge.jury" },
  competitor:       { style: "border-blue-500/30 bg-blue-500/10 text-blue-400", key: "badge.competitor" },
};

export default function Badge({ status }) {
  const { t } = useTranslation();
  const cfg = CONFIG[status] || { style: "border-slate-500/30 bg-slate-800 text-slate-400", key: null };
  const StatusIcon = ICON[status];
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border inline-flex items-center gap-1 leading-none ${cfg.style}`}>
      {StatusIcon && <StatusIcon className="w-3 h-3" />}
      {cfg.key ? t(cfg.key) : status?.toUpperCase()}
    </span>
  );
}
