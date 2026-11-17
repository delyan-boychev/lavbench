import { toDateTimeLocal } from './formatDate';

/**
 * @typedef {{
 *   enabled: boolean,
 *   image_id: string,
 *   profile_id: string,
 *   workspace_gib: string | number,
 *   auto_publish: boolean,
 *   archive_until: string,
 * }} WorkspaceDraft
 */

/**
 * The form's copy of a competition's workspace setting; empty choices take the catalog defaults.
 * @param {any} [setting]
 * @returns {WorkspaceDraft}
 */
export function workspaceDraft(setting) {
  return {
    enabled: Boolean(setting?.enabled),
    image_id: setting?.image_id || '',
    profile_id: setting?.profile_id || '',
    workspace_gib: setting?.workspace_gib ?? '',
    auto_publish: Boolean(setting?.auto_publish),
    archive_until: toDateTimeLocal(setting?.archive_until),
  };
}

/**
 * The `workspace` object the competition create and update routes take.
 * @param {WorkspaceDraft} draft
 */
export function workspacePayload(draft) {
  return {
    enabled: draft.enabled,
    image_id: draft.image_id,
    profile_id: draft.profile_id,
    workspace_gib: Number(draft.workspace_gib),
    auto_publish: draft.auto_publish,
    archive_until: draft.archive_until || null,
  };
}

/**
 * Fill the choices still empty with the catalog's default image, first profile and size.
 * @param {WorkspaceDraft} draft
 * @param {any} catalog
 * @returns {WorkspaceDraft}
 */
export function withCatalogDefaults(draft, catalog) {
  const images = catalog?.images || [];
  const defaultImage = images.find((image) => image.default) || images[0];
  return {
    ...draft,
    image_id: draft.image_id || defaultImage?.image_id || '',
    profile_id: draft.profile_id || catalog?.profiles?.[0]?.id || '',
    workspace_gib:
      draft.workspace_gib === '' ? (catalog?.workspace_gib?.default ?? '') : draft.workspace_gib,
  };
}
