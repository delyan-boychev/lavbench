import React from 'react';
import { buttonClassName } from './buttonStyles';

export default function Button({
  children,
  onClick = () => {},
  type = 'button',
  variant = 'primary',
  disabled = false,
  isLoading = false,
  className = '',
  title = '',
  'aria-label': ariaLabel = undefined,
  // eslint-disable-next-line no-unused-vars
  size = 'md',
  // data-* attributes (such as data-return-id) and form pass through to the button
  ...rest
}) {
  const buttonType = /** @type {'button' | 'submit' | 'reset'} */ (type);

  return (
    <button
      {...rest}
      type={buttonType}
      onClick={onClick}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      title={title}
      aria-label={ariaLabel}
      className={`${buttonClassName(variant)} ${className}`}
    >
      {isLoading && (
        <svg
          aria-hidden="true"
          className="animate-spin -ml-1 mr-2 h-4 w-4 text-current"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          ></circle>
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
      )}
      {children}
    </button>
  );
}
