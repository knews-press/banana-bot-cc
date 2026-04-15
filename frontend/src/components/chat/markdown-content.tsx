"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import rehypeHighlight from "rehype-highlight";
import type { Components } from "react-markdown";

interface MarkdownContentProps { content: string; }

export function MarkdownContent({ content }: MarkdownContentProps) {
  const components: Components = {
    img: ({ src, alt }) => {
      if (!src) return null;
      return (
        <span className="block my-3">
          <img
            src={src}
            alt={alt ?? "Generiertes Bild"}
            className="max-w-full rounded-md shadow-sm"
            style={{ maxHeight: "70vh", objectFit: "contain" }}
            loading="lazy"
          />
          {alt && alt !== "Generiertes Bild" && (
            <span
              className="block text-[11px] mt-1 italic"
              style={{ color: "var(--text-3)" }}
            >
              {alt}
            </span>
          )}
        </span>
      );
    },
    h1: ({ children }) => (
      <h1 className="text-[18px] font-semibold mt-5 mb-2 leading-snug" style={{ color: "var(--text)" }}>{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="text-[16px] font-semibold mt-4 mb-1.5 leading-snug" style={{ color: "var(--text)" }}>{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="text-[14px] font-semibold mt-3 mb-1 leading-snug" style={{ color: "var(--text)" }}>{children}</h3>
    ),
    p: ({ children }) => (
      <p className="text-[14px] leading-relaxed mb-3 last:mb-0" style={{ color: "var(--text)" }}>{children}</p>
    ),
    strong: ({ children }) => (
      <strong className="font-semibold" style={{ color: "var(--text)" }}>{children}</strong>
    ),
    em: ({ children }) => (
      <em className="italic" style={{ color: "var(--text-2)" }}>{children}</em>
    ),
    code: ({ children, className }) => {
      const isBlock = className?.includes("language-");
      if (isBlock) return <code className={className}>{children}</code>;
      return (
        <code
          className="px-1.5 py-0.5 rounded text-[12px] font-mono"
          style={{ backgroundColor: "var(--bg-subtle)", color: "var(--text)" }}
        >
          {children}
        </code>
      );
    },
    pre: ({ children }) => (
      <pre
        className="my-3 rounded-md text-[12px] font-mono overflow-x-auto p-3.5 leading-relaxed"
        style={{ backgroundColor: "var(--bg-subtle)" }}
      >
        {children}
      </pre>
    ),
    ul: ({ children }) => (
      <ul className="list-disc list-outside ml-4 mb-3 space-y-1 text-[14px]" style={{ color: "var(--text)" }}>{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal list-outside ml-4 mb-3 space-y-1 text-[14px]" style={{ color: "var(--text)" }}>{children}</ol>
    ),
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote
        className="border-l-2 pl-3.5 my-3 italic text-[14px]"
        style={{ borderColor: "var(--border-strong)", color: "var(--text-2)" }}
      >
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-4" style={{ borderColor: "var(--border)" }} />,
    table: ({ children }) => (
      <div className="overflow-x-auto my-3">
        <table className="w-full text-[13px] border-collapse">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th
        className="text-left px-3 py-1.5 font-semibold text-[12px] uppercase tracking-wide"
        style={{ borderBottom: "1px solid var(--border-strong)", color: "var(--text-2)" }}
      >
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="px-3 py-1.5" style={{ borderBottom: "1px solid var(--border)", color: "var(--text)" }}>
        {children}
      </td>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="underline underline-offset-2 transition-colors"
        style={{ color: "var(--text-2)" }}
        onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text)"}
        onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-2)"}
      >
        {children}
      </a>
    ),
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      rehypePlugins={[rehypeHighlight]}
      components={components}
    >
      {content}
    </ReactMarkdown>
  );
}
