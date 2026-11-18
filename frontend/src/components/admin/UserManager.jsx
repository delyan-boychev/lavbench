import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import FormView from '../ui/FormView';
import SelectField from '../ui/SelectField';
import Pagination from '../ui/Pagination';
import CompetitionStartedNotice from './CompetitionStartedNotice';
import CredentialsBox from './CredentialsBox';
import PersonFields from './PersonFields';
import { useUserEditor } from '../../hooks/useUserEditor';

/** Role choice, competition fields for competitors and assigned competitions for the jury. */
function AccountFields({ value, onChange, idPrefix, challenges, errors }) {
  const { t } = useTranslation();
  return (
    <>
      <SelectField
        label={t('admin.user_mgmt.role_label')}
        value={value.role}
        onChange={(val) => onChange({ role: val })}
        required
        options={[
          { value: 'competitor', label: t('admin.user_mgmt.role_competitor') },
          { value: 'jury', label: t('admin.user_mgmt.role_jury') },
        ]}
      />
      <PersonFields
        value={value}
        onChange={onChange}
        idPrefix={idPrefix}
        competitor={value.role === 'competitor'}
        challenges={challenges}
        errors={errors}
      />
      {value.role === 'jury' && (
        <SelectField
          label={t('admin.user_mgmt.assign_jury_competitions', 'Assign Competitions')}
          multiple
          searchable
          value={value.jury_challenges || []}
          onChange={(vals) => onChange({ jury_challenges: vals })}
          options={challenges.map((c) => ({ value: c.id.toString(), label: c.title }))}
          placeholder={t('admin.user_mgmt.no_competitions_assigned', 'No competitions assigned')}
        />
      )}
    </>
  );
}

export default function UserManager({
  newUser,
  setNewUser,
  handleRegisterUser,
  registerErrors = /** @type {Record<string, string>} */ ({}),
  isRegisteringUser,
  generatedUserCredentials,
  allUsers,
  userSearch,
  setUserSearch,
  handleDeleteUser,
  isDeletingUser,
  usersPage,
  usersPages,
  usersTotal,
  setUsersPage,
  challenges,
  currentUser,
  isChallengeStarted = (/** @type {string} */ _challengeId) => false,
}) {
  const { t } = useTranslation();
  const editor = useUserEditor({
    isLocked: (challengeId) => currentUser?.role === 'jury' && isChallengeStarted(challengeId),
  });

  if (editor.user) {
    return (
      <FormView
        title={t('admin.user_mgmt.edit_user_account', 'Edit User Account')}
        description={t(
          'admin.user_mgmt.edit_user_account_desc',
          'Update user details, role, and assigned competitions.',
        )}
        onSubmit={editor.submit}
        onCancel={editor.close}
        dirty={editor.dirty}
        errors={editor.errors}
        submitLabel={t('common.save', 'Save')}
        submitting={editor.isSaving}
      >
        <InputField
          label={t('admin.user_mgmt.username_label')}
          value={editor.form.username}
          onChange={() => {}}
          disabled
        />
        <InputField
          label={t('admin.competitor_reg.email_address')}
          value={editor.form.email}
          onChange={(e) => editor.update({ email: e.target.value })}
          error={editor.errors.email}
        />
        <InputField
          label={t('admin.user_mgmt.password_optional_label', 'New Password (Optional)')}
          type="password"
          value={editor.form.password}
          onChange={(e) => editor.update({ password: e.target.value })}
          placeholder={t(
            'admin.user_mgmt.password_optional_placeholder',
            'Leave blank to keep current',
          )}
          error={editor.errors.password}
        />
        <AccountFields
          value={editor.form}
          onChange={editor.update}
          idPrefix="edit-user"
          challenges={challenges}
          errors={editor.errors}
        />
        {editor.isLocked && <CompetitionStartedNotice />}
      </FormView>
    );
  }

  return (
    <div className="flex flex-col gap-8 animate-fadein">
      <FormView
        title={t('admin.user_mgmt.register_user_account')}
        description={t('admin.user_mgmt.register_user_account_desc')}
        onSubmit={handleRegisterUser}
        showBack={false}
        autoFocus={false}
        errors={registerErrors}
        submitLabel={t('admin.user_mgmt.register_user_btn')}
        submitting={isRegisteringUser}
      >
        <InputField
          label={t('admin.competitor_reg.email_address')}
          value={newUser.email}
          onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
          placeholder={t('admin.user_mgmt.email_placeholder_eg')}
          error={registerErrors.email}
        />
        <AccountFields
          value={newUser}
          onChange={(patch) => setNewUser({ ...newUser, ...patch })}
          idPrefix="new-user"
          challenges={challenges}
          errors={registerErrors}
        />
      </FormView>

      {generatedUserCredentials && (
        <CredentialsBox
          title={t('admin.user_mgmt.account_created_title', {
            role: t(`admin.user_mgmt.role_${generatedUserCredentials.role}`).toUpperCase(),
          })}
          personLabel={t('admin.user_mgmt.user_label')}
          person={`${generatedUserCredentials.name} ${generatedUserCredentials.surname}`}
          usernameLabel={t('admin.user_mgmt.username_label_colon')}
          username={generatedUserCredentials.username}
          passwordLabel={t('admin.user_mgmt.password_label_colon')}
          password={generatedUserCredentials.password}
        />
      )}

      {/* User accounts list */}
      <div className="admin-card p-8 w-full">
        <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
          <div>
            <h2 className="text-lg font-bold text-white">
              {t('admin.user_mgmt.system_user_accounts')}
            </h2>
            <p className="text-slate-400 text-xs">
              {t('admin.user_mgmt.system_user_accounts_desc')}
            </p>
          </div>
          <InputField
            label=""
            placeholder={t('admin.user_mgmt.search_users_placeholder')}
            value={userSearch}
            onChange={(e) => setUserSearch(e.target.value)}
            className="max-w-xs w-full"
          />
        </div>

        {!allUsers || allUsers.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-xs italic">
            {t('admin.user_mgmt.no_users_found')}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('admin.user_mgmt.username_header')}</th>
                  <th>{t('admin.competitor_reg.real_name_header')}</th>
                  <th>{t('admin.user_mgmt.role_header')}</th>
                  <th>{t('admin.user_mgmt.email_address_header')}</th>
                  <th className="text-right">{t('admin.competitor_reg.actions_header')}</th>
                </tr>
              </thead>
              <tbody>
                {allUsers.map((user) => (
                  <tr key={user.id}>
                    <td className="font-mono font-bold text-slate-200">{user.username}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <span>
                          {user.name} {user.surname}
                        </span>
                        {user.is_anonymous && (
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
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${user.role === 'admin' ? 'border-rose-500/30 bg-rose-500/10 text-rose-400' : user.role === 'jury' ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-blue-500/30 bg-blue-500/10 text-blue-400'}`}
                      >
                        {t('badge.' + user.role)}
                      </span>
                    </td>
                    <td>{user.email || '—'}</td>
                    <td style={{ textAlign: 'right' }}>
                      {user.id !== currentUser.id && (
                        <button
                          data-return-id={`user-edit-${user.id}`}
                          onClick={() => editor.open(user)}
                          className="text-[11px] font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer mr-3"
                        >
                          {t('common.edit', 'Edit')}
                        </button>
                      )}
                      {user.id !== currentUser.id ? (
                        <button
                          onClick={() => handleDeleteUser(user.id, user.username)}
                          disabled={isDeletingUser}
                          className="text-[11px] font-bold text-rose-400 hover:underline bg-transparent border-0 cursor-pointer disabled:opacity-50"
                        >
                          {t('admin.user_mgmt.delete_btn')}
                        </button>
                      ) : (
                        <span className="text-[10px] text-slate-500 font-semibold italic">
                          {t('admin.user_mgmt.current_admin')}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={usersPage}
              pages={usersPages}
              total={usersTotal}
              perPage={10}
              onPageChange={setUsersPage}
              itemName={t('admin.user_mgmt.users')}
            />
          </div>
        )}
      </div>
    </div>
  );
}
