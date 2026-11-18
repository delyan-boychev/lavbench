import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '../context/NotificationsContext';
import { useApiError } from './useApiError';
import { useFieldErrors } from './useFieldErrors';
import { useUpdateUser } from './useUserMutations';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The form values of an account, with every text field a string. */
function formFor(user) {
  return {
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
  };
}

/**
 * State and save of the edit form for a competitor or an account, used by the
 * registrations tab and by user management.
 * @param {{ isLocked?: (challengeId: string) => boolean }} [options]
 */
export function useUserEditor({ isLocked = () => false } = {}) {
  const { t } = useTranslation();
  const { showToast } = useNotifications();
  const { showApiError } = useApiError();
  const { mutateAsync, isPending } = useUpdateUser();
  const fieldErrors = useFieldErrors();
  const { reset: resetErrors, clear: clearError } = fieldErrors;
  const [user, setUser] = useState(null);
  const [form, setForm] = useState(() => formFor({}));
  const [snapshot, setSnapshot] = useState('');

  const open = useCallback(
    (next) => {
      const values = formFor(next);
      setUser(next);
      setForm(values);
      setSnapshot(JSON.stringify(values));
      resetErrors();
    },
    [resetErrors],
  );

  const close = useCallback(() => setUser(null), []);

  const update = useCallback(
    (patch) => {
      setForm((prev) => ({ ...prev, ...patch }));
      Object.keys(patch).forEach(clearError);
    },
    [clearError],
  );

  const submit = async () => {
    if (form.email && !EMAIL_RE.test(form.email)) {
      fieldErrors.setErrors({ email: t('admin.notifications.invalid_email') });
      return;
    }
    try {
      const result = await mutateAsync({
        id: user.id,
        username: form.username,
        email: form.email || null,
        password: form.password || null,
        name: form.name,
        middle_name: form.middle_name || null,
        surname: form.surname,
        birth_date: form.birth_date || null,
        grade: form.grade || null,
        school: form.school || null,
        city: form.city || null,
        challenge_id: form.challenge_id,
        is_anonymous: form.is_anonymous,
        role: form.role,
        jury_challenges: form.jury_challenges,
      });
      if (result?.ok) {
        showToast(t('admin.notifications.competitor_updated'));
        setUser(null);
      } else if (!fieldErrors.capture(result?.data)) {
        showApiError(result?.data, 'admin.notifications.competitor_update_failed');
      }
    } catch (error) {
      if (!fieldErrors.capture(error)) {
        showToast(t('admin.notifications.network_error_update_competitor'), 'rose');
      }
    }
  };

  return {
    user,
    form,
    update,
    open,
    close,
    submit,
    dirty: Boolean(user) && JSON.stringify(form) !== snapshot,
    errors: fieldErrors.errors,
    isLocked: Boolean(user) && isLocked(form.challenge_id),
    isSaving: isPending,
  };
}
