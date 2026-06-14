import React from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';

export default function BackupManager({ handleDownloadBackup }) {
  const { t } = useTranslation();

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
      <h2 className="text-xl font-bold text-white mb-2">{t('admin.backups.database_backups_security')}</h2>
      <p className="text-slate-400 text-xs mb-6">{t('admin.backups.database_backups_desc')}</p>
      
      <div className="bg-slate-900/40 border border-white/5 p-6 rounded-xl flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h4 className="font-bold text-slate-200 text-sm">{t('admin.backups.download_postgres_backup')}</h4>
          <p className="text-slate-500 text-xs mt-1">{t('admin.backups.download_postgres_backup_desc')}</p>
        </div>
        <Button variant="accent" onClick={handleDownloadBackup}>{t('admin.backups.download_backup_dump_btn')}</Button>
      </div>
    </div>
  );
}
