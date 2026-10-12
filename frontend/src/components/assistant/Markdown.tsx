import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface Props {
  text: string;
  onCite?: (index: number) => void;
  /**
   * Drop anything shaped like a source marker. Used while an answer is still
   * streaming: real markers are placed by the server from grounding metadata
   * only once the answer has passed its checks, so a bracketed number in the
   * raw stream is never a real citation.
   */
  stripCitations?: boolean;
}

const MARKER_LIKE = /[ \t]*\[(?:cite:[ \t]*)?\d{1,3}(?:[ \t]*,[ \t]*\d{1,3})*\]/gi;

interface MarkdownNode {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
}

function remarkCitations() {
  return (tree: MarkdownNode) => {
    const transform = (node: MarkdownNode) => {
      if (!node.children || ['link', 'code', 'inlineCode', 'html'].includes(node.type)) return;
      node.children = node.children.flatMap((child) => {
        if (child.type !== 'text' || !child.value) {
          transform(child);
          return [child];
        }
        return child.value.split(/(\[(?:\d{1,2}|\?)\])/g).filter(Boolean).map((part) => {
          if (part === '[?]') {
            return { type: 'link', url: '#unsourced', children: [{ type: 'text', value: '?' }] };
          }
          const match = /^\[(\d{1,2})\]$/.exec(part);
          return match
            ? { type: 'link', url: `#source-${match[1]}`, children: [{ type: 'text', value: match[1] }] }
            : { type: 'text', value: part };
        });
      });
    };
    transform(tree);
  };
}

export default function Markdown({ text, onCite, stripCitations = false }: Props) {
  if (stripCitations) text = text.replace(MARKER_LIKE, '');
  if (!text.trim()) return null;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkCitations]}
      skipHtml
      components={{
        a: ({ href, children }) => {
          if (href === '#unsourced') {
            // A figure the server could not match to any source passage.
            return (
              <span
                className="cite-chip unsourced"
                title="Not matched to a specific source passage - check it before relying on it"
                aria-label="Not matched to a source"
              >{children}</span>
            );
          }
          const citation = /^#source-(\d{1,2})$/.exec(href ?? '');
          if (citation) {
            return (
              <button
                type="button"
                className="cite-chip"
                onClick={() => onCite?.(Number(citation[1]))}
                title={`Source ${citation[1]}`}
                aria-label={`Source ${citation[1]}`}
              >{children}</button>
            );
          }
          return /^https?:\/\//.test(href ?? '')
            ? <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
            : <span>{children}</span>;
        },
        img: () => null,
        table: ({ children }) => <div className="answer-table-scroll"><table>{children}</table></div>,
        h1: ({ children }) => <h4 className="md-heading">{children}</h4>,
        h2: ({ children }) => <h4 className="md-heading">{children}</h4>,
        h3: ({ children }) => <h4 className="md-heading">{children}</h4>,
      }}
    >{text}</ReactMarkdown>
  );
}

