import React, { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import SelectField from '../ui/SelectField';

/**
 * @param {{ image: { name: string, description: string, digest: string, packages: { name: string, version: string }[] } }} props
 */
function ImageInfo({ image }) {
  const { t } = useTranslation();
  const tooltipId = useId();
  const shortDigest = image.digest.split('@sha256:')[1]?.slice(0, 12);

  return (
    <div className="relative group pb-2.5">
      <button
        type="button"
        className="p-1 text-slate-400 hover:text-white focus:text-white focus:outline-none rounded"
        aria-label={t('admin.compute.image_info', { name: image.name })}
        aria-describedby={tooltipId}
        data-testid="workspace-image-info"
      >
        <Info className="w-4 h-4" aria-hidden="true" />
      </button>
      <div
        id={tooltipId}
        role="tooltip"
        className="invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 transition-opacity absolute right-0 bottom-full mb-2 z-50 w-72 p-3 rounded-lg bg-slate-950 border border-white/10 shadow-xl text-xs text-slate-300"
      >
        <p className="font-semibold text-white">{image.name}</p>
        {image.description && <p className="mt-1">{image.description}</p>}
        <p className="mt-2 font-semibold text-slate-200">{t('admin.compute.image_packages')}</p>
        {image.packages.length > 0 ? (
          <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono">
            {image.packages.map((pkg) => (
              <li key={pkg.name} className="truncate">
                {pkg.name} <span className="text-slate-500">{pkg.version}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-slate-500">{t('admin.compute.image_no_packages')}</p>
        )}
        {shortDigest && (
          <p className="mt-2 text-slate-500 font-mono">
            {t('admin.compute.image_pinned', { digest: shortDigest })}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * @param {{
 *   images: { image_id: string, name: string, description: string, digest: string, packages: { name: string, version: string }[], default: boolean }[] | undefined,
 *   loadFailed: boolean,
 *   value: string,
 *   onChange: (value: string) => void,
 *   disabled: boolean,
 * }} props
 */
export default function WorkspaceImagePicker({ images, loadFailed, value, onChange, disabled }) {
  const { t } = useTranslation();
  const catalogue = images || [];
  const options = catalogue.map((image) => ({ value: image.image_id, label: image.name }));
  if (value && !catalogue.some((image) => image.image_id === value)) {
    options.push({ value, label: t('admin.compute.image_retired', { id: value }) });
  }
  const selected = catalogue.find((image) => image.image_id === value);

  return (
    <div className="flex flex-col gap-1" data-testid="workspace-image-picker">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <SelectField
            label={t('admin.compute.image')}
            value={value}
            onChange={onChange}
            options={options}
            disabled={disabled || (loadFailed && !value)}
            placeholder={t('admin.compute.image_placeholder')}
          />
        </div>
        {selected && <ImageInfo image={selected} />}
      </div>
      {loadFailed && (
        <p className="text-xs text-rose-400">{t('admin.compute.images_unavailable')}</p>
      )}
    </div>
  );
}
