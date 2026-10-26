// Welcome -- khaali chat par simple intro + 4 suggestion cards.
// Props: onPick(text) -- card dabane par wo text sawaal ki tarah bhej do
import Mark from "./Mark.jsx";

const SUGGESTIONS = [
  ["Explain my notes", "Key concepts in simple steps.", "Explain the main concepts in my uploaded study documents."],
  ["Make a quiz", "Interactive MCQs from your notes.", "Create a 5 question quiz from my uploaded documents."],
  ["Summarize a chapter", "Key points and terms, with page references.", "Summarize my uploaded documents with key points and important terms."],
  ["Plan my revision", "A day-by-day schedule until your exam.", "Make a 7 day revision plan from my uploaded documents."],
];

export default function Welcome({ onPick }) {
  return (
    <div className="welcome">
      <Mark size={46} />
      <h1>Study with <em>clarity</em>.</h1>
      <p className="welcome-copy">Upload your notes, then ask anything. The right specialist answers, with page references you can check.</p>
      <div className="suggestion-grid">
        {SUGGESTIONS.map(([title, sub, prompt]) => (
          <button key={title} onClick={() => onPick(prompt)}>
            <strong>{title}</strong><small>{sub}</small>
          </button>
        ))}
      </div>
    </div>
  );
}