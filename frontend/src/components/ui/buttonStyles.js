const BASE =
  'px-4 py-2.5 text-xs font-bold rounded-lg transition-all duration-200 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed border inline-flex items-center justify-center gap-2';
// Filled variants only: shadow-sm outranks shadow-none, so link buttons showed a box
const VARIANTS = {
  primary: 'shadow-sm bg-indigo-600 hover:bg-indigo-500 text-white border-indigo-500/30',
  secondary: 'shadow-sm bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700/50',
  accent: 'shadow-sm bg-teal-600 hover:bg-teal-500 text-white border-teal-500/30',
  danger: 'shadow-sm bg-rose-600 hover:bg-rose-500 text-white border-rose-500/30',
  link: 'bg-transparent hover:underline text-indigo-400 hover:text-indigo-300 border-transparent',
};

/** The classes of a Button variant, for controls that must look like one (a file picker). */
export function buttonClassName(variant = 'primary') {
  return `${BASE} ${VARIANTS[variant] || VARIANTS.primary}`;
}
