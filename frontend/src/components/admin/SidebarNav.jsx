import React from 'react';
import { useTranslation } from 'react-i18next';

export default function SidebarNav({ adminSubTab, onSelectTab, currentUser }) {
  const { t } = useTranslation();
  const isAdmin = currentUser.role === 'admin';
  const isAdminOrJury = isAdmin || currentUser.role === 'jury';

  const tabs = [
    { id: 'competition-mgmt', label: t('admin.manage_competitions'), show: isAdminOrJury },
    { id: 'challenge-config', label: t('admin.create_competition'), show: isAdmin },
    { id: 'competitor-reg', label: t('admin.competitor_registrations'), show: true },
    { id: 'backups', label: t('admin.database_backup'), show: isAdmin },
    { id: 'user-management', label: t('admin.user_management'), show: isAdmin },
    { id: 'audit-logs', label: t('admin.audit_logs') || 'Audit Logs', show: isAdmin },
    { id: 'workers-stats', label: t('admin.workers_resources'), show: isAdminOrJury },
    { id: 'submission-queue', label: t('admin.submission_queue.title'), show: isAdminOrJury },
  ];

  return (
    <div className="admin-card p-5 flex flex-col gap-1.5">
      <h2 className="text-xs font-extrabold uppercase text-slate-400 tracking-wider mb-3 px-2">
        {t('admin.jury_control_hub')}
      </h2>
      {tabs
        .filter((tab) => tab.show)
        .map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => onSelectTab(tab.id)}
            aria-current={adminSubTab === tab.id ? 'page' : undefined}
            className={`text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${
              adminSubTab === tab.id
                ? 'bg-indigo-600 text-white shadow-md'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
    </div>
  );
}
