import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import Button from '../ui/Button';
import FormView from '../ui/FormView';
import SelectField from '../ui/SelectField';
import Pagination from '../ui/Pagination';
import FileUploader from '../ui/FileUploader';
import CompetitionStartedNotice from './CompetitionStartedNotice';
import CredentialsBox from './CredentialsBox';
import PersonFields from './PersonFields';
import { useUserEditor } from '../../hooks/useUserEditor';
import { downloadCredentialsCsv } from '../../utils/credentialsCsv';

export default function CompetitorManager({
  challenges,
  newCompetitor,
  setNewCompetitor,
  handleRegisterCompetitor,
  registerErrors = /** @type {Record<string, string>} */ ({}),
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
  csvErrors = /** @type {Record<string, string>} */ ({}),
  importedCompetitors,
  resetCredentials,
  setResetCredentials,
  bulkResetMessage,
  setBulkResetMessage,
  competitorsList,
  competitorSearch,
  setCompetitorSearch,
  handleBulkResetPasswords,
  isResettingBulkPasswords,
  currentUser,
  selectedChallenge,
  isChallengeStarted,
  handleResetUserPassword,
  isResettingPassword,
  competitorsPage,
  competitorsPages,
  competitorsTotal,
  setCompetitorsPage,
}) {
  const { t } = useTranslation();
  const editor = useUserEditor({
    isLocked: (challengeId) => currentUser.role === 'jury' && isChallengeStarted(challengeId),
  });

  const handleDownloadImportedCSV = () => {
    if (!importedCompetitors || importedCompetitors.length === 0) return;
    downloadCredentialsCsv(
      importedCompetitors.map((c) => ({
        id: c.id,
        name: c.name,
        middle_name: c.middle_name,
        surname: c.surname,
        birth_date: c.birth_date,
        username: c.generated_username,
        password: c.generated_password,
      })),
      selectedChallenge?.title,
    );
  };

  if (editor.user) {
    return (
      <FormView
        title={t('admin.competitor_reg.edit_competitor_details')}
        description={t('admin.competitor_reg.updating_account', {
          username: editor.user.username,
        })}
        onSubmit={editor.submit}
        onCancel={editor.close}
        dirty={editor.dirty}
        errors={editor.errors}
        submitLabel={t('admin.stages.save_changes_btn')}
        submitting={editor.isSaving}
        submitDisabled={editor.isLocked}
      >
        <InputField
          label={t('admin.competitor_reg.system_username')}
          value={editor.form.username}
          onChange={() => {}}
          disabled
        />
        <InputField
          label={t('admin.competitor_reg.email_address')}
          value={editor.form.email}
          onChange={(e) => editor.update({ email: e.target.value })}
          placeholder={t('admin.competitor_reg.email_placeholder')}
          error={editor.errors.email}
        />
        <PersonFields
          value={editor.form}
          onChange={editor.update}
          idPrefix="edit"
          challenges={challenges}
          errors={editor.errors}
        />
        {editor.isLocked && <CompetitionStartedNotice />}
      </FormView>
    );
  }

  return (
    <div className="flex flex-col gap-8 animate-fadein">
      {/* Registration Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        <div className="flex flex-col gap-6">
          <FormView
            title={t('admin.competitor_reg.manual_competitor_registration')}
            description={t('admin.competitor_reg.manual_registration_desc')}
            onSubmit={handleRegisterCompetitor}
            showBack={false}
            autoFocus={false}
            errors={registerErrors}
            submitLabel={t('admin.competitor_reg.generate_credentials')}
            submitting={isRegisteringCompetitor}
            submitDisabled={isManualRegisterDisabled}
          >
            <PersonFields
              value={newCompetitor}
              onChange={(patch) => setNewCompetitor({ ...newCompetitor, ...patch })}
              idPrefix="register"
              challenges={challenges}
              errors={registerErrors}
            />
            {isManualRegisterDisabled && <CompetitionStartedNotice />}
          </FormView>

          {generatedCredentials && (
            <CredentialsBox
              title={t('admin.competitor_reg.competitor_account_generated')}
              personLabel={t('admin.competitor_reg.competitor_label')}
              person={`${generatedCredentials.name} ${generatedCredentials.surname}`}
              usernameLabel={t('admin.competitor_reg.generated_username')}
              username={generatedCredentials.username}
              passwordLabel={t('admin.competitor_reg.generated_password')}
              password={generatedCredentials.password}
              help={t('admin.competitor_reg.share_credentials_help')}
            />
          )}
        </div>

        <div className="flex flex-col gap-6">
          <FormView
            title={t('admin.competitor_reg.import_competitors_csv')}
            description={t('admin.competitor_reg.csv_import_desc')}
            onSubmit={handleCSVImport}
            showBack={false}
            autoFocus={false}
            errors={csvErrors}
            submitLabel={
              csvImporting
                ? t('admin.competitor_reg.importing_bulk_data')
                : t('admin.competitor_reg.upload_parse_csv')
            }
            submitVariant="accent"
            submitDisabled={csvImporting || isCSVImportDisabled}
          >
            <SelectField
              label={t('admin.competitor_reg.target_competition_challenge')}
              value={csvChallengeId}
              onChange={(val) => setCsvChallengeId(val)}
              error={csvErrors.challenge_id || false}
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
              error={csvErrors.file}
              required
            />

            {isCSVImportDisabled && <CompetitionStartedNotice bulk />}
          </FormView>

          {importedCompetitors.length > 0 && (
            <div className="p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3">
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
      <div className="admin-card p-8">
        <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
          <div>
            <h2 className="text-lg font-bold text-white">
              {t('admin.competitor_reg.registered_competitors')}
            </h2>
            <p className="text-slate-400 text-xs">{t('admin.competitor_reg.unmasking_desc')}</p>
          </div>
          <div className="flex items-center gap-3.5 flex-wrap">
            {currentUser.role === 'admin' && (
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
          <CredentialsBox
            className="mb-6"
            title={t('admin.competitor_reg.password_reset_succeeded')}
            onClear={() => setResetCredentials(null)}
            clearLabel={t('admin.competitor_reg.clear')}
            usernameLabel={t('admin.competitor_reg.account_username')}
            username={resetCredentials.username}
            passwordLabel={t('admin.competitor_reg.new_generated_password')}
            password={resetCredentials.password}
            help={t('admin.competitor_reg.share_credentials_help')}
          />
        )}

        {bulkResetMessage && (
          <div className="mb-6 p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3 animate-fadein">
            <div className="flex justify-between items-center gap-2">
              <div>
                <h3 className="font-bold text-sm text-emerald-400 font-sans">
                  {t('admin.competitor_reg.bulk_reset_saved_title')}
                </h3>
                <p className="text-xs text-slate-300 mt-1 leading-relaxed">{bulkResetMessage}</p>
                <p className="text-[10px] text-slate-400 mt-1">
                  {t('admin.competitor_reg.bulk_reset_saved_help')}
                </p>
              </div>
              <button
                onClick={() => setBulkResetMessage('')}
                className="text-xs font-bold text-emerald-400 hover:underline bg-transparent border-0 cursor-pointer flex-shrink-0"
              >
                {t('admin.competitor_reg.clear_list')}
              </button>
            </div>
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
                          <button
                            data-return-id={`competitor-edit-${comp.id}`}
                            onClick={() => editor.open(comp)}
                            className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
                          >
                            {t('admin.competitor_reg.edit')}
                          </button>
                        )}
                        {/* The API decides who may reset whose password */}
                        {comp.can_reset_password && (
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
