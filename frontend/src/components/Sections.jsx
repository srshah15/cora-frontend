// One renderer per plan section. Each takes the working plan and review
// state and returns the section body (a table, the visit timeline, or an
// empty-state message).

import { isFlagged, isOpen, itemsFor, reviewable, STATUS_LABEL } from "../lib/plan.js";

const text = (v) => (v == null ? "" : String(v));

function Notes({ item, k, flagged, reviews, unsaved }) {
  const r = reviews[k];
  return (
    <>
      {item.notes && <div className={`note${flagged ? " note-warn" : ""}`}>{item.notes}</div>}
      {r?.comment && (
        <div className="note note-review">
          {r.reviewer || "Reviewer"}: {r.comment}
        </div>
      )}
      {unsaved[k] && <div className="note note-warn">Not saved to the server. It is kept on this screen only.</div>}
      {item.source_page && <div className="src">p. {item.source_page}</div>}
    </>
  );
}

function ConfCell({ item, k, sectionKey, reviews, onReview }) {
  if (typeof item.confidence !== "number") return null;
  const pct = Math.round(item.confidence * 100);
  const flagged = isFlagged(item);
  const r = reviews[k];
  return (
    <>
      <div className="conf">
        <div className="conf-bar">
          <span style={{ width: `${pct}%` }} className={flagged ? "low" : ""} />
        </div>
        <span className="mono">{pct}%</span>
      </div>
      {flagged && reviewable(sectionKey) && (
        <button className={`review-btn${r ? ` ${r.status}` : ""}`} onClick={() => onReview(k)}>
          {r ? STATUS_LABEL[r.status] : "Review"}
        </button>
      )}
    </>
  );
}

const rowClass = (item, k, reviews) =>
  isOpen(item, k, reviews) ? "row-flag" : reviews[k]?.status === "rejected" ? "row-rejected" : "";

// Rows for list-style sections, with review badges and the flagged-only filter.
function Rows({ sectionKey, cols, ctx }) {
  const { plan, reviews, flaggedOnly } = ctx;
  const items = itemsFor(plan, sectionKey);
  const visible = items
    .map((it, i) => ({ it, k: `${sectionKey}:${i}` }))
    .filter(({ it, k }) => !flaggedOnly || isOpen(it, k, reviews));
  if (!items.length) return <p className="empty">Nothing found in the protocol for this category.</p>;
  if (!visible.length) return <p className="empty">No open flags here.</p>;

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => <th key={c.label}>{c.label}</th>)}
            <th className="col-conf">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {visible.map(({ it, k }) => (
            <tr key={k} className={rowClass(it, k, reviews)}>
              {cols.map((c, ci) => (
                <td key={c.label} className={ci === 0 ? "cell-main" : undefined}>
                  {c.render ? c.render(it) : text(it[c.field])}
                  {ci === 0 && <Notes item={it} k={k} flagged={isOpen(it, k, reviews)} reviews={reviews} unsaved={ctx.unsaved} />}
                </td>
              ))}
              <td className="col-conf">
                <ConfCell item={it} k={k} sectionKey={sectionKey} reviews={reviews} onReview={ctx.onReview} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Visits({ ctx }) {
  const visits = ctx.plan.visits || [];
  if (!visits.length) return <p className="empty">No visits extracted.</p>;
  return (
    <ol className="timeline">
      {visits.map((v) => (
        <li key={v.id} className={v.type === "Phone" ? "remote" : ""}>
          <span className="tl-dot" />
          <div className="tl-id mono">{v.id}</div>
          <div className="tl-name">{v.name}</div>
          <div className="tl-day">
            {v.day}
            {v.window && <span className="muted"> {v.window}</span>}
          </div>
          <div className="tl-type">{v.type || ""}</div>
          {isFlagged(v) ? (
            <div className="note note-warn">Needs checking{v.notes ? `: ${v.notes}` : ""}</div>
          ) : (
            v.notes && <div className="note">{v.notes}</div>
          )}
          {v.source_page && <div className="src">p. {v.source_page}</div>}
        </li>
      ))}
    </ol>
  );
}

function Procedures({ ctx }) {
  const { plan, reviews, flaggedOnly } = ctx;
  const visits = plan.visits || [];
  const all = plan.procedures || [];
  const procs = all
    .map((p, i) => ({ p, k: `procedures:${i}` }))
    .filter(({ p, k }) => !flaggedOnly || isOpen(p, k, reviews));
  if (!all.length) return <p className="empty">No procedures extracted.</p>;
  if (!procs.length) return <p className="empty">No open flags here.</p>;

  return (
    <>
      <p className="section-sub">
        {visits.length
          ? "Schedule of assessments. Each mark is a procedure required at that visit."
          : "Procedures mentioned in the protocol. Which visit each one happens at isn't extracted yet."}
      </p>
      <div className="table-wrap">
        <table className="soa">
          <thead>
            <tr>
              <th className="sticky">Procedure</th>
              {visits.map((v) => (
                <th key={v.id} title={`${text(v.name)} · ${text(v.day)}`}>
                  <span className="mono">{v.id}</span>
                </th>
              ))}
              <th className="col-conf">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {procs.map(({ p, k }) => (
              <tr key={k} className={rowClass(p, k, reviews)}>
                <td className="sticky cell-main">
                  {p.name} <span className="cat">{p.category || ""}</span>
                  <Notes item={p} k={k} flagged={isOpen(p, k, reviews)} reviews={reviews} unsaved={ctx.unsaved} />
                </td>
                {visits.map((v) => (
                  <td key={v.id} className="mark" aria-label={p.visits?.includes(v.id) ? `Required at ${v.id}` : undefined}>
                    {p.visits?.includes(v.id) ? "●" : ""}
                  </td>
                ))}
                <td className="col-conf">
                  <ConfCell item={p} k={k} sectionKey="procedures" reviews={reviews} onReview={ctx.onReview} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function designationTag(b) {
  const d = text(b.designation);
  const cls = /sponsor/i.test(d) ? "tag-sponsor" : /standard|soc/i.test(d) ? "tag-soc" : "tag-other";
  return <span className={`tag ${cls}`}>{d}</span>;
}

const chips = (ids) => (ids || []).map((id) => <span key={id} className="chip">{id} </span>);

function Pharmacy({ ctx }) {
  const ph = ctx.plan.pharmacy;
  if (!ph) return <p className="empty">No pharmacy info extracted.</p>;
  return (
    <>
      <p className="section-sub">
        Investigational pharmacy {ph.involved ? <><strong>is</strong></> : <>is <strong>not</strong></>} involved.
      </p>
      <Rows sectionKey="pharmacy" cols={[{ label: "Requirement", field: "item" }]} ctx={ctx} />
    </>
  );
}

export const RENDERERS = {
  visits: Visits,
  procedures: Procedures,
  staffing: ({ ctx }) => (
    <Rows
      sectionKey="staffing"
      ctx={ctx}
      cols={[
        { label: "Role", field: "role" },
        { label: "Est. FTE", render: (s) => <span className="mono">{text(s.fte)}</span> },
        { label: "Responsibilities", field: "responsibilities" },
        { label: "Qualifications", field: "qualifications" },
      ]}
    />
  ),
  safety: ({ ctx }) => (
    <Rows
      sectionKey="safety"
      ctx={ctx}
      cols={[
        { label: "Event", field: "event" },
        { label: "Timeline", field: "timeline" },
        { label: "Report to", field: "recipient" },
        { label: "Method", field: "method" },
      ]}
    />
  ),
  billing: ({ ctx }) => (
    <Rows
      sectionKey="billing"
      ctx={ctx}
      cols={[
        { label: "Item", field: "item" },
        { label: "Designation", render: designationTag },
        { label: "Visits", render: (b) => chips(b.visits) },
      ]}
    />
  ),
  equipment: ({ ctx }) => (
    <Rows sectionKey="equipment" ctx={ctx} cols={[{ label: "Item", field: "item" }, { label: "Purpose", field: "purpose" }]} />
  ),
  pharmacy: Pharmacy,
  technology: ({ ctx }) => (
    <Rows sectionKey="technology" ctx={ctx} cols={[{ label: "System", field: "system" }, { label: "Purpose", field: "purpose" }]} />
  ),
};
