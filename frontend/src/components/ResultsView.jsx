import { useEffect, useState } from "react";

import { fteTotal, itemsFor, openFlags, totalFlags } from "../lib/plan.js";
import { isPrioritized, orderedSections, ROLES } from "../lib/roles.js";
import { RENDERERS } from "./Sections.jsx";

const Stat = ({ n, label }) => (
  <div className="stat">
    <strong>{n}</strong>
    <span>{label}</span>
  </div>
);

// The role decides which numbers lead the summary (issue #29).
function roleStats(plan, role) {
  const count = (key) => itemsFor(plan, key).length;
  switch (role) {
    case "manager":
      return [[count("staffing"), "staff roles"], [fteTotal(plan).toFixed(2), "est. FTE"], [count("safety"), "safety reports"]];
    case "operations":
      return [[count("technology"), "systems"], [count("pharmacy"), "pharmacy items"], [count("equipment"), "equipment items"]];
    default:
      return [[count("visits"), "visits"], [count("procedures"), "procedures"], [fteTotal(plan).toFixed(2), "est. FTE"]];
  }
}

function Summary({ plan, reviews, role, exporting, onReview, onPdf, onDocx }) {
  const p = plan.protocol || {};
  const flags = totalFlags(plan, reviews);
  const facts = [
    ["Phase", p.phase], ["Sponsor", p.sponsor], ["Therapeutic area", p.therapeutic_area],
    ["Enrollment", p.enrollment], ["Design", p.design], ["Duration", p.duration],
  ].filter(([, v]) => v != null && v !== "");

  return (
    <div className="summary card">
      <div className="summary-head">
        <div>
          <div className="eyebrow">
            {p.registry_id || ""}
            {p.pages ? ` · ${p.pages} pages` : ""}
            {plan.version > 1 ? ` · version ${plan.version}` : ""}
          </div>
          <h1 className="summary-title">{p.title}</h1>
        </div>
        <div className="summary-actions">
          {flags > 0 && (
            <button className="btn btn-primary" onClick={() => onReview()}>
              Review {flags} flagged
            </button>
          )}
          <button className={`btn ${flags ? "btn-secondary" : "btn-primary"}`} onClick={onPdf}>
            Download PDF
          </button>
          <button className="btn btn-secondary" onClick={onDocx} disabled={exporting}>
            {exporting ? "Preparing…" : "Download Word"}
          </button>
        </div>
      </div>

      <dl className="facts">
        {facts.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{String(v)}</dd>
          </div>
        ))}
      </dl>

      {plan.extraction_info?.warning && (
        <p className="extraction-note extraction-warn" role="alert">
          <strong>Limited extraction.</strong> {plan.extraction_info.warning}
        </p>
      )}
      {plan.extraction === "keyword" && (
        <p className="extraction-note">
          Early draft: CORA found these items by searching the protocol text for keywords, and each one links to the
          page it came from. The visit schedule, staffing and billing aren't extracted yet.
        </p>
      )}
      {plan.reused && (
        <p className="extraction-note">
          This protocol was uploaded before, so CORA opened the saved plan instead of extracting it again. Your own
          earlier review decisions are loaded.
        </p>
      )}

      <div className="summary-stats">
        {roleStats(plan, role).map(([n, label]) => <Stat key={label} n={n} label={label} />)}
        <div className={`stat ${flags ? "stat-warn" : "stat-ok"}`}>
          <strong>{flags}</strong>
          <span>{flags === 1 ? "item needs" : "items need"} review</span>
        </div>
      </div>
    </div>
  );
}

function Section({ section, ctx, open, onToggle }) {
  const n = openFlags(ctx.plan, section.key, ctx.reviews);
  const flag = ctx.plan.section_reviews?.[section.key];
  const Body = RENDERERS[section.key];
  return (
    <section className="card section" id={`sec-${section.key}`}>
      <header className="section-head">
        <h2>
          <button
            className="cursor-pointer border-0 bg-transparent p-0 text-left font-[inherit] text-[inherit] text-ink"
            aria-expanded={open}
            aria-controls={`body-${section.key}`}
            onClick={onToggle}
          >
            <span aria-hidden="true" className="mr-2 inline-block w-3 text-ink-2">{open ? "▾" : "▸"}</span>
            {section.label}
          </button>
        </h2>
        {n ? <span className="pill pill-warn">{n} to review</span> : <span className="pill pill-ok">Looks good</span>}
      </header>
      {/* Collapsed sections stay in the page (hidden), so they remain reachable and printable. */}
      <div id={`body-${section.key}`} hidden={!open}>
        {flag?.needs_review && (
          <p className="note note-warn mb-3" role="note">
            Check this section: {flag.reason}
          </p>
        )}
        <Body ctx={ctx} />
      </div>
    </section>
  );
}

export default function ResultsView({ state, role, exporting, onRole, onFlaggedOnly, onReview, onPdf, onDocx, onScrolled }) {
  const { plan, reviews, flaggedOnly, unsaved, scrollTo } = state;
  const sections = orderedSections(role);
  // Which sections are expanded. Starts from the role: its sections open,
  // the others collapsed. The user can then open or close any of them.
  const [open, setOpen] = useState(() => Object.fromEntries(sections.map((s) => [s.key, isPrioritized(role, s.key)])));
  useEffect(() => {
    setOpen(Object.fromEntries(sections.map((s) => [s.key, isPrioritized(role, s.key)])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  // After "Back to plan", jump to the section of the item that was being reviewed.
  useEffect(() => {
    if (!scrollTo) return;
    setOpen((o) => ({ ...o, [scrollTo]: true }));
    document.getElementById(`sec-${scrollTo}`)?.scrollIntoView?.();
    onScrolled();
  }, [scrollTo, onScrolled]);

  const ctx = { plan, reviews, flaggedOnly, unsaved, onReview };

  return (
    <section id="resultsView" className="view results">
      <aside className="sidenav" aria-label="Sections">
        <label className="mb-4 flex flex-col gap-1 text-[13px] text-ink-2">
          <span>View as</span>
          <select
            id="rolePicker"
            className="rounded-lg border border-line bg-surface px-2 py-1.5 text-[13px] text-ink"
            value={role}
            onChange={(e) => onRole(e.target.value)}
          >
            {ROLES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </label>
        <nav id="sectionNav">
          {sections.map((s) => {
            const n = openFlags(plan, s.key, reviews);
            return (
              <a key={s.key} href={`#sec-${s.key}`} onClick={() => setOpen((o) => ({ ...o, [s.key]: true }))}>
                {s.label}
                {n > 0 && <span className="badge-count">{n}</span>}
              </a>
            );
          })}
        </nav>
        <div className="sidenav-footer">
          <label className="toggle">
            <input id="flaggedOnly" type="checkbox" checked={flaggedOnly} onChange={(e) => onFlaggedOnly(e.target.checked)} />
            <span>Only show flagged items</span>
          </label>
        </div>
      </aside>

      <div className="results-main">
        <Summary plan={plan} reviews={reviews} role={role} exporting={exporting} onReview={onReview} onPdf={onPdf} onDocx={onDocx} />
        <div id="sections">
          {sections.map((s) => (
            <Section
              key={s.key}
              section={s}
              ctx={ctx}
              open={open[s.key] ?? true}
              onToggle={() => setOpen((o) => ({ ...o, [s.key]: !(o[s.key] ?? true) }))}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
