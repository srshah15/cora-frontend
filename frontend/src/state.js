// All app state lives in one reducer.
//
// A reducer is a function (state, action) -> new state. Components never
// change state directly; they dispatch an action that says what happened
// ("PLAN_LOADED", "DECIDED"), and this file is the only place that decides
// what that means. Because it is a pure function, it can be tested without
// rendering anything.

import { applyReviews, flaggedKeys, keyParts, nextOpen, withItemValues } from "./lib/plan.js";

export const initialState = {
  view: "upload", // upload | processing | results | review
  plan: null, // the working plan: the server's plan with this reviewer's edits applied
  // Reviewer decisions keyed like "safety:2":
  // { status, comment, reviewer, at, original, values }
  reviews: {},
  unsaved: {}, // keys whose decision could not be saved to the server
  flaggedOnly: false,
  hasPdf: false,
  processing: null, // { filename, finishing: bool, perStep }
  uploadError: null, // { kind, message }
  queue: [], // flagged item keys, in plan order
  qi: 0, // index into queue; -1 means everything is reviewed
  scrollTo: null, // section key to scroll to after returning to the plan
};

export function reducer(state, action) {
  switch (action.type) {
    case "PROCESSING_STARTED":
      return { ...state, view: "processing", uploadError: null, processing: { filename: action.filename, finishing: false } };

    case "PROCESSING_FINISHING":
      // The plan has arrived; play the remaining steps quickly, then load it.
      return { ...state, processing: { ...state.processing, finishing: true, perStep: action.perStep } };

    case "PLAN_LOADED": {
      const reviews = action.plan.reviews || {};
      return {
        ...initialState,
        view: "results",
        plan: applyReviews(action.plan, reviews),
        reviews,
        hasPdf: action.hasPdf,
      };
    }

    case "UPLOAD_FAILED":
      return { ...state, view: "upload", processing: null, uploadError: action.error };

    case "RESET": // "New protocol"
      return initialState;

    case "FLAGGED_ONLY":
      return { ...state, flaggedOnly: action.value };

    case "REVIEW_OPENED": {
      const queue = flaggedKeys(state.plan);
      if (!queue.length) return state;
      const qi = action.key ? queue.indexOf(action.key) : nextOpen(queue, state.reviews, 0);
      return { ...state, view: "review", queue, qi };
    }

    case "REVIEW_MOVED":
      if (action.index < 0 || action.index >= state.queue.length) return state;
      return { ...state, qi: action.index };

    case "DECIDED": {
      const k = state.queue[state.qi];
      const reviews = { ...state.reviews, [k]: action.decision };
      // An edit is applied to the working plan; the original values stay in
      // the decision so it can be undone and shown as "Was: ...".
      const plan = action.decision.status === "edited" ? withItemValues(state.plan, k, action.decision.values) : state.plan;
      return { ...state, plan, reviews, qi: nextOpen(state.queue, reviews, state.qi) };
    }

    case "UNDONE": {
      const k = state.queue[state.qi];
      const r = state.reviews[k];
      if (!r) return state;
      const { [k]: _removed, ...reviews } = state.reviews;
      const { [k]: _alsoRemoved, ...unsaved } = state.unsaved;
      const plan = r.status === "edited" ? withItemValues(state.plan, k, r.original) : state.plan;
      return { ...state, plan, reviews, unsaved };
    }

    case "SAVE_FAILED":
      return { ...state, unsaved: { ...state.unsaved, [action.key]: true } };

    case "SAVE_SUCCEEDED": {
      const { [action.key]: _removed, ...unsaved } = state.unsaved;
      return { ...state, unsaved };
    }

    case "BACK_TO_PLAN": {
      const k = state.queue[state.qi];
      return { ...state, view: "results", scrollTo: k ? keyParts(state.plan, k).sec : null };
    }

    case "SCROLLED":
      return { ...state, scrollTo: null };

    default:
      return state;
  }
}
