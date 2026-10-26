// App.jsx -- main screen. Yahan sirf STATE + EFFECTS + handlers hain; UI components/ folder me.
import { useCallback, useEffect, useRef, useState } from "react";
import { PanelLeftOpen } from "lucide-react";
import {
  ApiError, clearChat, deleteDocument, getDocuments, getHealth, getHistory,
  getChats, getQuota, makeId, sendChat, uploadFile,
} from "./api.js";
import Sidebar from "./components/Sidebar.jsx";
import Welcome from "./components/Welcome.jsx";
import MessageList from "./components/MessageList.jsx";
import Composer from "./components/Composer.jsx";
import CodeStudio from "./components/CodeStudio.jsx";
import { useTheme } from "./theme.js";

// Conversation ID localStorage me, taaki refresh ke baad wahi chat khule.
function loadSessionId() {
  try {
    return localStorage.getItem("studypilot_session") || makeId();
  } catch { return makeId(); }
}

export default function App() {
  const [sessionId, setSessionId] = useState(loadSessionId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [files, setFiles] = useState([]);
  const [quota, setQuota] = useState(null);
  const [chats, setChats] = useState([]);
  const [view, setView] = useState("study");            // "study" | "code" (Code with AI)
  const [codeVisited, setCodeVisited] = useState(false); // code screen pehli baar kholne par hi mount hogi
  const [uploading, setUploading] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 860); // chhoti screen par band shuru
  const [theme, toggleTheme] = useTheme();
  const [status, setStatus] = useState("Checking backend…");
  const [error, setError] = useState("");
  const bottomRef = useRef(null);
  const busyRef = useRef(false); // double-send rokne ke liye (state async hota hai, ref turant)

  // sessionId badle to save karo.
  useEffect(() => {
    try { localStorage.setItem("studypilot_session", sessionId); } catch { /* ignore */ }
  }, [sessionId]);

  // ---------- EFFECT 1: backend health -- har 15 sec. (FIX: cleanup + abort + retry)
  // Pehle ye sirf ek baar chalta tha: backend baad me start ho to "offline" hi dikhta rehta tha,
  // aur unmount par request cancel nahi hoti thi.
  useEffect(() => {
    const controller = new AbortController();
    async function check() {
      try {
        const d = await getHealth(controller.signal);
        setStatus(`Connected · ${d.indexed_chunks} chunks indexed`);
      } catch (e) {
        if (e.name !== "AbortError") setStatus("Backend offline · start FastAPI on port 8000");
      }
    }
    check();
    const timer = setInterval(check, 15000);
    return () => { controller.abort(); clearInterval(timer); }; // cleanup function
  }, []);

  // ---------- EFFECT 2: documents + quota + chat list, mount par ek baar.
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const [docs, q, list] = await Promise.all([
          getDocuments(controller.signal), getQuota(controller.signal), getChats(controller.signal),
        ]);
        setFiles(docs.documents); setQuota(q); setChats(list.chats);
      } catch (e) {
        if (e.name !== "AbortError" && e.code !== "offline") setError(e.message);
      }
    })();
    return () => controller.abort();
  }, []);

  // ---------- EFFECT 2b: jab bhi sessionId badle (chat kholo / new chat) us chat ki history load.
  // Cleanup me abort: tez-tez chat badalne par purana response naye chat par na chadh jaye.
  useEffect(() => {
    const controller = new AbortController();
    setMessages([]);
    (async () => {
      try {
        const hist = await getHistory(sessionId, controller.signal);
        setMessages(hist.messages.map(m => ({
          id: makeId(), role: m.role, content: m.content,
          route: m.meta?.route, quiz: m.meta?.quiz, sources: m.meta?.sources, verified: m.meta?.verified,
        })));
      } catch (e) {
        if (e.name !== "AbortError" && e.code !== "offline") setError(e.message);
      }
    })();
    return () => controller.abort();
  }, [sessionId]);

  // ---------- EFFECT 3: naya message aate hi neeche scroll.
  // FIX: pehle `() => ref.current?.scrollIntoView()` arrow ki wajah se effect ka return value
  // lag jaata tha. Effect ko cleanup function ya undefined hi return karna chahiye -> braces lagaye.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  const refreshChats = useCallback(async () => {
    try { setChats((await getChats()).chats); } catch { /* list optional hai */ }
  }, []);

  const refreshQuota = useCallback(async () => {
    try { setQuota(await getQuota()); } catch { /* quota badge optional hai */ }
  }, []);

  // Files upload (ek-ek karke; backend ek hi file par ruk kar quota sambhalta hai).
  async function uploadSelected(selected) {
    if (!selected.length) return;
    setUploading(true); setError("");
    const problems = [];
    for (const file of selected) {
      try { await uploadFile(file); }
      catch (e) { problems.push(`${file.name}: ${e.message}`); }
    }
    try { setFiles((await getDocuments()).documents); } catch { /* ignore */ }
    if (problems.length) setError(problems.join("\n"));
    setUploading(false); refreshQuota();
  }

  async function removeFile(hash) {
    try { await deleteDocument(hash); setFiles(prev => prev.filter(f => f.file_hash !== hash)); }
    catch (e) { setError(e.message); }
  }

  async function sendMessage(text = input) {
    const message = String(text).trim();
    if (!message || busyRef.current) return;
    busyRef.current = true;
    setInput(""); setError("");
    setMessages(prev => [...prev, { id: makeId(), role: "user", content: message }]);
    setThinking(true);
    try {
      const data = await sendChat(sessionId, message);
      setMessages(prev => [...prev, {
        id: makeId(), role: "assistant", content: data.answer, route: data.route,
        quiz: data.quiz, sources: data.sources, verified: data.verified, events: data.events,
      }]);
      setQuota(data.quota); refreshChats();
    } catch (e) {
      // Friendly message hi dikhao (quota/busy/offline sab ka alag text backend se aata hai)
      const msg = e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
      setError(msg);
      setInput(message); // user ka likha hua wapas, taaki dobara type na karna pade
      setMessages(prev => prev.slice(0, -1)); // failed message ko chat se hata do (backend me bhi save nahi hua)
      refreshQuota();
    } finally {
      setThinking(false); busyRef.current = false;
    }
  }

  // FIX: pehle "New conversation" purani chat DELETE kar deta tha. Ab purani chat list me bachi rehti hai.
  // Chhoti screen par sidebar overlay hota hai -- kuch chunne ke baad band kar do.
  const closeOnMobile = () => { if (window.innerWidth <= 860) setSidebarOpen(false); };

  function newChat() {
    setView("study"); closeOnMobile();
    if (busyRef.current) return;
    setSessionId(makeId()); setError("");
  }

  function openChat(id) {
    setView("study"); closeOnMobile();
    if (busyRef.current || id === sessionId) return;
    setSessionId(id); setError("");
  }

  // Study <-> Code with AI. Code screen mounted rehti hai (hidden), taaki beech me chalta build/chat na toote.
  function switchView(next) {
    setView(next); closeOnMobile();
    if (next === "code") setCodeVisited(true);
  }

  async function removeChat(id) {
    try { await clearChat(id); } catch (e) { setError(e.message); return; }
    if (id === sessionId) setSessionId(makeId());
    refreshChats();
  }

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} onNewChat={newChat}
               files={files} uploading={uploading} onUpload={uploadSelected} onDelete={removeFile}
               status={status} quota={quota}
               chats={chats} activeId={sessionId} onOpenChat={openChat} onDeleteChat={removeChat}
               view={view} onSwitchView={switchView} theme={theme} onToggleTheme={toggleTheme} />
      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            {!sidebarOpen && <button className="icon-button" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"><PanelLeftOpen size={19} /></button>}
            <strong className="page-title">{view === "code" ? "Code with AI" : "Study"}</strong>
          </div>
          <div className="topbar-right"><span className="model-dot" /> {view === "code" ? "Planner · Coder · Reviewer" : "Gemini · Multi-agent RAG"}</div>
        </header>
        <div className="study-wrap" hidden={view === "code"}>
          <section className="conversation">
            {messages.length === 0
              ? <Welcome onPick={sendMessage} />
              : <MessageList messages={messages} thinking={thinking} bottomRef={bottomRef} />}
          </section>
          <Composer value={input} onChange={setInput} onSend={() => sendMessage()}
                    onAttach={() => document.querySelector('input[type="file"]')?.click()}
                    disabled={thinking} error={error} docCount={files.length} />
        </div>
        {codeVisited && (
          <div className="code-wrap" hidden={view !== "code"}>
            <CodeStudio onQuota={setQuota} />
          </div>)}
      </main>
    </div>
  );
}