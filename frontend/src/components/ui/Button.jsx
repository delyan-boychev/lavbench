import React from 'react';

export default function Button({ 
  children, 
  onClick = () => {}, 
  type = 'button', 
  variant = 'primary', 
  disabled = false, 
  isLoading = false,
  className = '',
  title = '',
  // eslint-disable-next-line no-unused-vars
  size = 'md'
}) {
  const baseStyle = "px-4 py-2.5 text-xs font-bold rounded-lg transition-all duration-200 shadow-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed border inline-flex items-center justify-center gap-2";
  const variants = {
    primary: "bg-indigo-600 hover:bg-indigo-500 text-white border-indigo-500/30",
    secondary: "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700/50",
    accent: "bg-teal-600 hover:bg-teal-500 text-white border-teal-500/30",
    danger: "bg-rose-600 hover:bg-rose-500 text-white border-rose-500/30",
    link: "bg-transparent hover:underline text-indigo-400 hover:text-indigo-300 border-transparent shadow-none"
  };

  const buttonType = /** @type {'button' | 'submit' | 'reset'} */ (type);

  return (
    <button
      type={buttonType}
      onClick={onClick}
      disabled={disabled || isLoading}
      title={title}
      className={`${baseStyle} ${variants[variant] || variants.primary} ${className}`}
    >
      {isLoading && (
        <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      )}
      {children}
    </button>
  );
}
