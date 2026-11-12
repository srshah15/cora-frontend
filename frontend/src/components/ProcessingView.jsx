import { useEffect, useRef, useState } from "react";

import { timing } from "../config.js";

const STEPS = [
  ["Ingestion", "Extracting text from the PDF, OCR if needed"],
  ["Extraction", "Pulling each operational category from the text"],
  ["Structuring", "Mapping results into the standard schema"],
  ["Review check", "Flagging low-confidence items for a human"],
];

// Walks through the pipeline steps on a timer. The backend is a single
// request, so this is cosmetic: it shows that work is happening. When the
// plan arrives (`finishing`), the remaining steps complete quickly and
// onFinished is called.
export default function ProcessingView({ filename, finishing, perStep, onFinished }) {
  const [active, setActive] = useState(0); // index of the step in progress; STEPS.length = all done
  // A ref holds the latest callback without restarting the timers when the
  // parent re-renders and passes a new function.
  const done = useRef(onFinished);
  done.current = onFinished;

  useEffect(() => {
    if (finishing) return undefined;
    // While waiting: advance, but never past the last step.
    const timer = setInterval(() => setActive((i) => Math.min(i + 1, STEPS.length - 1)), timing.step);
    return () => clearInterval(timer); // cleanup runs when the effect ends or the screen goes away
  }, [finishing]);

  useEffect(() => {
    if (!finishing) return undefined;
    if (active >= STEPS.length) {
      const t = setTimeout(() => done.current(), timing.finishPause);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setActive((i) => i + 1), perStep ?? timing.finishStep);
    return () => clearTimeout(t);
  }, [finishing, active, perStep]);

  return (
    <section id="processingView" className="view">
      <div className="processing-card">
        <h2 id="processingTitle">Processing protocol</h2>
        <p id="processingFile" className="muted mono">{filename}</p>
        <ol id="steps" className="steps">
          {STEPS.map(([title, text], i) => (
            <li key={title} className={i < active ? "done" : i === active ? "active" : ""}>
              <span className="dot" />
              <div>
                <strong>{title}</strong>
                <span>{text}</span>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
