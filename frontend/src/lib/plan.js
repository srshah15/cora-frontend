// Pure helpers for working with a plan. No React and no DOM in here, so each
// function can be unit-tested with plain objects.

import { REVIEW_THRESHOLD } from "../config.js";

export const SECTIONS = [
  { key: "visits", label: "Visit schedule" },
  { key: "procedures", label: "Procedures" },
  { key: "staffing", label: "Staffing" },
  { key: "safety", label: "Safety reporting" },
  { key: "billing", label: "Billing" },
  { key: "equipment", label: "Equipment" },
  { key: "pharmacy", label: "Pharmacy" },
  { key: "technology", label: "Technology" },
];

// Editable fields per section. The first field is the item's title.
// Visits have no entry: they can't be reviewed one by one (the backend's
// review keys don't allow it), so low-confidence visits are marked on the
// timeline instead.
export const FIELDS = {
  procedures: [
    { f: "name", label: "Procedure" },
    { f: "category", label: "Category" },
    { f: "visits", label: "Visits", type: "visits" },
  ],
  staffing: [
    { f: "role", label: "Role" },
    { f: "fte", label: "Est. FTE", type: "number" },
    { f: "responsibilities", label: "Responsibilities", type: "textarea" },
  ],
  safety: [
    { f: "event", label: "Event" },
    { f: "timeline", label: "Timeline" },
    { f: "recipient", label: "Report to" },
    { f: "method", label: "Method" },
  ],
  billing: [
    { f: "item", label: "Item" },
    { f: "designation", label: "Designation", type: "designation" },
    { f: "visits", label: "Visits", type: "visits" },
  ],
  equipment: [
    { f: "item", label: "Item" },
    { f: "purpose", label: "Purpose", type: "textarea" },
  ],
  pharmacy: [{ f: "item", label: "Requirement", type: "textarea" }],
  technology: [
    { f: "system", label: "System" },
    { f: "purpose", label: "Purpose", type: "textarea" },
  ],
};

export const STATUS_LABEL = { accepted: "Accepted", edited: "Edited", rejected: "Rejected" };

export const reviewable = (key) => Boolean(FIELDS[key]);

// The one rule for "needs human review": a numeric confidence strictly below
// the threshold. Exactly 0.7 is not flagged; a missing confidence is not flagged.
export const isFlagged = (item, threshold = REVIEW_THRESHOLD) =>
  typeof item?.confidence === "number" && item.confidence < threshold;

export function itemsFor(plan, key) {
  if (!plan) return [];
  if (key === "pharmacy") return plan.pharmacy?.items || [];
  return plan[key] || [];
}

// Flagged and no decision yet.
export const isOpen = (item, key, reviews) => isFlagged(item) && !reviews[key];

export function openFlags(plan, key, reviews) {
  if (!reviewable(key)) return 0;
  return itemsFor(plan, key).filter((it, i) => isOpen(it, `${key}:${i}`, reviews)).length;
}

export const totalFlags = (plan, reviews) => SECTIONS.reduce((n, s) => n + openFlags(plan, s.key, reviews), 0);

// Keys of every flagged, reviewable item, in plan order: the review queue.
export const flaggedKeys = (plan) =>
  SECTIONS.filter((s) => reviewable(s.key)).flatMap((s) =>
    itemsFor(plan, s.key).flatMap((it, i) => (isFlagged(it) ? [`${s.key}:${i}`] : []))
  );

// First undecided item at or after `from`, wrapping around; -1 if none left.
export function nextOpen(queue, reviews, from) {
  for (let n = 0; n < queue.length; n++) {
    const j = (from + n) % queue.length;
    if (!reviews[queue[j]]) return j;
  }
  return -1;
}

export function keyParts(plan, k) {
  const [sec, i] = k.split(":");
  return { sec, index: Number(i), item: itemsFor(plan, sec)[Number(i)] };
}

export const fteTotal = (plan) => (plan?.staffing || []).reduce((n, s) => n + (Number(s.fte) || 0), 0);

export const slug = (plan) =>
  (plan.protocol?.short_title || plan.protocol?.registry_id || "protocol")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "protocol";

export const fmtValue = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "") || "(empty)";
export const same = (a, b) => JSON.stringify(a ?? "") === JSON.stringify(b ?? "");

// Returns a NEW plan with `values` merged into one item. React state must not
// be changed in place: React compares old and new objects to decide what to
// redraw, so we copy the path we change and leave the rest shared.
export function withItemValues(plan, k, values) {
  const { sec, index } = keyParts(plan, k);
  const patch = (items) => items.map((it, i) => (i === index ? { ...it, ...values } : it));
  if (sec === "pharmacy") return { ...plan, pharmacy: { ...plan.pharmacy, items: patch(plan.pharmacy?.items || []) } };
  return { ...plan, [sec]: patch(plan[sec] || []) };
}

// A plan loaded from the server is the shared, unedited version. Re-apply
// this reviewer's own saved edits on top of it.
export function applyReviews(plan, reviews) {
  let out = plan;
  for (const [k, r] of Object.entries(reviews || {})) {
    if (r.status === "edited" && r.values && keyParts(out, k).item) out = withItemValues(out, k, r.values);
  }
  return out;
}

export function reviewCounts(reviews) {
  const counts = { accepted: 0, edited: 0, rejected: 0 };
  for (const r of Object.values(reviews)) counts[r.status]++;
  return counts;
}
