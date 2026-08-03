import React, { useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useApp } from '../../context/AppContext';
import InputField from '../ui/InputField';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import Pagination from '../ui/Pagination';

export default function UserManager({
  newUser,
  setNewUser,
  handleRegisterUser,
  isRegisteringUser,
  generatedUserCredentials,
  allUsers,
  userSearch,
  setUserSearch,
  handleDeleteUser,
  isDeletingUser,
  handleUpdateUserSubmit: onUpdateUserSubmit,
  isUpdatingUser,
  usersPage,
  usersPages,
  usersTotal,
  setUsersPage,
  challenges,
  currentUser,
}) {
  const { t } = useTranslation();
  const { showToast } = useApp();

  const [editingUser, setEditingUser] = useState(null);
  const [editUserForm, setEditUserForm] = useState({
    username: '',
    email: '',
    password: '',
    name: '',
    middle_name: '',
    surname: '',
    birth_date: '',
    grade: '',
    school: '',
    city: '',
    challenge_id: '',
    is_anonymous: false,
    role: 'competitor',
    jury_challenges: [],
  });

  const isEditDisabled = (() => {
    if (currentUser?.role !== 'jury' || !editUserForm.challenge_id) return false;
    const challenge = challenges.find(
      (c) => c.id.toString() === editUserForm.challenge_id.toString(),
    );
    return challenge?.start_time ? new Date() >= new Date(challenge.start_time) : false;
  })();

  const initEditUser = useCallback((user) => {
    setEditingUser(user);
    setEditUserForm({
      username: user.username || '',
      email: user.email || '',
      password: '',
      name: user.name || '',
      middle_name: user.middle_name || '',
      surname: user.surname || '',
      birth_date: user.birth_date || '',
      grade: user.grade || '',
      school: user.school || '',
      city: user.city || '',
      challenge_id: user.challenge_id ? user.challenge_id.toString() : '',
      is_anonymous: user.is_anonymous || false,
      role: user.role || 'competitor',
      jury_challenges: user.jury_challenges || [],
    });
  }, []);

  const handleUpdateUserSubmit = async (e) => {
    e.preventDefault();
    if (editUserForm.email) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(editUserForm.email)) {
        showToast(
          t('admin.notifications.invalid_email', 'Please enter a valid email address'),
          'rose',
        );
        return;
      }
    }
    try {
      await onUpdateUserSubmit(editingUser.id, {
        username: editUserForm.username,
        email: editUserForm.email || null,
        password: editUserForm.password || null,
        name: editUserForm.name,
        middle_name: editUserForm.middle_name || null,
        surname: editUserForm.surname,
        birth_date: editUserForm.birth_date || null,
        grade: editUserForm.grade || null,
        school: editUserForm.school || null,
        city: editUserForm.city || null,
        challenge_id: editUserForm.challenge_id === '' ? '' : editUserForm.challenge_id,
        is_anonymous: editUserForm.is_anonymous,
        role: editUserForm.role,
        jury_challenges: editUserForm.jury_challenges,
      });
      showToast(t('admin.notifications.competitor_updated'));
      setEditingUser(null);
    } catch {
      showToast(t('admin.notifications.network_error_update_competitor'), 'rose');
    }
  };

  return (
    <>
      <div className="flex flex-col gap-8 animate-fadein">
        <div className="flex flex-col gap-8">
          {/* Form Register Admin/Jury */}
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl w-full">
            <h2 className="text-lg font-bold text-white mb-2">
              {t('admin.user_mgmt.register_user_account')}
            </h2>
            <p className="text-slate-400 text-xs mb-6">
              {t('admin.user_mgmt.register_user_account_desc')}
            </p>

            <form onSubmit={handleRegisterUser} noValidate className="flex flex-col gap-4">
              <InputField
                label={t('admin.competitor_reg.email_address')}
                type="text"
                value={newUser.email}
                onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                placeholder={t('admin.user_mgmt.email_placeholder_eg')}
              />

              <div
                className={`grid ${newUser.role === 'competitor' ? 'grid-cols-3' : 'grid-cols-2'} gap-4`}
              >
                <InputField
                  label={t('admin.competitor_reg.first_name')}
                  value={newUser.name}
                  onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
                  required
                />
                {newUser.role === 'competitor' && (
                  <InputField
                    label={t('admin.competitor_reg.middle_name')}
                    value={newUser.middle_name}
                    onChange={(e) => setNewUser({ ...newUser, middle_name: e.target.value })}
                    required
                  />
                )}
                <InputField
                  label={t('admin.competitor_reg.last_name')}
                  value={newUser.surname}
                  onChange={(e) => setNewUser({ ...newUser, surname: e.target.value })}
                  required
                />
              </div>

              <SelectField
                label={t('admin.user_mgmt.role_label')}
                value={newUser.role}
                onChange={(val) => setNewUser({ ...newUser, role: val })}
                required
                options={[
                  { value: 'competitor', label: t('admin.user_mgmt.role_competitor') },
                  { value: 'jury', label: t('admin.user_mgmt.role_jury') },
                ]}
              />

              {newUser.role === 'competitor' && (
                <>
                  <div className="grid grid-cols-1 gap-4 mb-2">
                    <InputField
                      label={t('admin.competitor_reg.birth_date')}
                      type="date"
                      value={newUser.birth_date}
                      onChange={(e) => setNewUser({ ...newUser, birth_date: e.target.value })}
                      required
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <InputField
                      label={t('admin.competitor_reg.grade')}
                      value={newUser.grade}
                      onChange={(e) => setNewUser({ ...newUser, grade: e.target.value })}
                      required
                    />
                    <InputField
                      label={t('admin.competitor_reg.school')}
                      value={newUser.school}
                      onChange={(e) => setNewUser({ ...newUser, school: e.target.value })}
                      required
                    />
                    <InputField
                      label={t('admin.competitor_reg.city')}
                      value={newUser.city}
                      onChange={(e) => setNewUser({ ...newUser, city: e.target.value })}
                      required
                    />
                  </div>
                  <SelectField
                    label={t('admin.competitor_reg.assign_competition')}
                    value={newUser.challenge_id}
                    onChange={(val) => setNewUser({ ...newUser, challenge_id: val })}
                    required
                    options={[
                      { value: '', label: t('admin.competitor_reg.assign_competition_choose') },
                      ...challenges.map((c) => ({ value: c.id.toString(), label: c.title })),
                    ]}
                  />

                  <div className="mt-2.5">
                    <ToggleField
                      label={t('admin.competitor_reg.anonymous_help')}
                      id="new-user-is-anonymous"
                      checked={newUser.is_anonymous}
                      onChange={(e) => setNewUser({ ...newUser, is_anonymous: e.target.checked })}
                    />
                  </div>
                </>
              )}

              {newUser.role === 'jury' && (
                <SelectField
                  label={t('admin.user_mgmt.assign_jury_competitions', 'Assign Competitions')}
                  multiple
                  searchable
                  value={newUser.jury_challenges || []}
                  onChange={(vals) => setNewUser({ ...newUser, jury_challenges: vals })}
                  options={challenges.map((c) => ({ value: c.id.toString(), label: c.title }))}
                  placeholder={t(
                    'admin.user_mgmt.no_competitions_assigned',
                    'No competitions assigned',
                  )}
                />
              )}

              <Button
                type="submit"
                variant="primary"
                className="mt-2"
                disabled={isRegisteringUser}
                isLoading={isRegisteringUser}
              >
                {t('admin.user_mgmt.register_user_btn')}
              </Button>
            </form>

            {generatedUserCredentials && (
              <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
                <h3 className="font-bold text-sm text-indigo-300">
                  {t('admin.user_mgmt.account_created_title', {
                    role: t(`admin.user_mgmt.role_${generatedUserCredentials.role}`).toUpperCase(),
                  })}
                </h3>
                <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                  <div>
                    <strong>{t('admin.user_mgmt.user_label')}</strong>{' '}
                    {generatedUserCredentials.name} {generatedUserCredentials.surname}
                  </div>
                  <div className="pt-2">
                    <strong>{t('admin.user_mgmt.username_label_colon')}</strong>{' '}
                    <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
                      {generatedUserCredentials.username}
                    </code>
                  </div>
                  <div>
                    <strong>{t('admin.user_mgmt.password_label_colon')}</strong>{' '}
                    <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
                      {generatedUserCredentials.password}
                    </code>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* User accounts list */}
          <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl w-full">
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
                              onClick={() => initEditUser(user)}
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
      </div>

      {/* Edit User Account Modal */}
      {editingUser &&
        createPortal(
          <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center z-[10000] p-4">
            <div className="bg-[#0b0c16] border border-white/10 rounded-2xl max-w-lg w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-fadein">
              <form
                onSubmit={handleUpdateUserSubmit}
                noValidate
                className="flex flex-col flex-1 min-h-0"
              >
                {/* Header */}
                <div className="p-6 border-b border-white/5 flex-shrink-0">
                  <h2 className="text-lg font-bold text-white mb-1">
                    {t('admin.user_mgmt.edit_user_account', 'Edit User Account')}
                  </h2>
                  <p className="text-slate-400 text-xs">
                    {t(
                      'admin.user_mgmt.edit_user_account_desc',
                      'Update user details, role, and assigned competitions.',
                    )}
                  </p>
                </div>

                {/* Form Body (Scrollable) */}
                <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
                  <InputField
                    label={t('admin.user_mgmt.username_label')}
                    value={editUserForm.username}
                    onChange={(e) => setEditUserForm({ ...editUserForm, username: e.target.value })}
                    required
                    disabled
                  />
                  <InputField
                    label={t('admin.competitor_reg.email_address')}
                    type="text"
                    value={editUserForm.email || ''}
                    onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })}
                  />
                  <InputField
                    label={t('admin.user_mgmt.password_optional_label', 'New Password (Optional)')}
                    type="password"
                    value={editUserForm.password || ''}
                    onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })}
                    placeholder={t(
                      'admin.user_mgmt.password_optional_placeholder',
                      'Leave blank to keep current',
                    )}
                  />
                  <div
                    className={`grid ${editUserForm.role === 'competitor' ? 'grid-cols-3' : 'grid-cols-2'} gap-4`}
                  >
                    <InputField
                      label={t('admin.competitor_reg.first_name')}
                      value={editUserForm.name}
                      onChange={(e) => setEditUserForm({ ...editUserForm, name: e.target.value })}
                      required
                    />
                    {editUserForm.role === 'competitor' && (
                      <InputField
                        label={t('admin.competitor_reg.middle_name')}
                        value={editUserForm.middle_name || ''}
                        onChange={(e) =>
                          setEditUserForm({ ...editUserForm, middle_name: e.target.value })
                        }
                        required
                      />
                    )}
                    <InputField
                      label={t('admin.competitor_reg.last_name')}
                      value={editUserForm.surname}
                      onChange={(e) =>
                        setEditUserForm({ ...editUserForm, surname: e.target.value })
                      }
                      required
                    />
                  </div>

                  <SelectField
                    label={t('admin.user_mgmt.role_label')}
                    value={editUserForm.role}
                    onChange={(val) => setEditUserForm({ ...editUserForm, role: val })}
                    required
                    options={[
                      { value: 'competitor', label: t('admin.user_mgmt.role_competitor') },
                      { value: 'jury', label: t('admin.user_mgmt.role_jury') },
                    ]}
                  />

                  {editUserForm.role === 'competitor' && (
                    <>
                      <div className="grid grid-cols-1 gap-4 mb-2">
                        <InputField
                          label={t('admin.competitor_reg.birth_date')}
                          type="date"
                          value={editUserForm.birth_date || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, birth_date: e.target.value })
                          }
                          required
                        />
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <InputField
                          label={t('admin.competitor_reg.grade')}
                          value={editUserForm.grade || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, grade: e.target.value })
                          }
                          required
                        />
                        <InputField
                          label={t('admin.competitor_reg.school')}
                          value={editUserForm.school || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, school: e.target.value })
                          }
                          required
                        />
                        <InputField
                          label={t('admin.competitor_reg.city')}
                          value={editUserForm.city || ''}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, city: e.target.value })
                          }
                          required
                        />
                      </div>
                      <SelectField
                        label={t('admin.competitor_reg.assign_competition')}
                        value={editUserForm.challenge_id}
                        onChange={(val) => setEditUserForm({ ...editUserForm, challenge_id: val })}
                        required
                        options={[
                          { value: '', label: t('admin.competitor_reg.assign_competition_choose') },
                          ...challenges.map((c) => ({ value: c.id.toString(), label: c.title })),
                        ]}
                      />
                      <div className="mt-2.5">
                        <ToggleField
                          label={t('admin.competitor_reg.anonymous_help')}
                          id="edit-user-is-anonymous"
                          checked={editUserForm.is_anonymous}
                          onChange={(e) =>
                            setEditUserForm({ ...editUserForm, is_anonymous: e.target.checked })
                          }
                        />
                      </div>
                    </>
                  )}

                  {editUserForm.role === 'jury' && (
                    <SelectField
                      label={t('admin.user_mgmt.assign_jury_competitions', 'Assign Competitions')}
                      multiple
                      searchable
                      value={editUserForm.jury_challenges || []}
                      onChange={(vals) =>
                        setEditUserForm({ ...editUserForm, jury_challenges: vals })
                      }
                      options={challenges.map((c) => ({ value: c.id.toString(), label: c.title }))}
                      placeholder={t(
                        'admin.user_mgmt.no_competitions_assigned',
                        'No competitions assigned',
                      )}
                    />
                  )}

                  {isEditDisabled && (
                    <div className="text-rose-400 text-xs font-semibold bg-rose-500/10 p-3 rounded-lg mt-2">
                      {t('admin.competitor_reg.competition_started_warning')}
                    </div>
                  )}
                </div>

                {/* Footer */}
                <div className="p-6 border-t border-white/5 flex justify-end gap-3 flex-shrink-0">
                  <Button type="button" variant="secondary" onClick={() => setEditingUser(null)}>
                    {t('common.cancel', 'Cancel')}
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={isUpdatingUser}
                    isLoading={isUpdatingUser}
                  >
                    {t('common.save', 'Save')}
                  </Button>
                </div>
              </form>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
