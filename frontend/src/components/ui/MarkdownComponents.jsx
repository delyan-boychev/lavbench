import React from 'react';

const getRawText = (node) => {
  if (!node) return "";
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(getRawText).join("");
  if (node.props && node.props.children) return getRawText(node.props.children);
  return "";
};

const stringToSlug = (str) => {
  return str
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}\s-]/gu, '') // Keep letters, numbers, spaces, and hyphens (Unicode-aware)
    .replace(/\s+/g, '-')             // Replace spaces with hyphens
    .replace(/-+/g, '-')              // Collapse multiple hyphens
    .replace(/^-+|-+$/g, '');         // Remove leading/trailing hyphens
};

export const markdownComponents = {
  blockquote: ({ children }) => {
    const rawText = getRawText(children).trim();
    const alertMatch = rawText.match(/^\[!(NOTE|IMPORTANT|WARNING|TIP|CAUTION)\]/i);
    
    if (alertMatch) {
      const type = alertMatch[1].toUpperCase();
      
      const styles = {
        NOTE: {
          bg: 'rgba(99, 102, 241, 0.05)',
          border: 'border-l-4 border-l-indigo-500',
          text: 'text-indigo-400',
          title: 'Note',
          icon: (
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" />
              <path strokeLinecap="round" d="M12 16v-4m0-4h.01" />
            </svg>
          )
        },
        IMPORTANT: {
          bg: 'rgba(139, 92, 246, 0.05)',
          border: 'border-l-4 border-l-purple-500',
          text: 'text-purple-400',
          title: 'Important',
          icon: (
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499c.195-.39.6-.641 1.03-.641s.836.251 1.03.641l2.52 5.034 5.59.812c.433.063.793.38.93.805.138.427-.002.899-.346 1.206l-4.045 3.945 1.0 5.568c.078.435-.1.874-.46 1.137-.36.262-.84.288-1.228.067L12 18.73l-4.99 2.57c-.388.22-.868.195-1.228-.067-.36-.263-.538-.702-.46-1.137l1.0-5.568-4.045-3.945c-.344-.307-.484-.78-.346-1.206.137-.426.497-.743.93-.805l5.59-.812 2.52-5.034z" />
            </svg>
          )
        },
        WARNING: {
          bg: 'rgba(245, 158, 11, 0.05)',
          border: 'border-l-4 border-l-amber-500',
          text: 'text-amber-400',
          title: 'Warning',
          icon: (
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          )
        },
        TIP: {
          bg: 'rgba(16, 185, 129, 0.05)',
          border: 'border-l-4 border-l-emerald-500',
          text: 'text-emerald-400',
          title: 'Tip',
          icon: (
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          )
        },
        CAUTION: {
          bg: 'rgba(244, 63, 94, 0.05)',
          border: 'border-l-4 border-l-rose-500',
          text: 'text-rose-400',
          title: 'Caution',
          icon: (
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          )
        }
      };
      
      const config = styles[type] || styles.NOTE;
      
      const removeMarker = (node) => {
        let removed = false;
        
        const traverse = (n) => {
          if (!n) return n;
          
          if (typeof n === 'string') {
            if (!removed && /^\s*\[!(NOTE|IMPORTANT|WARNING|TIP|CAUTION)\]/i.test(n)) {
              removed = true;
              return n.replace(/^\s*\[!(NOTE|IMPORTANT|WARNING|TIP|CAUTION)\]\s*/i, "");
            }
            return n;
          }
          
          if (typeof n === 'number') {
            return String(n);
          }
          
          if (Array.isArray(n)) {
            return n.map(item => traverse(item));
          }
          
          if (React.isValidElement(n)) {
            if (n.props && n.props.children) {
              return React.cloneElement(n, {}, traverse(n.props.children));
            }
          }
          
          return n;
        };
        
        return traverse(node);
      };
      
      const cleanedChildren = removeMarker(children);
      
      return (
        <div className={`p-3.5 my-4 rounded-r-lg border-y border-r border-white/5 ${config.bg} ${config.border} flex flex-col gap-1`}>
          <div className={`flex items-center text-[10px] font-bold uppercase tracking-wider ${config.text}`}>
            {config.icon}
            {config.title}
          </div>
          <div className="text-[12.5px] leading-relaxed text-slate-300">
            {cleanedChildren}
          </div>
        </div>
      );
    }
    
    return <blockquote className="border-l-2 border-slate-700 pl-4 my-3 italic text-slate-400">{children}</blockquote>;
  },
  h1: ({ children }) => <h1 id={stringToSlug(getRawText(children))}>{children}</h1>,
  h2: ({ children }) => <h2 id={stringToSlug(getRawText(children))}>{children}</h2>,
  h3: ({ children }) => <h3 id={stringToSlug(getRawText(children))}>{children}</h3>,
  h4: ({ children }) => <h4 id={stringToSlug(getRawText(children))}>{children}</h4>,
  h5: ({ children }) => <h5 id={stringToSlug(getRawText(children))}>{children}</h5>,
  h6: ({ children }) => <h6 id={stringToSlug(getRawText(children))}>{children}</h6>,
  a: ({ href, children, ...props }) => {
    const isInternal = href && href.startsWith('#');
    const handleClick = (e) => {
      if (isInternal) {
        e.preventDefault();
        try {
          const targetId = decodeURIComponent(href.substring(1));
          const element = document.getElementById(targetId);
          if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        } catch (err) {
          console.warn("Failed to scroll to internal link:", err);
        }
      }
    };
    return (
      <a 
        href={href} 
        onClick={handleClick} 
        target={isInternal ? undefined : "_blank"} 
        rel={isInternal ? undefined : "noopener noreferrer"}
        {...props}
      >
        {children}
      </a>
    );
  }
};
