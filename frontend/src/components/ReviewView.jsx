import { useEffect, useState } from "react";

import { REVIEW_THRESHOLD } from "../config.js";
import { FIELDS, fmtValue, keyParts, reviewCounts, same, SECTIONS, STATUS_LABEL } from "../lib/plan.js";

// Shows the uploaded PDF at the item's source page. Sample data has no PDF.
function SourcePane({ pdfUrl, page, isSample }) {
  if (!pdfUrl) {
    return (
      <div id="sourcePane" className="card source-pane">
        <div className="src-empty">
          <strong>Source protocol</strong>
          <p>
            {isSample ? "The sample uses a fictional protocol, so there's no PDF to show." : "The source PDF isn't available."}
            {page ? ` In a real upload, page ${page} opens here so you can check the item against the protocol.` : ""}
          </p>
        </div>
      </div>
    );
  }
  const src = `${pdfUrl}#page=${page || 1}&navpanes=0&view=FitH`;
  return (
    <div id="sourcePane" className="card source-pane">
      <div className="src-head">
        <strong>Source protocol</strong>
        <span className="muted">{page ? `p. ${page}` : "No page reference"}</span>
        <a href={src} target="_blank" rel="noopener">Open in new tab</a>
      </div>
      {/* key={src}: a fresh iframe each time. The built-in PDF viewer ignores
          a changed #page on a document that is already open. */}
      <iframe key={src} className="src-frame" src={src} title="Source protocol PDF" />
    </div>
  );
}

function Field({ fd, value, original, locked, visits, onChange }) {
  const id = `rv-${fd.f}`;
  let input;
  if (fd.type === "visits") {
    const picked = value || [];
    input = (
      <div className="visit-picks" id={id}>
        {!visits.length && <span className="muted">No visits extracted yet</span>}
        {visits.map((v) => (
          <label key={v.id} className="visit-pick" title={`${v.name ?? ""} · ${v.day ?? ""}`}>
            <input
              type="checkbox"
              value={v.id}
              checked={picked.includes(v.id)}
              disabled={locked}
              // Keep the schedule's order, whatever order the boxes are ticked in.
              onChange={(e) =>
                onChange(visits.map((x) => x.id).filter((x) => (x === v.id ? e.target.checked : picked.includes(x))))
              }
            />
            <span className="mono">{v.id}</span>
          </label>
        ))}
      </div>
    );
  } else if (fd.type === "textarea") {
    input = <textarea id={id} rows={3} disabled={locked} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  } else if (fd.type === "number") {
    input = (
      <input
        id={id} type="number" step="0.05" min="0" disabled={locked} value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
      />
    );
  } else {
    input = (
      <input
        id={id} type="text" list={fd.type === "designation" ? "designations" : undefined} disabled={locked}
        value={value ?? ""} onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <div className="rv-field">
      <label htmlFor={id}>{fd.label}</label>
      {input}
      {original && !same(original[fd.f], value) && <div className="rv-was">Was: {fmtValue(original[fd.f])}</div>}
    </div>
  );
}

const trimmed = (vals) => Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, typeof v === "string" ? v.trim() : v]));

// The form for one flagged item. The parent gives it key={item key}, so
// moving to another item mounts a fresh form with that item's values.
function ItemForm({ k, item, sec, decision, visits, position, total, onDecide, onUndo, onMove }) {
  const fields = FIELDS[sec];
  const [vals, setVals] = useState(() => Object.fromEntries(fields.map((fd) => [fd.f, item[fd.f]])));
  const [comment, setComment] = useState(decision?.comment || "");
  const locked = Boolean(decision);
  const edited = fields.some((fd) => !same(trimmed(vals)[fd.f], item[fd.f]));
  const pct = Math.round(item.confidence * 100);
  const label = SECTIONS.find((s) => s.key === sec).label;

  return (
    <>
      <div className="rv-head">
        <span className="eyebrow">{label} · {position + 1} of {total}</span>
        {decision && (
          <span className={`pill pill-${decision.status}`}>
            {STATUS_LABEL[decision.status]}{decision.reviewer ? ` by ${decision.reviewer}` : ""}
          </span>
        )}
      </div>
      <h2 className="rv-title">{String(item[fields[0].f] ?? "")}</h2>
      <div className="rv-why">
        <div className="conf">
          <div className="conf-bar"><span style={{ width: `${pct}%` }} className="low" /></div>
          <span className="mono">{pct}%</span>
        </div>
        <p>{item.notes || `Confidence is below the ${Math.round(REVIEW_THRESHOLD * 100)}% review threshold.`}</p>
      </div>
      <form id="rvForm" className="rv-form" autoComplete="off" onSubmit={(e) => e.preventDefault()}>
        {fields.map((fd) => (
          <Field
            key={fd.f} fd={fd} value={locked ? item[fd.f] : vals[fd.f]} original={decision?.original}
            locked={locked} visits={visits} onChange={(v) => setVals((old) => ({ ...old, [fd.f]: v }))}
          />
        ))}
        <div className="rv-field">
          <label htmlFor="rvComment">Comment</label>
          <textarea
            id="rvComment" rows={2} placeholder="Optional: why you changed or rejected this" disabled={locked}
            value={comment} onChange={(e) => setComment(e.target.value)}
          />
        </div>
      </form>
      <div className="rv-actions">
        <button id="rvPrev" className="btn btn-ghost" disabled={position === 0} onClick={() => onMove(position - 1)}>← Prev</button>
        <span className="spacer" />
        {decision ? (
          <button id="rvUndo" className="btn btn-secondary" onClick={() => onUndo(k)}>Undo decision</button>
        ) : (
          <>
            <button id="rvReject" className="btn btn-danger" onClick={() => onDecide(k, "rejected", trimmed(vals), comment.trim())}>Reject</button>
            <button id="rvAccept" className="btn btn-primary" onClick={() => onDecide(k, "accepted", trimmed(vals), comment.trim())}>
              {edited ? "Accept with edits" : "Accept"}
            </button>
          </>
        )}
        <button id="rvNext" className="btn btn-ghost" disabled={position === total - 1} onClick={() => onMove(position + 1)}>Next →</button>
      </div>
      <p className="kbd-hint">
        Shortcuts: <kbd>A</kbd> accept · <kbd>R</kbd> reject · <kbd>←</kbd> <kbd>→</kbd> move
      </p>
    </>
  );
}

function Queue({ plan, queue, qi, reviews, onMove }) {
  return (
    <div className="rv-queue">
      <h3>Flagged items</h3>
      <ol>
        {queue.map((k, j) => {
          const { sec, item } = keyParts(plan, k);
          const r = reviews[k];
          return (
            <li key={k}>
              <button className={j === qi ? "current" : ""} onClick={() => onMove(j)}>
                <span className="rv-q-title">{String(item[FIELDS[sec][0].f] ?? "")}</span>
                <span className={`pill pill-${r ? r.status : "open"}`}>{r ? STATUS_LABEL[r.status] : "Open"}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export default function ReviewView({ state, pdfUrl, reviewerName, onReviewerName, reviewerInput, onDecide, onUndo, onMove, onBack, onPdf }) {
  const { plan, queue, qi, reviews } = state;
  const decided = queue.filter((k) => reviews[k]).length;
  const k = qi >= 0 ? queue[qi] : null;
  const current = k ? keyParts(plan, k) : null;

  // Keyboard shortcuts. The listener is on the document, so it is added when
  // this screen appears and removed when it goes away.
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.target.closest?.("input, textarea, select")) return; // don't hijack typing
      const id = { a: "rvAccept", r: "rvReject", ArrowLeft: "rvPrev", ArrowRight: "rvNext" }[e.key];
      const btn = id && document.getElementById(id);
      if (btn && !btn.disabled) {
        e.preventDefault();
        btn.click();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const counts = reviewCounts(reviews);

  return (
    <section id="reviewView" className="view review">
      <div className="review-bar">
        <button id="backToPlan" className="btn btn-ghost" onClick={onBack}>← Back to plan</button>
        <div className="review-progress">
          <span id="reviewCount">{decided} of {queue.length} reviewed</span>
          <div className="progress" aria-hidden="true">
            <span id="reviewProgress" style={{ width: `${queue.length ? (decided / queue.length) * 100 : 0}%` }} />
          </div>
        </div>
        <label className="reviewer">
          <span>Reviewer</span>
          <input
            id="reviewerName" ref={reviewerInput} type="text" placeholder="Your name" autoComplete="name"
            value={reviewerName} onChange={(e) => onReviewerName(e.target.value)}
          />
        </label>
      </div>
      <div className="review-grid">
        <SourcePane pdfUrl={pdfUrl} page={current?.item.source_page} isSample={plan.is_sample} />
        <div id="reviewPane" className="card review-pane">
          {current ? (
            <ItemForm
              // The decision is part of the key so the form resets after Accept/Undo.
              key={`${k}:${reviews[k]?.status || "open"}`}
              k={k} item={current.item} sec={current.sec} decision={reviews[k]} visits={plan.visits || []}
              position={qi} total={queue.length} onDecide={onDecide} onUndo={onUndo} onMove={onMove}
            />
          ) : (
            <div className="rv-done">
              <h2>All flagged items reviewed</h2>
              <p className="muted">{counts.accepted} accepted · {counts.edited} edited · {counts.rejected} rejected</p>
              <div className="rv-actions">
                <button id="rvDoneBack" className="btn btn-secondary" onClick={onBack}>Back to plan</button>
                <button id="rvDoneExport" className="btn btn-primary" onClick={onPdf}>Download PDF</button>
              </div>
            </div>
          )}
          <Queue plan={plan} queue={queue} qi={qi} reviews={reviews} onMove={onMove} />
        </div>
      </div>
    </section>
  );
}
