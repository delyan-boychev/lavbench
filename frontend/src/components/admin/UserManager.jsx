import React from 'react';
import { useTranslation } from 'react-i18next';
import InputField from '../ui/InputField';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';
import ToggleField from '../ui/ToggleField';
import Pagination from '../ui/Pagination';

export default function UserManager({
  newUser,
  setNewUser,
  handleRegisterUser,
  generatedUserCredentials,
  allUsers,
  userSearch,
  setUserSearch,
  handleDeleteUser,
  usersPage,
  usersPages,
  usersTotal,
  setUsersPage,
  challenges,
  currentUser
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-8 animate-fadein">
      
      <div className="flex flex-col gap-8">
        
        {/* Form Register Admin/Jury */}
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl w-full">
          <h2 className="text-lg font-bold text-white mb-2">{t('admin.user_mgmt.register_user_account')}</h2>
          <p className="text-slate-400 text-xs mb-6">{t('admin.user_mgmt.register_user_account_desc')}</p>
          
          <form onSubmit={handleRegisterUser} className="flex flex-col gap-4">
            <InputField 
              label={t('admin.user_mgmt.username_label')} 
              value={newUser.username} 
              onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} 
              placeholder={t('admin.user_mgmt.username_placeholder_eg')}
              required 
            />
            <InputField 
              label={t('admin.competitor_reg.email_address')} 
              type="email"
              value={newUser.email} 
              onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} 
              placeholder={t('admin.user_mgmt.email_placeholder_eg')}
            />
            
            <div className="grid grid-cols-2 gap-4">
              <InputField 
                label={t('admin.competitor_reg.first_name')} 
                value={newUser.name} 
                onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} 
                required 
              />
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
                { value: "competitor", label: t('admin.user_mgmt.role_competitor') },
                { value: "jury", label: t('admin.user_mgmt.role_jury') }
              ]}
            />

            {newUser.role === 'competitor' && (
              <>
                <div className="grid grid-cols-3 gap-2">
                  <InputField label={t('admin.competitor_reg.grade')} value={newUser.grade} onChange={(e) => setNewUser({ ...newUser, grade: e.target.value })} />
                  <InputField label={t('admin.competitor_reg.school')} value={newUser.school} onChange={(e) => setNewUser({ ...newUser, school: e.target.value })} />
                  <InputField label={t('admin.competitor_reg.city')} value={newUser.city} onChange={(e) => setNewUser({ ...newUser, city: e.target.value })} />
                </div>
                <SelectField 
                  label={t('admin.competitor_reg.assign_competition')} 
                  value={newUser.challenge_id} 
                  onChange={(val) => setNewUser({ ...newUser, challenge_id: val })} 
                  required 
                  options={[
                    { value: "", label: t('admin.competitor_reg.assign_competition_choose') },
                    ...challenges.map(c => ({ value: c.id.toString(), label: c.title }))
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

            <Button type="submit" variant="primary" className="mt-2">{t('admin.user_mgmt.register_user_btn')}</Button>
          </form>

          {generatedUserCredentials && (
            <div className="mt-6 p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5">
              <h3 className="font-bold text-sm text-indigo-300">{t('admin.user_mgmt.account_created_title', { role: t(`admin.user_mgmt.role_${generatedUserCredentials.role}`).toUpperCase() })}</h3>
              <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
                <div><strong>{t('admin.user_mgmt.user_label')}</strong> {generatedUserCredentials.name} {generatedUserCredentials.surname}</div>
                <div className="pt-2"><strong>{t('admin.user_mgmt.username_label_colon')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedUserCredentials.username}</code></div>
                <div><strong>{t('admin.user_mgmt.password_label_colon')}</strong> <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">{generatedUserCredentials.password}</code></div>
              </div>
            </div>
          )}
        </div>

        {/* User accounts list */}
        <div className="bg-[#0d0e18] border border-white/5 p-8 rounded-2xl w-full">
          <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
            <div>
              <h2 className="text-lg font-bold text-white">{t('admin.user_mgmt.system_user_accounts')}</h2>
              <p className="text-slate-400 text-xs">{t('admin.user_mgmt.system_user_accounts_desc')}</p>
            </div>
            <InputField 
              placeholder={t('admin.user_mgmt.search_users_placeholder')} 
              value={userSearch} 
              onChange={(e) => setUserSearch(e.target.value)} 
              className="max-w-xs w-full"
            />
          </div>

          {allUsers.length === 0 ? (
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
                  {allUsers.map(user => (
                    <tr key={user.id}>
                      <td className="font-mono font-bold text-slate-200">{user.username}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <span>{user.name} {user.surname}</span>
                          {user.is_anonymous && (
                            <span className="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 uppercase tracking-wider" title={t('admin.competitor_reg.requested_anonymity_title')}>{t('admin.competitor_reg.anon_badge')}</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${user.role === 'admin' ? 'border-rose-500/30 bg-rose-500/10 text-rose-400' : user.role === 'jury' ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-blue-500/30 bg-blue-500/10 text-blue-400'}`}>
                          {user.role.toUpperCase()}
                        </span>
                      </td>
                      <td>{user.email || "—"}</td>
                      <td style={{ textAlign: 'right' }}>
                        {user.id !== currentUser.id ? (
                          <button
                            onClick={() => handleDeleteUser(user.id, user.username)}
                            className="text-[11px] font-bold text-rose-400 hover:underline bg-transparent border-0 cursor-pointer"
                          >
                            {t('admin.user_mgmt.delete_btn')}
                          </button>
                        ) : (
                          <span className="text-[10px] text-slate-500 font-semibold italic">{t('admin.user_mgmt.current_admin')}</span>
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
  );
}
