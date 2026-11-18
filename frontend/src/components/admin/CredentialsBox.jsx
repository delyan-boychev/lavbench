import React, { useEffect, useRef } from 'react';
import { revealElement } from '../../utils/reveal';

/**
 * Generated login details to hand over. Comes into view when it appears, since it can
 * appear away from the button that produced it.
 * @param {{
 *   title: string,
 *   personLabel?: string,
 *   person?: string,
 *   usernameLabel: string,
 *   username: string,
 *   passwordLabel: string,
 *   password: string,
 *   help?: string,
 *   onClear?: (() => void) | null,
 *   clearLabel?: string,
 *   className?: string,
 * }} props
 */
export default function CredentialsBox({
  title,
  personLabel = '',
  person = '',
  usernameLabel,
  username,
  passwordLabel,
  password,
  help = '',
  onClear = null,
  clearLabel = '',
  className = '',
}) {
  const ref = useRef(null);

  useEffect(() => {
    revealElement(ref.current);
  }, [username, password]);

  return (
    <div
      ref={ref}
      role="status"
      className={`p-5 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex flex-col gap-2.5 animate-fadein ${className}`}
    >
      <div className="flex justify-between items-center">
        <h3 className="font-bold text-sm text-indigo-300 font-sans">{title}</h3>
        {onClear && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs font-bold text-indigo-400 hover:underline bg-transparent border-0 cursor-pointer"
          >
            {clearLabel}
          </button>
        )}
      </div>
      <div className="text-xs flex flex-col gap-1 leading-relaxed text-slate-300">
        {personLabel && (
          <div>
            <strong>{personLabel}</strong> {person}
          </div>
        )}
        <div className={personLabel ? 'pt-2' : ''}>
          <strong>{usernameLabel}</strong>{' '}
          <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
            {username}
          </code>
        </div>
        <div>
          <strong>{passwordLabel}</strong>{' '}
          <code className="bg-slate-900 px-1 py-0.5 rounded text-indigo-400 font-bold">
            {password}
          </code>
        </div>
        {help && <p className="text-[10px] text-slate-500 mt-2 font-medium">{help}</p>}
      </div>
    </div>
  );
}
