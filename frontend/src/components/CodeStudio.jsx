// CodeStudio -- "Code with AI" screen. Left: agentic chat. Right: file tree + code viewer (live).
//
// Flow:  tu kaam bolta hai -> Planner plan banata hai -> tu Approve karta hai ->
//        Coder files banata hai (live dikhti hain) -> Reviewer bugs dhundh kar fix karta hai.
// Props: onQuota(quota) -- build ke baad sidebar ka quota badge update karne ke liye
import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FolderPlus, Loader2, Send, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ApiError, codeBuild, codePlan, deleteProject, downloadProjectZip, getProjectFile,
  getProjectFiles, getProjects, makeId,
} from "../api.js";
import FileTree from "./FileTree.jsx";
import CodeViewer from "./CodeViewer.jsx";
import PlanCard from "./PlanCard.jsx";

const EXAMPLES = [
  "Build a todo list web app (HTML, CSS, JS) where I can add, delete and mark tasks as done",
  "Create a number guessing game in Python that runs in the terminal",
  "Make a simple dark-themed portfolio landing page",
];

// Files ki do lists ko path ke hisaab se milata hai (naya size jeetta hai).
const mergeFiles = (prev, loaded) => {
  const map = new Map(prev.map(f => [f.path, f]));
  loaded.forEach(f => map.set(f.path, f));
  return [...map.values()];
};

// Live progress ki ek line (event -> readable text).
function progressLine(e) {
  if (e.type === "file") return `📄 ${e.message}`;
  if (e.type === "tool") return `🛠 ${e.agent}: ${e.tool}`;
  if (e.type === "result" && e.tool) return null;            // tool results bahut shor karte hain
  return `• ${e.agent}: ${e.message}`;
}

export default function CodeStudio({ onQuota }) {
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(null);       // {id, name} ya null
  const [files, setFiles] = useState([]);             // [{path, size}]
  const [contents, setContents] = useState({});       // {path: text}
  const [selected, setSelected] = useState("");
  const [messages, setMessages] = useState([]);       // {id, role, text | plan}
  const [pending, setPending] = useState(null);       // approve hone ka intezar karta plan
  const [progress, setProgress] = useState([]);       // build ke live events
  const [busy, setBusy] = useState("");               // "" | "planning" | "building"
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const endRef = useRef(null);
  const buildAbort = useRef(null);

  const refreshProjects = useCallback(async () => {
    try { setProjects((await getProjects()).projects); } catch { /* list optional hai */ }
  }, []);

  // EFFECT 1: mount par projects ki list; unmount par chalta build stream band.
  useEffect(() => {
    const controller = new AbortController();
    getProjects(controller.signal).then(d => setProjects(d.projects)).catch(() => {});
    return () => { controller.abort(); buildAbort.current?.abort(); };
  }, []);

  // EFFECT 2: project badle to uski files ki list load (merge: live aayi files na mitein).
  useEffect(() => {
    if (!project) return undefined;
    const controller = new AbortController();
    getProjectFiles(project.id, controller.signal).then(d => {
      setFiles(prev => mergeFiles(prev, d.files));
      setSelected(cur => cur || (d.files.find(f => f.path === "index.html") || d.files[0])?.path || "");
    }).catch(() => {});
    return () => controller.abort();
  }, [project?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // EFFECT 3: chuni hui file ka content (agar abhi tak load nahi hua).
  useEffect(() => {
    if (!project || !selected || contents[selected] !== undefined) return undefined;
    const controller = new AbortController();
    getProjectFile(project.id, selected, controller.signal)
      .then(d => setContents(c => ({ ...c, [selected]: d.content }))).catch(() => {});
    return () => controller.abort();
  }, [project?.id, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  // EFFECT 4: naya message / progress aate hi neeche scroll.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progress, busy]);

  const pushMessage = (m) => setMessages(prev => [...prev, { id: makeId(), ...m }]);
  const resetView = () => { setFiles([]); setContents({}); setSelected(""); setPending(null); setProgress([]); setError(""); };

  function newProject() {
    if (busy) return;
    resetView(); setProject(null); setMessages([]);
  }

  function openProject(id) {
    if (busy || !id) return;
    const p = projects.find(x => x.id === id);
    if (!p) return;
    resetView(); setProject({ id: p.id, name: p.name });
    setMessages([{ id: makeId(), role: "assistant", text: `Opened **${p.name}**. Tell me what to change (for example "add a dark mode").` }]);
  }

  // Step 1: kaam bhejo -> plan.
  async function send(text = input) {
    const request = String(text).trim();
    if (!request || busy) return;
    setInput(""); setError("");
    pushMessage({ role: "user", text: request });
    setBusy("planning");
    try {
      const data = await codePlan(request, project?.id);
      const id = makeId();
      setPending({ id, project_id: data.project_id, plan: data.plan, request, isNew: data.is_new });
      setMessages(prev => [...prev, { id, role: "assistant", plan: data.plan, isNew: data.is_new }]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create a plan. Please try again.");
      setInput(request);
      setMessages(prev => prev.slice(0, -1));      // fail hua sawaal chat se hata do
    } finally {
      setBusy("");
    }
  }

  // Build ke dauran aane wale har live event ko handle karta hai.
  function onBuildEvent(ev) {
    if (ev.type === "event") {
      setProgress(prev => [...prev, ev.event]);
    } else if (ev.type === "file") {
      setProgress(prev => [...prev, { type: "file", message: `${ev.action}: ${ev.path}` }]);
      setContents(c => ({ ...c, [ev.path]: ev.content }));
      setFiles(prev => mergeFiles(prev, [{ path: ev.path, size: ev.size }]));
      setSelected(ev.path);                        // jo file abhi bani wahi dikhao (live feel)
    } else if (ev.type === "done") {
      setFiles(ev.files);
      const review = ev.review ? `\n\n**Review:** ${ev.review}` : "";
      pushMessage({ role: "assistant", text: `${ev.summary || "Build complete."}${review}` });
      if (ev.quota) onQuota?.(ev.quota);
    } else if (ev.type === "error") {
      setError(ev.message);
    }
  }

  // Step 2: Approve -> build stream.
  async function approve() {
    if (!pending || busy) return;
    const p = pending;
    setMessages(prev => prev.map(x => (x.id === p.id ? { ...x, plan: p.plan } : x)));   // edit kiya hua brief card me bacha rahe
    setPending(null); setBusy("building"); setProgress([]); setError("");
    if (!project || project.id !== p.project_id) {
      setFiles([]); setContents({}); setSelected("");
      setProject({ id: p.project_id, name: p.plan.project_name });
    }
    const controller = new AbortController();
    buildAbort.current = controller;
    try {
      await codeBuild({ project_id: p.project_id, request: p.request, plan: p.plan }, onBuildEvent, controller.signal);
    } catch (e) {
      if (e.name !== "AbortError") setError(e instanceof ApiError ? e.message : "The build stopped unexpectedly.");
    } finally {
      buildAbort.current = null; setBusy(""); refreshProjects();
    }
  }

  function cancelPlan() {
    setPending(null);
    pushMessage({ role: "assistant", text: "Plan cancelled. Tell me if you want something different." });
  }

  async function download() {
    try { await downloadProjectZip(project.id); } catch (e) { setError(e.message); }
  }

  async function removeProject() {
    if (!project || busy || !window.confirm(`Delete the project "${project.name}"?`)) return;
    try { await deleteProject(project.id); } catch (e) { setError(e.message); return; }
    resetView(); setProject(null); setMessages([]); refreshProjects();
  }

  const copy = () => { if (contents[selected] !== undefined) navigator.clipboard?.writeText(contents[selected]); };

  return (
    <div className="code-studio">
      {/* ---------------- LEFT: agentic chat ---------------- */}
      <section className="code-chat">
        <div className="code-chat-head">
          <select value={project?.id || ""} onChange={e => openProject(e.target.value)} disabled={!!busy} aria-label="Choose a project">
            <option value="">{project ? `● ${project.name}` : "New project"}</option>
            {projects.filter(p => p.id !== project?.id).map(p => <option key={p.id} value={p.id}>{p.name} ({p.files} files)</option>)}
          </select>
          <button className="icon-button" onClick={newProject} disabled={!!busy} title="New project" aria-label="New project"><FolderPlus size={16} /></button>
        </div>

        <div className="code-feed">
          {messages.length === 0 && (
            <div className="code-empty">
              <h3>Tell me what to build.</h3>
              <p>The Planner writes a detailed brief and file plan. You approve it, then the Coder writes the files and the Reviewer checks them.</p>
              {EXAMPLES.map(t => <button key={t} className="code-example" onClick={() => send(t)} disabled={!!busy}>{t}</button>)}
            </div>)}
          {messages.map(m => m.plan
            ? <PlanCard key={m.id} plan={pending?.id === m.id ? pending.plan : m.plan} isNew={m.isNew}
                        active={pending?.id === m.id} busy={!!busy} onApprove={approve} onCancel={cancelPlan}
                        onBriefChange={brief => setPending(p => (p && p.id === m.id ? { ...p, plan: { ...p.plan, brief } } : p))} />
            : <div key={m.id} className={`code-msg ${m.role}`}>
                {m.role === "assistant" ? <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown></div> : m.text}
              </div>)}
          {busy === "planning" && <div className="code-status"><Loader2 size={15} className="spin" /> Planner is writing the brief and plan…</div>}
          {busy === "building" && (
            <div className="code-progress">
              <div className="code-status"><Loader2 size={15} className="spin" /> Agents are working…</div>
              {progress.map(progressLine).filter(Boolean).slice(-14).map((line, i) => <div key={i} className="progress-line">{line}</div>)}
            </div>)}
          <div ref={endRef} />
        </div>

        {error && <div className="error-banner">{error}</div>}
        <form className="code-input" onSubmit={e => { e.preventDefault(); send(); }}>
          <textarea rows="2" value={input} maxLength={4000} disabled={!!busy}
                    placeholder={project ? "What should change in this project?" : "What do you want to build? Add as much detail as you like…"}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <button type="submit" className="send-button" disabled={!input.trim() || !!busy} aria-label="Send"><Send size={17} /></button>
        </form>
      </section>

      {/* ---------------- RIGHT: files + code ---------------- */}
      <section className="code-right">
        <div className="code-toolbar">
          <div><strong>{project?.name || "No project yet"}</strong><span>{files.length} files</span></div>
          <div className="code-toolbar-actions">
            <button className="icon-button" onClick={download} disabled={!project || files.length === 0 || !!busy} title="Download ZIP" aria-label="Download ZIP"><Download size={16} /></button>
            <button className="icon-button" onClick={removeProject} disabled={!project || !!busy} title="Delete project" aria-label="Delete project"><Trash2 size={16} /></button>
          </div>
        </div>
        <div className="code-body">
          <FileTree files={files} selected={selected} onSelect={setSelected} />
          <CodeViewer path={selected} content={contents[selected]} onCopy={copy} />
        </div>
      </section>
    </div>
  );
}