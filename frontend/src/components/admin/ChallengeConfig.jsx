import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';

export default function ChallengeConfig({
  handleCreateChallenge,
  newChallenge,
  setNewChallenge,
  timezones,
}) {
  const { t } = useTranslation();

  return (
    <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl animate-fadein">
      <h2 className="text-xl font-bold text-white mb-6">{t('admin.create_new_challenge')}</h2>
      <form onSubmit={handleCreateChallenge} className="flex flex-col gap-4">
        <InputField
          label={t('admin.competition_title')}
          value={newChallenge.title}
          onChange={(e) => setNewChallenge({ ...newChallenge, title: e.target.value })}
          required
        />
        <InputField
          multiline
          label={t('admin.description')}
          value={newChallenge.description}
          onChange={(e) => setNewChallenge({ ...newChallenge, description: e.target.value })}
          rows={4}
        />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <InputField
            label={t('admin.daily_limits')}
            type="number"
            value={newChallenge.max_eval_requests}
            onChange={(e) =>
              setNewChallenge({ ...newChallenge, max_eval_requests: parseInt(e.target.value) || 0 })
            }
          />
          <InputField
            label={t('admin.ram_limit_override')}
            type="number"
            value={newChallenge.ram_limit_mb}
            onChange={(e) =>
              setNewChallenge({ ...newChallenge, ram_limit_mb: parseInt(e.target.value) || 0 })
            }
          />
          <InputField
            label={t('admin.time_limit_override')}
            type="number"
            value={newChallenge.time_limit_sec}
            onChange={(e) =>
              setNewChallenge({ ...newChallenge, time_limit_sec: parseInt(e.target.value) || 0 })
            }
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <InputField
            label={t('admin.stages.start_time_label')}
            type="datetime-local"
            value={newChallenge.start_time}
            onChange={(e) => setNewChallenge({ ...newChallenge, start_time: e.target.value })}
            required
          />
          <InputField
            label={t('admin.stages.end_time_label')}
            type="datetime-local"
            value={newChallenge.end_time}
            onChange={(e) => setNewChallenge({ ...newChallenge, end_time: e.target.value })}
            required
          />
          <SelectField
            label={t('admin.timezone_choose')}
            value={newChallenge.timezone}
            onChange={(val) => setNewChallenge({ ...newChallenge, timezone: val })}
            options={timezones}
            required
          />
        </div>
        <div className="flex flex-col gap-3 mt-2.5">
          <ToggleField
            label={t('admin.requires_gpu_workers')}
            id="create-gpu-req"
            checked={newChallenge.gpu_required}
            onChange={(e) => setNewChallenge({ ...newChallenge, gpu_required: e.target.checked })}
          />
          <ToggleField
            label={t('admin.double_blind_eval')}
            id="create-double-blind"
            checked={newChallenge.double_blind !== false}
            onChange={(e) => setNewChallenge({ ...newChallenge, double_blind: e.target.checked })}
          />
          <ToggleField
            label={t('admin.freeze_label')}
            id="create-is-frozen"
            checked={newChallenge.is_frozen || false}
            onChange={(e) => setNewChallenge({ ...newChallenge, is_frozen: e.target.checked })}
          />
        </div>
        <Button type="submit" variant="primary" className="w-fit mt-4">
          {t('admin.create_competition_btn')}
        </Button>
      </form>
    </div>
  );
}
