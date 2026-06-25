import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import Button from '../ui/Button';
import EmptyState from '../ui/EmptyState';
import api from '../../services/ApiService';
import { useApp } from '../../context/AppContext';
import { formatDateTime } from '../../utils/formatDate';

export default function BackupManager() {
  const { t } = useTranslation();
  const { selectedChallenge } = useApp();
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [forcing, setForcing] = useState(false);

  const listUrl = '/admin/backups';
  const downloadBase = '/api/admin/backups';

  const loadBackups = useCallback(async () => {
    try {
      const { ok, data } = await api.get(listUrl);
      if (ok) setBackups(data.backups || []);
    } catch {
      /* noop */
    }
    setLoading(false);
  }, [listUrl]);

  useEffect(() => {
    loadBackups();
    const eventSource = new EventSource('/api/admin/backups/live');
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.backups) {
          const filtered = data.backups.filter(
            (b) =>
              !b.filename.includes('submission_ended') &&
              !b.filename.includes('grace_ended') &&
              !b.filename.includes('finalized'),
          );
          setBackups(filtered);
          setLoading(false);
        }
        if (data.event?.status === 'completed') {
          setForcing(false);
          loadBackups();
        }
      } catch (e) {
        console.error('Backup SSE parse error:', e);
      }
    };
    return () => eventSource.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleForce = async () => {
    setForcing(true);
    try {
      await api.post('/admin/backups/force');
    } catch {
      setForcing(false);
    }
  };

  const handleDelete = async (filename) => {
    try {
      await api.delete(`/admin/backups/${filename}`);
      loadBackups();
    } catch {
      /* noop */
    }
  };

  const handleDownload = (filename) => {
    const url = `${downloadBase}/${filename}/download`;
    window.open(url, '_blank');
  };

  const formatDate = (iso) => formatDateTime(iso, selectedChallenge?.timezone || 'UTC');

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-bold text-white">
          {t('admin.backups.database_backups_security')}
        </h2>
        <Button variant="accent" onClick={handleForce} disabled={forcing}>
          {forcing ? t('admin.backups.forcing') : t('admin.backups.force_now')}
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-500 text-sm">{t('common.loading')}</div>
      ) : backups.length === 0 ? (
        <EmptyState message={t('admin.backups.no_backups')} />
      ) : (
        <div className="flex flex-col gap-3">
          {backups.map((b) => (
            <div
              key={b.filename}
              className="flex items-center justify-between gap-4 bg-slate-900/40 border border-white/5 p-4 rounded-xl flex-wrap"
            >
              <div className="flex flex-col gap-1 min-w-0">
                <span className="font-bold text-slate-200 text-sm truncate">{b.filename}</span>
                <div className="flex gap-3 text-xs text-slate-500">
                  <span>{b.size_mb} MB</span>
                  <span>{formatDate(b.created_at)}</span>
                </div>
              </div>
              <div className="flex gap-2 flex-shrink-0">
                <Button variant="ghost" size="sm" onClick={() => handleDownload(b.filename)}>
                  {t('admin.backups.download')}
                </Button>
                {b.type === 'manual' && (
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
