// api.js -- Backend se baat karne ke saare functions EK jagah.
// Har function error par ApiError throw karta hai jisme user-friendly message hota hai.

export const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

// crypto.randomUUID() -> naya random ID string (jaise "3b241101-e2bb-...")
export const makeId = () => crypto.randomUUID();

// Workspace ID = is browser/user ki pehchaan. localStorage me save, taaki documents/chat/projects
// refresh ke baad bhi mile aur dusre users ka data na dikhe.
export function getWorkspaceId() {
  try {
    let id = localStorage.getItem("studypilot_workspace");
    if (!id) { id = makeId(); localStorage.setItem("studypilot_workspace", id); }
    return id;
  } catch { return makeId(); } // private mode me localStorage fail ho sakta hai
}
const WORKSPACE = getWorkspaceId();

export class ApiError extends Error {
  // message: user ko dikhane layak text, code: 'quota'/'bad_input'/..., retryAfter: seconds ya null
  constructor(message, code = "error", retryAfter = null) {
    super(message); this.code = code; this.retryAfter = retryAfter;
  }
}

// Backend ke error response ({error:{code,message,retry_after}}) ko ApiError me badalta hai.
async function toApiError(response) {
  let data = null;
  try { data = await response.json(); } catch { /* khaali body */ }
  const err = data?.error;
  return new ApiError(err?.message || "Something went wrong. Please try again.",
                      err?.code || "error", err?.retry_after ?? null);
}

// fetch ka network-error wrapper: server band ho to friendly message.
async function safeFetch(url, options) {
  try { return await fetch(url, options); }
  catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("Couldn't reach the server. Is the backend running?", "offline");
  }
}

// request(path, options, signal) -> parsed JSON.
//   path    : "/chat" jaisa
//   options : fetch ke options (method, body, headers)
//   signal  : AbortController.signal (component unmount par request cancel karne ke liye)
async function request(path, options = {}, signal) {
  const response = await safeFetch(`${API}${path}`, {
    ...options, signal,
    headers: { "X-Workspace-Id": WORKSPACE, ...(options.headers || {}) },
  });
  if (!response.ok) throw await toApiError(response);
  try { return await response.json(); } catch { return null; }
}

const JSON_HEADERS = { "Content-Type": "application/json" };

// GET /health -> {status, indexed_chunks}
export const getHealth = (signal) => request("/health", {}, signal);
// GET /quota -> {chat:{used_today,limit_today,remaining_today,...}, embed:{...}, approx_questions_left, resets_in_seconds}
export const getQuota = (signal) => request("/quota", {}, signal);
// GET /documents -> {documents:[{file_hash,name,chunks}]}
export const getDocuments = (signal) => request("/documents", {}, signal);
// DELETE /documents/:hash -> {status:'deleted'}
export const deleteDocument = (hash) => request(`/documents/${hash}`, { method: "DELETE" });
// POST /upload (multipart) -> {filename,file_hash,chunks_indexed,already_indexed,message}
export function uploadFile(file) {
  const form = new FormData(); form.append("file", file);
  return request("/upload", { method: "POST", body: form });
}
// POST /chat -> {session_id, answer, route, quiz, sources, verified, events, quota}
export const sendChat = (sessionId, message) => request("/chat", {
  method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ session_id: sessionId, message }),
});
// GET /chat/:id -> {messages:[{role,content,meta}]}
export const getHistory = (sessionId, signal) => request(`/chat/${sessionId}`, {}, signal);
// DELETE /chat/:id -> {status:'cleared'}
export const clearChat = (sessionId) => request(`/chat/${sessionId}`, { method: "DELETE" });
// GET /chats -> {chats:[{session_id,title,updated_at,messages}]}  (sidebar ki "Recent chats")
export const getChats = (signal) => request("/chats", {}, signal);

// ======================================================================== CODE STUDIO
// POST /code/plan -> {project_id, is_new, plan:{project_name,summary,stack,files:[{path,action,purpose}],notes}}
export const codePlan = (text, projectId) => request("/code/plan", {
  method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ request: text, project_id: projectId || null }),
});
// GET /code/projects -> {projects:[{id,name,summary,updated,files}]}
export const getProjects = (signal) => request("/code/projects", {}, signal);
// GET /code/projects/:id/files -> {files:[{path,size}], meta}
export const getProjectFiles = (id, signal) => request(`/code/projects/${id}/files`, {}, signal);
// GET /code/projects/:id/file?path= -> {path, content}
export const getProjectFile = (id, path, signal) =>
  request(`/code/projects/${id}/file?path=${encodeURIComponent(path)}`, {}, signal);
// DELETE /code/projects/:id -> {status:'deleted'}
export const deleteProject = (id) => request(`/code/projects/${id}`, { method: "DELETE" });

// ZIP download: <a href> header nahi bhej sakta, isliye fetch -> blob -> temporary link se download.
export async function downloadProjectZip(id) {
  const response = await safeFetch(`${API}/code/projects/${id}/zip`, { headers: { "X-Workspace-Id": WORKSPACE } });
  if (!response.ok) throw await toApiError(response);
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url; a.download = `${id}.zip`; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// POST /code/build -> NDJSON stream. Har line ek JSON event; onEvent(event) har event par chalta hai:
//   {type:"event", event:{agent,type,message,...}} | {type:"file", path, action, content, size}
//   {type:"ping"} | {type:"done", project_id, files, summary, review, llm_calls, quota}
//   {type:"error", code, message, retry_after}
// body: {project_id, request, plan}. signal: AbortController.signal.
export async function codeBuild(body, onEvent, signal) {
  const response = await safeFetch(`${API}/code/build`, {
    method: "POST", signal, body: JSON.stringify(body),
    headers: { "X-Workspace-Id": WORKSPACE, ...JSON_HEADERS },
  });
  if (!response.ok) throw await toApiError(response);   // quota/validation error stream shuru hone se pehle
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();                                 // aakhri adhuri line agle chunk ke saath poori hogi
    for (const line of lines) {
      if (!line.trim()) continue;
      try { onEvent(JSON.parse(line)); } catch { /* kharab line ignore */ }
    }
  }
}