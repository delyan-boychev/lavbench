import React from 'react';

const CONFIG = {
  completed: { style: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400", label: "✓ Completed" },
  failed:    { style: "border-rose-500/30 bg-rose-500/10 text-rose-400", label: "✗ Failed" },
  running:   { style: "border-blue-500/30 bg-blue-500/10 text-blue-400", label: "⟳ Running" },
  queued:    { style: "border-amber-500/30 bg-amber-500/10 text-amber-400", label: "⏳ Queued" },
  building_env: { style: "border-purple-500/30 bg-purple-500/10 text-purple-400", label: "⚙ Building Env" },
  running_inference: { style: "border-cyan-500/30 bg-cyan-500/10 text-cyan-400", label: "⚙ Inference" },
  evaluating: { style: "border-indigo-500/30 bg-indigo-500/10 text-indigo-400", label: "⚙ Evaluating" },
  active:    { style: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400", label: "● Active" },
  archived:  { style: "border-slate-500/40 bg-slate-800/60 text-slate-400", label: "■ Archived" },
  not_started: { style: "border-blue-500/30 bg-blue-500/10 text-blue-400", label: "⏳ Not Started" },
  frozen:    { style: "border-cyan-500/30 bg-cyan-500/10 text-cyan-400", label: "❄ Frozen" },
  ended:     { style: "border-amber-500/30 bg-amber-500/10 text-amber-400", label: "⏱ Ended" },
  finalized: { style: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400", label: "✓ Finalized" },
  admin:     { style: "border-rose-500/30 bg-rose-500/10 text-rose-400", label: "Admin" },
  jury:      { style: "border-amber-500/30 bg-amber-500/10 text-amber-400", label: "Jury" },
  competitor:{ style: "border-blue-500/30 bg-blue-500/10 text-blue-400", label: "Competitor" },
};

export default function Badge({ status }) {
  const cfg = CONFIG[status] || { style: "border-slate-500/30 bg-slate-800 text-slate-400", label: status?.toUpperCase() };
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border inline-flex items-center gap-1 leading-none ${cfg.style}`}>
      {cfg.label}
    </span>
  );
}
