// CodeViewer -- ek file ka code, line numbers ke saath (syntax colors nahi -- extra library nahi chahiye).
// Props: path (str), content (str | undefined => loading), onCopy()
import { Copy } from "lucide-react";

export default function CodeViewer({ path, content, onCopy }) {
  if (!path) return <div className="code-viewer empty">Select a file, or start a build.</div>;
  const lines = (content ?? "").split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();   // aakhri khaali line hata do
  return (
    <div className="code-viewer">
      <div className="code-viewer-head">
        <span>{path}</span>
        <button className="icon-button" onClick={onCopy} aria-label="Copy code" title="Copy"><Copy size={14} /></button>
      </div>
      {content === undefined
        ? <p className="empty-files">Loading…</p>
        : <pre><code>{lines.map((line, i) => (
            <div className="code-line" key={i}><span className="ln">{i + 1}</span><span className="lc">{line || " "}</span></div>
          ))}</code></pre>}
    </div>
  );
}