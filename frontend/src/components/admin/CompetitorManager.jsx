import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import Pagination from '../ui/Pagination';
import FileUploader from '../ui/FileUploader';

export default function CompetitorManager({
  challenges,
  newCompetitor,
  setNewCompetitor,
  handleRegisterCompetitor,
  isManualRegisterDisabled,
  isRegisteringCompetitor,
  generatedCredentials,
  csvChallengeId,
  setCsvChallengeId,
  csvFile = null,
  setCsvFile,
  csvImporting,
  isCSVImportDisabled,
  handleCSVImport,
  importedCompetitors,
  resetCredentials,
  setResetCredentials,
  bulkResetCredentials,
  setBulkResetCredentials,
  competitorsList,
  competitorSearch,
  setCompetitorSearch,
  handleBulkResetPasswords,
  isResettingBulkPasswords,
  currentUser,
  selectedChallenge,
  isChallengeStarted,
  initEditUser,
  handleResetUserPassword,
  isResettingPassword,
  competitorsPage,
  competitorsPages,
  competitorsTotal,
  setCompetitorsPage,
}) {
  const { t } = useTranslation();

  const handleDownloadImportedCSV = () => {
    if (!importedCompetitors || importedCompetitors.length === 0) return;

    const headers = ['ID', 'Name', 'Middle Name', 'Surname', 'Birth Date', 'Alias ID', 'Password'];
    const rows = importedCompetitors.map((c) => [
      c.id || '',
      c.name || '',
      c.middle_name || '',
      c.surname || '',
      c.birth_date || '',
      c.generated_username || '',
      c.generated_password || '',
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map((row) => row.map((val) => `"${val.replace(/"/g, '""')}"`).join(',')),
    ].join('\n');

    const blob = new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), csvContent], {
      type: 'text/csv;charset=utf-8;',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);

    const compName = selectedChallenge?.title
      ? selectedChallenge.title
          .toLowerCase()
          .replace(/[^a-z0-9а-яё\s-_]+/gi, '')
          .trim()
          .replace(/\s+/g, '_')
      : 'competition';
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const dateStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
    const fileName = `${compName}_competitors_credentials_${dateStr}.csv`;

    link.setAttribute('download', fileName);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleDownloadResetCSV = () => {
    if (!bulkResetCredentials || bulkResetCredentials.length === 0) return;

    const headers = ['ID', 'Name', 'Middle Name', 'Surname', 'Birth Date', 'Alias ID', 'Password'];
    const rows = bulkResetCredentials.map((c) => [
      c.id || '',
      c.name || '',
      c.middle_name || '',
      c.surname || '',
      c.birth_date || '',
      c.username || '',
      c.password || '',
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map((row) => row.map((val) => `"${val.replace(/"/g, '""')}"`).join(',')),
    ].join('\n');

    const blob = new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), csvContent], {
      type: 'text/csv;charset=utf-8;',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);

    const compName = selectedChallenge?.title
      ? selectedChallenge.title
          .toLowerCase()
          .replace(/[^a-z0-9а-яё\s-_]+/gi, '')
          .trim()
          .replace(/\s+/g, '_')
      : 'competition';
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const dateStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
    const fileName = `${compName}_competitors_credentials_${dateStr}.csv`;

    link.setAttribute('download', fileName);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex flex-col gap-8 animate-fadein">
      {/* Registration Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        {/* Form Manual */}
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
          <h2 className="text-lg font-bold text-white mb-2">
            {t('admin.competitor_reg.manual_competitor_registration')}
          </h2>
          <p className="text-slate-400 text-xs mb-6">
            {t('admin.competitor_reg.manual_registration_desc')}
          </p>

          <form onSubmit={handleRegisterCompetitor} className="flex flex-col gap-4">
            <div className="grid grid-cols-3 gap-4">
              <InputField
                label={t('admin.competitor_reg.first_name')}
                value={newCompetitor.name}
                onChange={(e) => setNewCompetitor({ ...newCompetitor, name: e.target.value })}
                required
              />
              <InputField
                label={t('admin.competitor_reg.middle_name')}
                value={newCompetitor.middle_name}
                onChange={(e) =>
                  setNewCompetitor({ ...newCompetitor, middle_name: e.target.value })
                }
                required
              />
              <InputField
                label={t('admin.competitor_reg.last_name')}
                value={newCompetitor.surname}
                onChange={(e) => setNewCompetitor({ ...newCompetitor, surname: e.target.value })}
                required
              />
            </div>
            <InputField
              label={t('admin.competitor_reg.birth_date')}
              type="date"
              value={newCompetitor.birth_date}
              onChange={(e) => setNewCompetitor({ ...newCompetitor, birth_date: e.target.value })}
              required
            />
            <div className="grid grid-cols-3 gap-4">
              <InputField
                label={t('admin.competitor_reg.grade')}
                value={newCompetitor.grade}
                onChange={(e) => setNewCompetitor({ ...newCompetitor, grade: e.target.value })}
                required
              />
              <InputField
                label={t('admin.competitor_reg.school')}
                value={newCompetitor.school}
                onChange={(e) => setNewCompetitor({ ...newCompetitor, school: e.target.value })}
                required
              />
              <InputField
                label={t('admin.competitor_reg.city')}
                value={newCompetitor.city}
                onChange={(e) => setNewCompetitor({ ...newCompetitor, city: e.target.value })}
                required
              />
            </div>

            <SelectField
              label={t('admin.competitor_reg.assign_competition')}
              value={newCompetitor.challenge_id}
              onChange={(val) => setNewCompetitor({ ...newCompetitor, challenge_id: val })}
              required
              options={[
                { value: '', label: t('admin.competitor_reg.assign_competition_choose') },
                ...challenges.map((c) => ({ value: c.id.toString(), label: c.title })),
              ]}
            />

            <div className="mt-2.5">
              <ToggleField
                label={t('admin.competitor_reg.anonymous_help')}
                id="register-is-anonymous"
                checked={newCompetitor.is_anonymous}
                onChange={(e) =>
                  setNewCompetitor({ ...newCompetitor, is_anonymous: e.target.checked })
                }
              />
            </div>

            {isManualRegisterDisabled && (
              <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                {t('admin.competitor_reg.competition_started_warning')}
              </div>
            )}
            <Button
              type="submit"
              variant="primary"
              className="mt-2"
              disabled={isManualRegisterDisabled || isRegisteringCompetitor}
              isLoading={isRegisteringCompetitor}
            >
              {t('admin.competitor_reg.generate_credentials')}
            </Button>
          </form>

          {generatedCredentials && (
            <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
              <h3 className="font-bold text-sm text-indigo-300">
                {t('admin.competitor_reg.competitor_account_generated')}
              </h3>
              <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                <div>
                  <strong>{t('admin.competitor_reg.competitor_label')}</strong>{' '}
                  {generatedCredentials.name} {generatedCredentials.surname}
                </div>
                <div className="pt-2">
                  <strong>{t('admin.competitor_reg.generated_username')}</strong>{' '}
                  <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
                    {generatedCredentials.username}
                  </code>
                </div>
                <div>
                  <strong>{t('admin.competitor_reg.generated_password')}</strong>{' '}
                  <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
                    {generatedCredentials.password}
                  </code>
                </div>
                <p className="text-[10px] text-slate-500 mt-2 font-medium">
                  {t('admin.competitor_reg.share_credentials_help')}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Form CSV upload */}
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
          <h2 className="text-lg font-bold text-white mb-2">
            {t('admin.competitor_reg.import_competitors_csv')}
          </h2>
          <p className="text-slate-400 text-xs mb-6">{t('admin.competitor_reg.csv_import_desc')}</p>

          <form onSubmit={handleCSVImport} className="flex flex-col gap-4">
            <SelectField
              label={t('admin.competitor_reg.target_competition_challenge')}
              value={csvChallengeId}
              onChange={(val) => setCsvChallengeId(val)}
              required
              options={[
                { value: '', label: t('admin.competitor_reg.assign_competition_choose') },
                ...challenges.map((c) => ({ value: c.id.toString(), label: c.title })),
              ]}
            />

            <FileUploader
              files={csvFile ? [csvFile] : []}
              onChange={(files) => setCsvFile(files[0] || null)}
              accept=".csv"
              label={t('admin.competitor_reg.choose_csv_file')}
              required
            />

            {isCSVImportDisabled && (
              <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                {t('admin.competitor_reg.bulk_import_started_warning')}
              </div>
            )}
            <Button type="submit" variant="accent" disabled={csvImporting || isCSVImportDisabled}>
              {csvImporting
                ? t('admin.competitor_reg.importing_bulk_data')
                : t('admin.competitor_reg.upload_parse_csv')}
            </Button>
          </form>

          {importedCompetitors.length > 0 && (
            <div className="mt-6 p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3">
              <div>
                <h3 className="font-bold text-sm text-emerald-400">
                  {t('admin.competitor_reg.successfully_imported_count', {
                    count: importedCompetitors.length,
                  })}
                </h3>
                <p className="text-[10px] text-slate-400 mt-1">
                  {t(
                    'admin.competitor_reg.download_credentials_help',
                    'Competitor accounts successfully created. Click below to download their login credentials securely.',
                  )}
                </p>
              </div>
              <Button
                variant="accent"
                className="w-full py-2 text-xs font-semibold"
                onClick={handleDownloadImportedCSV}
              >
                {t('admin.competitor_reg.download_credentials_csv', 'Download Credentials (CSV)')}
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* List Registered Competitors */}
      <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl">
        <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
          <div>
            <h2 className="text-lg font-bold text-white">
              {t('admin.competitor_reg.registered_competitors')}
            </h2>
            <p className="text-slate-400 text-xs">{t('admin.competitor_reg.unmasking_desc')}</p>
          </div>
          <div className="flex items-center gap-3.5 flex-wrap">
            {(currentUser.role === 'admin' ||
              challenges.some((c) => !isChallengeStarted(c.id))) && (
              <Button
                variant="secondary"
                size="sm"
                onClick={handleBulkResetPasswords}
                disabled={isResettingBulkPasswords}
                isLoading={isResettingBulkPasswords}
              >
                {t('admin.competitor_reg.reset_all_passwords')}
              </Button>
            )}
            <InputField
              label=""
              placeholder={
                currentUser.role === 'jury' &&
                selectedChallenge &&
                isChallengeStarted(selectedChallenge.id)
                  ? t('admin.competitor_reg.search_alias_only_placeholder')
                  : t('admin.competitor_reg.search_competitor_placeholder')
              }
              value={competitorSearch}
              onChange={(e) => setCompetitorSearch(e.target.value)}
              className="max-w-xs w-full"
            />
          </div>
        </div>

        {resetCredentials && (
          <div className="mb-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5 animate-fadein">
            <div className="flex justify-between items-center">
              <h3 className="font-bold text-sm text-indigo-300 font-sans">
                {t('admin.competitor_reg.password_reset_succeeded')}
              </h3>
              <button
                onClick={() => setResetCredentials(null)}
                className="text-xs font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
              >
                {t('admin.competitor_reg.clear')}
              </button>
            </div>
            <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
              <div>
                <strong>{t('admin.competitor_reg.account_username')}</strong>{' '}
                <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
                  {resetCredentials.username}
                </code>
              </div>
              <div>
                <strong>{t('admin.competitor_reg.new_generated_password')}</strong>{' '}
                <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
                  {resetCredentials.password}
                </code>
              </div>
              <p className="text-[10px] text-slate-500 mt-2 font-medium">
                {t('admin.competitor_reg.share_credentials_help')}
              </p>
            </div>
          </div>
        )}

        {bulkResetCredentials.length > 0 && (
          <div className="mb-6 p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3 animate-fadein">
            <div className="flex justify-between items-center gap-2">
              <div>
                <h3 className="font-bold text-sm text-emerald-400 font-sans">
                  {t('admin.competitor_reg.generated_passwords_bulk_title', {
                    count: bulkResetCredentials.length,
                  })}
                </h3>
                <p className="text-[10px] text-slate-400 mt-1">
                  {t(
                    'admin.competitor_reg.download_reset_credentials_help',
                    'Passwords reset successfully. Click below to download their updated credentials securely.',
                  )}
                </p>
              </div>
              <button
                onClick={() => setBulkResetCredentials([])}
                className="text-xs font-bold text-emerald-400 hover:underline bg-transparent border-0 cursor-pointer"
              >
                {t('admin.competitor_reg.clear_list')}
              </button>
            </div>
            <Button
              variant="accent"
              className="w-full py-2 text-xs font-semibold"
              onClick={handleDownloadResetCSV}
            >
              {t('admin.competitor_reg.download_credentials_csv', 'Download Credentials (CSV)')}
            </Button>
          </div>
        )}

        {competitorsList.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-xs italic">
            {t('admin.competitor_reg.no_competitors_found')}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('admin.competitor_reg.alias_id_header')}</th>
                  <th>{t('admin.competitor_reg.real_name_header')}</th>
                  <th>{t('admin.competitor_reg.school_grade_header')}</th>
                  <th>{t('admin.competitor_reg.city_header')}</th>
                  <th>{t('admin.competitor_reg.system_username')}</th>
                  <th className="text-right">{t('admin.competitor_reg.actions_header')}</th>
                </tr>
              </thead>
              <tbody>
                {competitorsList.map((comp) => (
                  <tr key={comp.id}>
                    <td className="font-mono font-semibold text-indigo-400">{comp.alias_id}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <span>
                          {comp.name ? (
                            `${comp.name} ${comp.surname || ''}`
                          ) : (
                            <span className="text-slate-500 italic">
                              {t('admin.competitor_reg.double_blind_badge')}
                            </span>
                          )}
                        </span>
                        {comp.is_anonymous && (
                          <span
                            className="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 uppercase tracking-wider"
                            title={t('admin.competitor_reg.requested_anonymity_title')}
                          >
                            {t('admin.competitor_reg.anon_badge')}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      {comp.school
                        ? `${comp.school}${comp.grade ? ` (${t('leaderboard.grade_value', { grade: comp.grade })})` : ''}`
                        : '—'}
                    </td>
                    <td>{comp.city || '—'}</td>
                    <td className="font-mono text-slate-400">
                      {comp.username || (
                        <span className="text-slate-500 italic">
                          {t('admin.competitor_reg.hidden_badge')}
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div className="flex justify-end gap-3.5">
                        {(currentUser.role === 'admin' ||
                          !isChallengeStarted(comp.challenge_id)) && (
                          <>
                            <button
                              onClick={() => initEditUser(comp)}
                              className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
                            >
                              {t('admin.competitor_reg.edit')}
                            </button>
                            <button
                              onClick={() =>
                                handleResetUserPassword(
                                  comp.id,
                                  comp.name ? `${comp.name} ${comp.surname}` : comp.alias_id,
                                )
                              }
                              disabled={isResettingPassword}
                              className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer disabled:opacity-50"
                            >
                              {t('admin.competitor_reg.reset_pw_btn')}
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={competitorsPage}
              pages={competitorsPages}
              total={competitorsTotal}
              perPage={10}
              onPageChange={setCompetitorsPage}
              itemName={t('admin.competitor_reg.competitors')}
            />
          </div>
        )}
      </div>
    </div>
  );
}
