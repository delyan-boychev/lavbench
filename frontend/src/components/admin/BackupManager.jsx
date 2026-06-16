import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import EmptyState from '../ui/EmptyState';
import api from '../../services/ApiService';

export default function BackupManager({ challengeId }) {
  const { t } = useTranslation();
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [forcing, setForcing] = useState(false);

  const listUrl = challengeId
    ? `/api/admin/challenges/${challengeId}/backups`
    : '/api/admin/backups';

  const downloadBase = challengeId
    ? `/api/admin/challenges/${challengeId}/backups`
    : '/api/admin/backups';

  useEffect(() => {
    loadBackups();
    const eventSource = new EventSource('/api/admin/backups/live');
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.backups) {
          const filtered = challengeId
            ? data.backups.filter(b => b.filename.includes(challengeId) || true)
            : data.backups.filter(b => !b.filename.includes('submission_ended') && !b.filename.includes('grace_ended') && !b.filename.includes('finalized'));
          setBackups(data.backups);
          setLoading(false);
        }
        if (data.event?.status === 'completed') {
          setForcing(false);
          loadBackups();
        }
      } catch {}
    };
    return () => eventSource.close();
  }, [challengeId]);

  const loadBackups = async () => {
    try {
      const { ok, data } = await api.get(listUrl);
      if (ok) setBackups(data.backups || []);
    } catch {}
    setLoading(false);
  };

  const handleForce = async () => {
    setForcing(true);
    try {
      await api.post('/api/admin/backups/force');
    } catch {
      setForcing(false);
    }
  };

  const handleDelete = async (filename) => {
    try {
      await api.delete(`/api/admin/backups/${filename}`);
      loadBackups();
    } catch {}
  };

  const handleDownload = (filename) => {
    const url = `${downloadBase}/${filename}/download`;
    window.open(url, '_blank');
  };

  const formatDate = (iso) => {
    try { return new Date(iso).toLocaleString(); }
    catch { return iso; }
  };

  const stateLabel = (filename) => {
    if (filename.startsWith('submission_ended')) return t('admin.backups.submission_ended');
    if (filename.startsWith('grace_ended')) return t('admin.backups.grace_ended');
    if (filename.startsWith('finalized')) return t('admin.backups.finalized');
    return '';
  };

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-bold text-white">
          {challengeId ? t('admin.backups.competition_backups') : t('admin.backups.database_backups_security')}
        </h2>
        {!challengeId && (
          <Button variant="accent" onClick={handleForce} disabled={forcing}>
            {forcing ? t('admin.backups.forcing') : t('admin.backups.force_now')}
          </Button>
        )}
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-500 text-sm">{t('common.loading')}</div>
      ) : backups.length === 0 ? (
        <EmptyState message={t('admin.backups.no_backups')} />
      ) : (
        <div className="flex flex-col gap-3">
          {backups.map(b => (
            <div key={b.filename} className="flex items-center justify-between gap-4 bg-slate-900/40 border border-white/5 p-4 rounded-xl flex-wrap">
              <div className="flex flex-col gap-1 min-w-0">
                <span className="font-bold text-slate-200 text-sm truncate">{b.filename}</span>
                <div className="flex gap-3 text-xs text-slate-500">
                  <span>{b.size_mb} MB</span>
                  <span>{formatDate(b.created_at)}</span>
                  {stateLabel(b.filename) && (
                    <span className="text-indigo-400 font-medium">{stateLabel(b.filename)}</span>
                  )}
                </div>
              </div>
              <div className="flex gap-2 flex-shrink-0">
                <Button variant="ghost" size="sm" onClick={() => handleDownload(b.filename)}>
                  {t('admin.backups.download')}
                </Button>
                {!challengeId && b.type === 'manual' && (
                  <Button variant="danger" size="sm" onClick={() => handleDelete(b.filename)}>
                    ✕
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
