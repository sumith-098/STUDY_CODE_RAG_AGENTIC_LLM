// Composer -- neeche ka input box (attach + textarea jo text ke saath badhta hai + send).
// Props: value, onChange(text), onSend(), onAttach(), disabled (bool), error (str), docCount (int)
import { useEffect, useRef } from "react";
import { ArrowUp, FileText, Paperclip } from "lucide-react";

export default function Composer({ value, onChange, onSend, onAttach, disabled, error, docCount }) {
  const ref = useRef(null);

  // Textarea ki height text ke hisaab se (max 200px, uske baad andar scroll).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  return (
    <footer className="composer-wrap">
      <div className="composer-inner">
        {error && <div className="error-banner">{error}</div>}
        {docCount > 0 && <div className="context-chip"><FileText size={13} /> {docCount} document{docCount === 1 ? "" : "s"} ready</div>}
        <form className="composer" onSubmit={e => { e.preventDefault(); onSend(); }}>
          <button type="button" className="icon-button composer-attach" onClick={onAttach} aria-label="Attach a document"><Paperclip size={18} /></button>
          <textarea ref={ref} rows="1" placeholder="Ask a question, request a quiz or a summary…" value={value}
                    maxLength={4000} onChange={e => onChange(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }} />
          <button type="submit" className="send-button" disabled={!value.trim() || disabled} aria-label="Send message"><ArrowUp size={18} /></button>
        </form>
        <div className="composer-foot">AI can make mistakes. Please verify important information.</div>
      </div>
    </footer>
  );
}