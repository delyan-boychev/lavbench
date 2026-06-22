import React from 'react';
import { useTranslation } from 'react-i18next';

export default function SidebarNav({ adminSubTab, setAdminSubTab, currentUser,
  setIsCreatingTask, setEditingTask, setIsCreatingStage, setEditingStage, setFinalizingStage }) {
  const { t } = useTranslation();

  const resetSubViews = () => {
    setIsCreatingTask(false);
    setEditingTask(null);
    setIsCreatingStage(false);
    setEditingStage(null);
    setFinalizingStage(null);
  };

  const btnClass = (tab) =>
    `text-left px-4 py-2.5 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer ${
      adminSubTab === tab
        ? 'bg-indigo-600 text-white shadow-md'
        : 'text-slate-300 hover:bg-slate-800'
    }`;

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-5 rounded-2xl flex flex-col gap-1.5">
      <h2 className="text-xs font-extrabold uppercase text-slate-400 tracking-wider mb-3 px-2">
        {t('admin.jury_control_hub')}
      </h2>

      {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
        <button onClick={() => { setAdminSubTab('competition-mgmt'); resetSubViews(); }} className={btnClass('competition-mgmt')}>
          {t('admin.manage_competitions')}
        </button>
      )}

      {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
        <button onClick={() => { setAdminSubTab('challenge-config'); resetSubViews(); }} className={btnClass('challenge-config')}>
          {t('admin.create_competition')}
        </button>
      )}

      <button onClick={() => { setAdminSubTab('competitor-reg'); resetSubViews(); }} className={btnClass('competitor-reg')}>
        {t('admin.competitor_registrations')}
      </button>

      {currentUser.role === 'admin' && (
        <button onClick={() => { setAdminSubTab('backups'); resetSubViews(); }} className={btnClass('backups')}>
          {t('admin.database_backup')}
        </button>
      )}

      {currentUser.role === 'admin' && (
        <button onClick={() => { setAdminSubTab('user-management'); resetSubViews(); }} className={btnClass('user-management')}>
          {t('admin.user_management')}
        </button>
      )}

      {(currentUser.role === 'admin' || currentUser.role === 'jury') && (
        <button onClick={() => { setAdminSubTab('workers-stats'); resetSubViews(); }} className={btnClass('workers-stats')}>
          {t('admin.workers_resources')}
        </button>
      )}
    </div>
  );
}
