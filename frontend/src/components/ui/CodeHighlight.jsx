import React, { useMemo } from 'react';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';
import 'prismjs/components/prism-python';

export default function CodeHighlight({ 
  code = '', 
  language = 'python', 
  maxHeight, 
  wrap = true,
  style = {}
}) {
  const highlighted = useMemo(() => {
    try {
      const lang = Prism.languages[language] || Prism.languages.python;
      return Prism.highlight(code, lang, language);
    } catch (e) {
      console.error('Prism highlighting error:', e);
      return null;
    }
  }, [code, language]);

  const preStyle = {
    padding: '10px 14px',
    fontSize: '0.72rem',
    borderRadius: 'var(--radius-sm)',
    background: '#050608',
    margin: 0,
    overflowX: 'auto',
    ...(maxHeight ? { maxHeight, overflowY: 'auto' } : {}),
    ...(wrap ? { whiteSpace: 'pre-wrap', wordBreak: 'break-all' } : {}),
    ...style
  };

  if (!highlighted) {
    return (
      <pre className="code-panel" style={preStyle}>
        {code}
      </pre>
    );
  }

  const codeStyle = wrap ? { whiteSpace: 'pre-wrap', wordBreak: 'break-all' } : {};

  return (
    <pre className="code-panel" style={preStyle}>
      <code 
        className={`language-${language}`} 
        style={codeStyle}
        dangerouslySetInnerHTML={{ __html: highlighted }} 
      />
    </pre>
  );
}
