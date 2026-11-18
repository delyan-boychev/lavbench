import React, { useId } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import Button from './Button';

/**
 * A button that shows or hides the content under it; the caller owns `open`.
 * @param {{
 *   label: React.ReactNode,
 *   open: boolean,
 *   onToggle: () => void,
 *   variant?: string,
 *   aside?: React.ReactNode,
 *   className?: string,
 *   children: React.ReactNode,
 * }} props
 */
export default function Disclosure({
  label,
  open,
  onToggle,
  variant = 'link',
  aside = null,
  className = 'flex flex-col gap-3',
  children,
}) {
  const panelId = useId();
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={variant}
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={panelId}
          className={variant === 'link' ? '!px-0 self-start' : ''}
        >
          <Chevron size={14} aria-hidden="true" />
          {label}
        </Button>
        {aside}
      </div>
      <div id={panelId} hidden={!open}>
        {open && children}
      </div>
    </div>
  );
}
