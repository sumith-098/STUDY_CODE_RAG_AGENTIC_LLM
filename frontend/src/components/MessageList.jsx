// MessageList -- chat messages. User: soft bubble. Assistant: bina bubble, serif text (padhne me aaram).
// Props: messages, thinking (bool), bottomRef (auto-scroll ke liye)
import Mark from "./Mark.jsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AgentTrace from "./AgentTrace.jsx";
import QuizCard from "./QuizCard.jsx";

export default function MessageList({ messages, thinking, bottomRef }) {
  return (
    <div className="message-list">
      {messages.map(m => (
        <article className={`message ${m.role}`} key={m.id}>
          {m.role === "assistant" && <div className="msg-mark"><Mark size={24} /></div>}
          <div className="message-body">
            {m.role === "assistant" && (
              <div className="message-author">StudyPilot{m.route && <span>{m.route}</span>}</div>
            )}
            <div className="message-content md">
              {m.role === "assistant"
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                : m.content}
            </div>
            {m.quiz?.length > 0 && <QuizCard questions={m.quiz} />}
            {m.sources?.length > 0 && (
              <div className="sources">
                {m.sources.map(s => <span className="source-chip" key={`${s.source}-${s.page}`}>{s.source} · p.{s.page}</span>)}
                {m.verified === true && <span className="verified">✔ verified</span>}
                {m.verified === false && <span className="verified fixed">✎ auto-corrected</span>}
              </div>
            )}
            <AgentTrace events={m.events} route={m.route} />
          </div>
        </article>
      ))}
      {thinking && (
        <div className="thinking">
          <div className="msg-mark pulse"><Mark size={24} /></div>
          <span className="thinking-label">Working on it…</span>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}