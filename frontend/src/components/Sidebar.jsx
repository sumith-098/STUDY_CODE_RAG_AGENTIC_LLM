// Sidebar -- fixed rehta hai (chat scroll hone par ye nahi hilta). Upar brand + navigation,
// beech me scroll hone wali list (Recents + Knowledge), neeche pinned quota/status/theme.
// Props: open, onClose, onNewChat, files [{file_hash,name,chunks}], uploading, onUpload(fileList),
//        onDelete(hash), status (str), quota (obj|null),
//        chats [{session_id,title}], activeId, onOpenChat(id), onDeleteChat(id),
//        view ('study' | 'code'), onSwitchView(view), theme ('light'|'dark'), onToggleTheme()
import { useRef } from "react";
import { ArrowLeft, Code, FileText, MessageSquare, Moon, PanelLeftClose, Plus, Sun, Trash2, Upload } from "lucide-react";
import QuotaBadge from "./QuotaBadge.jsx";
import Mark from "./Mark.jsx";

export default function Sidebar({ open, onClose, onNewChat, files, uploading, onUpload, onDelete, status, quota,
                                  chats, activeId, onOpenChat, onDeleteChat, view, onSwitchView, theme, onToggleTheme }) {
  const inputRef = useRef(null);
  return (
    <aside className={`sidebar ${open ? "" : "sidebar-hidden"}`}>
      <div className="sb-head">
        <div className="brand"><Mark size={26} /><span>StudyPilot</span></div>
        <button className="icon-button" onClick={onClose} aria-label="Close sidebar"><PanelLeftClose size={18} /></button>
      </div>

      <nav className="sb-nav">
        <button className="nav-item" onClick={onNewChat}>
          <span className="nav-icon accent"><Plus size={14} /></span>New chat
        </button>
        {view === "code"
          ? <button className="nav-item" onClick={() => onSwitchView("study")}><span className="nav-icon"><ArrowLeft size={16} /></span>Back to Study</button>
          : <button className="nav-item" onClick={() => onSwitchView("code")}><span className="nav-icon"><Code size={16} /></span>Code with AI</button>}
      </nav>

      <div className="sb-scroll">
        <div className="sb-label">Recents</div>
        {chats.map(c => (
          <div key={c.session_id} className={`chat-row ${c.session_id === activeId && view === "study" ? "active" : ""}`}>
            <button className="chat-open" onClick={() => onOpenChat(c.session_id)} title={c.title}>
              <MessageSquare size={14} /><span>{c.title}</span>
            </button>
            <button className="icon-button row-del" onClick={() => onDeleteChat(c.session_id)} aria-label="Delete chat"><Trash2 size={13} /></button>
          </div>))}
        {chats.length === 0 && <p className="empty-files">Your past chats will appear here.</p>}

        <div className="sb-label sb-label-row"><span>Knowledge</span><span className="count-pill">{files.length}</span></div>
        <button className="nav-item" onClick={() => inputRef.current?.click()} disabled={uploading}>
          <span className="nav-icon"><Upload size={15} /></span>
          {uploading ? "Indexing… (large or scanned files can take 1-2 min)" : "Add study material"}
        </button>
        <input ref={inputRef} type="file" accept=".pdf,.docx,.txt" multiple hidden
               onChange={e => { onUpload(Array.from(e.target.files || [])); e.target.value = ""; }} />
        {files.map(f => (
          <div className="file-row" key={f.file_hash}>
            <FileText size={15} />
            <div className="file-info"><span title={f.name}>{f.name}</span><small>{f.chunks} chunks</small></div>
            <button className="icon-button row-del" onClick={() => onDelete(f.file_hash)} aria-label={`Delete ${f.name}`}><Trash2 size={13} /></button>
          </div>))}
        {files.length === 0 && <p className="empty-files">PDF, DOCX or TXT · max 15 MB.</p>}
      </div>

      <div className="sb-foot">
        <QuotaBadge quota={quota} />
        <div className="foot-row">
          <div className="status-line" title={status}>
            <span className={`status-light ${status.startsWith("Connected") ? "online" : ""}`} />
            <span>{status.startsWith("Connected") ? "Connected" : "Backend offline"}</span>
          </div>
          <button className="icon-button" onClick={onToggleTheme} aria-label="Toggle theme" title={theme === "dark" ? "Light theme" : "Dark theme"}>
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </div>
    </aside>
  );
}