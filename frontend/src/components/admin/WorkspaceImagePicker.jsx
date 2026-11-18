import React, { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import Button from '../ui/Button';
import SelectField from '../ui/SelectField';

/**
 * @typedef {{ image_id: string, name: string, description?: string, packages?: { name: string, version: string }[], default?: boolean }} WorkspaceImage
 */

/** @param {{ image: WorkspaceImage }} props */
function ImageInfo({ image }) {
  const { t } = useTranslation();
  const tooltipId = useId();
  const packages = image.packages || [];

  return (
    <div className="relative group pb-2.5">
      <button
        type="button"
        className="p-1 text-slate-400 hover:text-white focus:text-white focus:outline-none rounded"
        aria-label={t('environment.image_info', { name: image.name })}
        aria-describedby={tooltipId}
      >
        <Info className="w-4 h-4" aria-hidden="true" />
      </button>
      <div
        id={tooltipId}
        role="tooltip"
        className="invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 transition-opacity absolute right-0 bottom-full mb-2 z-50 w-72 max-w-[80vw] p-3 rounded-lg bg-slate-950 border border-white/10 shadow-xl text-xs text-slate-300"
      >
        <p className="font-semibold text-white">{image.name}</p>
        {image.description && <p className="mt-1">{image.description}</p>}
        <p className="mt-2 font-semibold text-slate-200">{t('environment.image_packages')}</p>
        {packages.length > 0 ? (
          <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono">
            {packages.map((pkg) => (
              <li key={pkg.name} className="truncate">
                {pkg.name} <span className="text-slate-500">{pkg.version}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-slate-500">{t('environment.image_no_packages')}</p>
        )}
      </div>
    </div>
  );
}

/**
 * The workspace image select, from nanoColab's catalog, with the installed libraries on hover.
 * A failed catalog load keeps its error under the field and offers a retry.
 * @param {{
 *   images: WorkspaceImage[] | undefined,
 *   loadFailed: boolean,
 *   onRetry?: () => void,
 *   value: string,
 *   onChange: (value: string) => void,
 *   disabled?: boolean,
 *   error?: string,
 * }} props
 */
export default function WorkspaceImagePicker({
  images,
  loadFailed,
  onRetry = undefined,
  value,
  onChange,
  disabled = false,
  error = '',
}) {
  const { t } = useTranslation();
  const catalog = images || [];
  const options = catalog.map((image) => ({ value: image.image_id, label: image.name }));
  // A stored image nanoColab no longer lists stays selectable instead of silently changing
  if (value && !catalog.some((image) => image.image_id === value)) {
    options.push({ value, label: images ? t('environment.image_retired', { id: value }) : value });
  }
  const selected = catalog.find((image) => image.image_id === value);

  return (
    <div className="flex flex-col gap-1" data-testid="workspace-image-picker">
      <div className="flex items-end gap-2">
        <div className="flex-1 min-w-0">
          <SelectField
            label={t('environment.image')}
            value={value}
            onChange={onChange}
            options={options}
            disabled={disabled || (!images && !loadFailed) || (loadFailed && !value)}
            placeholder={
              images || loadFailed ? t('environment.image_placeholder') : t('common.loading')
            }
            error={error || (loadFailed ? t('environment.images_unavailable') : '')}
            required
          />
        </div>
        {selected && <ImageInfo image={selected} />}
      </div>
      {loadFailed && onRetry && (
        <Button variant="link" className="!px-0 !py-1 self-start" onClick={() => onRetry()}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}
