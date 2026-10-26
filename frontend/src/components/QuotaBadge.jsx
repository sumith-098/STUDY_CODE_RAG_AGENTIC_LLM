// QuotaBadge -- free tier me aaj kitne sawaal bache, patli bar ke saath (green/amber/red).
// Props: quota = backend /quota ka object (ya null)
import { Gauge } from "lucide-react";

export default function QuotaBadge({ quota }) {
  if (!quota) return null;
  const left = quota.approx_questions_left;
  const pct = quota.chat.remaining_today / quota.chat.limit_today;
  const level = pct > 0.4 ? "ok" : pct > 0.15 ? "warn" : "low";
  const hours = Math.max(1, Math.ceil(quota.resets_in_seconds / 3600));
  return (
    <div className={`quota-badge ${level}`} title={`AI calls today: ${quota.chat.used_today}/${quota.chat.limit_today}. Resets in about ${hours}h.`}>
      <div className="quota-text"><Gauge size={14} /><span>~{left} questions left today</span></div>
      <div className="quota-bar"><i style={{ width: `${Math.max(3, Math.round(pct * 100))}%` }} /></div>
    </div>
  );
}