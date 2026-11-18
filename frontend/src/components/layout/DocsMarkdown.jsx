import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '../ui/MarkdownComponents';

/**
 * Split out so react-markdown only loads when the docs modal is opened.
 * @param {{ content: string, section?: string | null }} props
 */
export default function DocsMarkdown({ content, section = null }) {
  const rootRef = useRef(null);

  // Section headings are numbered in every language, so "10" finds "## 10. ..." in each
  useEffect(() => {
    if (!section || !content) return;
    const heading = rootRef.current?.querySelector(`h2[id^="${section}-"]`);
    heading?.scrollIntoView?.({ block: 'start' });
  }, [content, section]);

  return (
    <div ref={rootRef}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
