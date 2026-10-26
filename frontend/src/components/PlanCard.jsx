// PlanCard -- Planner agent ka plan; user "Approve" dabaye tabhi code likha jaata hai.
// Props: plan {project_name,summary,stack,files[],notes,brief}, isNew (bool), active (bool: abhi approve ho sakta hai),
//        busy (bool), onApprove(), onCancel(), onBriefChange(text) -- user brief edit kar sakta hai
import { Check, FilePlus2, FilePen, X } from "lucide-react";

export default function PlanCard({ plan, isNew, active, busy, onApprove, onCancel, onBriefChange }) {
  return (
    <div className="plan-card">
      <div className="plan-head"><strong>{plan.project_name}</strong><span>{isNew ? "NEW PROJECT" : "UPDATE"}</span></div>
      {plan.summary && <p>{plan.summary}</p>}
      {plan.stack && <p className="plan-stack">Stack: {plan.stack}</p>}
      <div className="plan-files">
        {plan.files.map(f => (
          <div key={f.path} className="plan-file">
            {f.action === "modify" ? <FilePen size={14} /> : <FilePlus2 size={14} />}
            <code>{f.path}</code><small>{f.purpose}</small>
          </div>))}
      </div>
      {plan.notes && <p className="plan-notes">▶ {plan.notes}</p>}
      {plan.brief && (
        <details className="plan-brief">
          <summary>Detailed brief <small>{active ? "AI-written · you can edit it before building" : "AI-written"}</small></summary>
          {active
            ? <textarea value={plan.brief} onChange={e => onBriefChange?.(e.target.value)} rows={12} maxLength={6000} />
            : <pre>{plan.brief}</pre>}
        </details>)}
      {active && (
        <div className="plan-actions">
          <button className="plan-approve" onClick={onApprove} disabled={busy}><Check size={15} /> Approve & build</button>
          <button className="plan-cancel" onClick={onCancel} disabled={busy}><X size={15} /> Cancel</button>
        </div>)}
    </div>
  );
}