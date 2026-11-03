"use client";

import { useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
}

/** Raw HTML in a message is shown as text, never rendered (same as before markdown). */
function htmlAsText() {
  const BLOCK = new Set(["root", "blockquote", "listItem"]);
  const walk = (node: MdNode) => {
    node.children = node.children?.map((child) => {
      if (child.type !== "html") {
        walk(child);
        return child;
      }
      const text: MdNode = { type: "text", value: child.value ?? "" };
      // An HTML block becomes a normal paragraph of text; inline HTML becomes inline text.
      return BLOCK.has(node.type) ? { type: "paragraph", children: [text] } : text;
    });
  };
  return (tree: MdNode) => walk(tree);
}

const SAFE_URL = /^(https?:|mailto:)/i;

const components: Components = {
  a: ({ href, children }) =>
    href ? (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  img: ({ alt }) => <span className="text-muted">[image{alt ? `: ${alt}` : ""}]</span>,
  table: ({ children }) => (
    <div className="my-1 max-w-full overflow-x-auto">
      <table className="border-collapse text-xs [&_td]:border [&_td]:border-line [&_td]:px-1.5 [&_td]:py-0.5 [&_th]:border [&_th]:border-line [&_th]:px-1.5 [&_th]:py-0.5 [&_th]:text-left">
        {children}
      </table>
    </div>
  ),
  pre: ({ children }) => <pre className="my-1 max-w-full overflow-x-auto rounded bg-bg p-2 text-xs">{children}</pre>,
  code: ({ children, className }) => (
    <code className={`${className ?? ""} rounded bg-panel-2 px-1 font-mono text-[0.9em]`}>{children}</code>
  ),
  ul: ({ children }) => <ul className="my-1 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1 list-decimal space-y-0.5 pl-5">{children}</ol>,
  h1: ({ children }) => <p className="mt-2 text-base font-semibold">{children}</p>,
  h2: ({ children }) => <p className="mt-2 font-semibold">{children}</p>,
  h3: ({ children }) => <p className="mt-1.5 font-semibold">{children}</p>,
  p: ({ children }) => <p className="my-1 whitespace-pre-line first:mt-0 last:mb-0">{children}</p>,
  blockquote: ({ children }) => (
    <blockquote className="my-1 border-l-2 border-line pl-2 text-muted">{children}</blockquote>
  ),
};

/** Markdown for chat messages: GFM tables and lists, no raw HTML, only http(s) and mailto links. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="break-words leading-relaxed" data-testid="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, htmlAsText]}
        urlTransform={(url) => (SAFE_URL.test(url) ? url : "")}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

/** Long answers start folded (about 12 lines); "Show more" opens them. */
export function isLong(text: string): boolean {
  return text.length > 1200 || text.split("\n").length > 14;
}

export function Folded({ text, children }: { text: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!isLong(text)) return <>{children}</>;
  return (
    <div>
      <div
        data-testid="folded"
        data-open={open}
        className={open ? "" : "relative max-h-[18em] overflow-hidden"}
        style={
          open
            ? undefined
            : {
                maskImage: "linear-gradient(to bottom, black 75%, transparent)",
                WebkitMaskImage: "linear-gradient(to bottom, black 75%, transparent)",
              }
        }
      >
        {children}
      </div>
      <button
        type="button"
        data-testid="fold-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="mt-1 text-xs font-medium text-accent underline"
      >
        {open ? "Show less" : "Show more"}
      </button>
    </div>
  );
}
