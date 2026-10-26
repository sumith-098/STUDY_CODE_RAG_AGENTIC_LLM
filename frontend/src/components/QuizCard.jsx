// QuizCard -- interactive MCQ quiz. Option dabao -> turant sahi/galat + explanation.
// Props: questions = [{question, options[], correct_index, explanation, source}]
import { useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

export default function QuizCard({ questions }) {
  const [picked, setPicked] = useState({});               // {questionIndex: optionIndex}
  const score = Object.entries(picked).filter(([q, o]) => questions[q].correct_index === o).length;
  const done = Object.keys(picked).length === questions.length;

  return (
    <div className="quiz">
      {questions.map((q, qi) => {
        const chosen = picked[qi];
        const answered = chosen !== undefined;
        return (
          <div className="quiz-q" key={qi}>
            <strong>{qi + 1}. {q.question}</strong>
            {q.options.map((opt, oi) => {
              let cls = "quiz-opt";
              if (answered && oi === q.correct_index) cls += " right";
              else if (answered && oi === chosen) cls += " wrong";
              return (
                <button key={oi} className={cls} disabled={answered}
                        onClick={() => setPicked(p => ({ ...p, [qi]: oi }))}>
                  {opt}
                </button>
              );
            })}
            {answered && (
              <p className="quiz-exp">
                {chosen === q.correct_index ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {q.explanation} {q.source && <em>({q.source})</em>}
              </p>
            )}
          </div>
        );
      })}
      {done && <div className="quiz-score">Score: {score} / {questions.length} 🎉</div>}
    </div>
  );
}
