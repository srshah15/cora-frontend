import { describe, expect, it } from "vitest";

import { initialState, reducer } from "./state.js";

const plan = {
  protocol: {},
  safety: [
    { event: "SAE", timeline: "24 hours", confidence: 0.5 },
    { event: "Pregnancy", timeline: null, confidence: 0.4 },
  ],
};
const loaded = (extra = {}) => reducer(initialState, { type: "PLAN_LOADED", plan: { ...plan, ...extra }, hasPdf: false });
const decision = (status, values) => ({ status, comment: "", reviewer: "Ana", at: "now", original: { event: "SAE", timeline: "24 hours" }, values });

describe("app state reducer", () => {
  it("moves upload -> processing -> results", () => {
    let s = reducer(initialState, { type: "PROCESSING_STARTED", filename: "a.pdf" });
    expect(s.view).toBe("processing");
    expect(s.processing).toEqual({ filename: "a.pdf", finishing: false });
    s = reducer(s, { type: "PLAN_LOADED", plan, hasPdf: true });
    expect(s.view).toBe("results");
    expect(s.processing).toBeNull();
  });

  it("returns to the upload view with the error on failure", () => {
    let s = reducer(initialState, { type: "PROCESSING_STARTED", filename: "a.pdf" });
    s = reducer(s, { type: "UPLOAD_FAILED", error: { kind: "unreachable", message: "x" } });
    expect(s.view).toBe("upload");
    expect(s.uploadError.kind).toBe("unreachable");
  });

  it("clears an old error when a new upload starts", () => {
    let s = reducer(initialState, { type: "UPLOAD_FAILED", error: { kind: "server", message: "x" } });
    s = reducer(s, { type: "PROCESSING_STARTED", filename: "b.pdf" });
    expect(s.uploadError).toBeNull();
  });

  it("opens the review queue at the first open item, or at a chosen one", () => {
    expect(reducer(loaded(), { type: "REVIEW_OPENED" })).toMatchObject({ view: "review", qi: 0, queue: ["safety:0", "safety:1"] });
    expect(reducer(loaded(), { type: "REVIEW_OPENED", key: "safety:1" }).qi).toBe(1);
  });

  it("records a decision and advances to the next open item", () => {
    let s = reducer(loaded(), { type: "REVIEW_OPENED" });
    s = reducer(s, { type: "DECIDED", decision: decision("accepted") });
    expect(s.reviews["safety:0"].status).toBe("accepted");
    expect(s.qi).toBe(1);
    s = reducer(s, { type: "DECIDED", decision: decision("rejected") });
    expect(s.qi).toBe(-1); // everything reviewed
  });

  it("applies an edit to the working plan and undo restores the original", () => {
    let s = reducer(loaded(), { type: "REVIEW_OPENED" });
    s = reducer(s, { type: "DECIDED", decision: decision("edited", { event: "Serious AE", timeline: "24 hours" }) });
    expect(s.plan.safety[0].event).toBe("Serious AE");

    s = reducer(s, { type: "REVIEW_MOVED", index: 0 });
    s = reducer(s, { type: "UNDONE" });
    expect(s.plan.safety[0].event).toBe("SAE");
    expect(s.reviews["safety:0"]).toBeUndefined();
  });

  it("re-applies saved edits that arrive with a reused plan", () => {
    const s = loaded({ reviews: { "safety:1": { status: "edited", values: { timeline: "Immediately" } } } });
    expect(s.plan.safety[1].timeline).toBe("Immediately");
    expect(s.reviews["safety:1"].status).toBe("edited");
  });

  it("'New protocol' clears everything", () => {
    const s = reducer(reducer(loaded(), { type: "REVIEW_OPENED" }), { type: "RESET" });
    expect(s).toEqual(initialState);
  });

  it("tracks decisions that failed to save", () => {
    let s = reducer(loaded(), { type: "SAVE_FAILED", key: "safety:0" });
    expect(s.unsaved).toEqual({ "safety:0": true });
    s = reducer(s, { type: "SAVE_SUCCEEDED", key: "safety:0" });
    expect(s.unsaved).toEqual({});
  });
});
