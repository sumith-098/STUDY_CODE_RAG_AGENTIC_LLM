// AgentTrace -- "Agent activity" dropdown: kaunsa agent kab chala, kya tool use hua.
// Props: events = [{agent, type, message, ...extra}], route = specialist naam
import { Wrench } from "lucide-react";

export default function AgentTrace({ events, route }) {
  if (!events?.length) return null;
  return (
    <details className="activity">
      <summary><Wrench size={14} /> Agent activity · {route} · {events.length} steps</summary>
      {events.map((e, i) => (
        <div className="event-row" key={i}>
          <span className="event-marker" />
          <div>
            <strong>{e.agent}</strong> — {e.message}
            {e.queries && <pre>{JSON.stringify(e.queries)}</pre>}
            {e.found && <pre>{e.found.join("\n")}</pre>}
            {e.arguments && <pre>{JSON.stringify(e.arguments)}</pre>}
          </div>
        </div>
      ))}
    </details>
  );
}
