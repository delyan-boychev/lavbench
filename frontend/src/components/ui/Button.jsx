import React from 'react';

export default function Button({ 
  children, 
  onClick, 
  type = 'button', 
  variant = 'primary', 
  disabled = false, 
  className = '',
  title = ''
}) {
  const baseStyle = "px-4 py-2.5 text-xs font-bold rounded-lg transition-all duration-200 shadow-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed border inline-flex items-center justify-center gap-2";
  const variants = {
    primary: "bg-indigo-600 hover:bg-indigo-500 text-white border-indigo-500/30",
    secondary: "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700/50",
    accent: "bg-teal-600 hover:bg-teal-500 text-white border-teal-500/30",
    danger: "bg-rose-600 hover:bg-rose-500 text-white border-rose-500/30",
    link: "bg-transparent hover:underline text-indigo-400 hover:text-indigo-300 border-transparent shadow-none"
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${baseStyle} ${variants[variant] || variants.primary} ${className}`}
    >
      {children}
    </button>
  );
}
