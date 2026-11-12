// App settings. Values come from Vite env variables (see .env.example).

// Items with confidence below this are flagged for human review.
// The backend uses the same number (REVIEW_THRESHOLD in llm_extractor.py).
export const REVIEW_THRESHOLD = 0.7;

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // matches the backend limit

// Read on each call (not once at import) so ?api= works and tests can change it.
export function apiBase() {
  const fromUrl = new URLSearchParams(window.location.search).get("api");
  return (fromUrl || import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/+$/, "");
}

export function uploadTimeoutMs() {
  return Number(import.meta.env.VITE_UPLOAD_TIMEOUT_MS) || 130_000;
}

// Durations of the processing animation, in ms. An object so tests can set
// them to 0 instead of waiting.
export const timing = {
  step: 1400,       // cosmetic advance while waiting for the backend
  finishStep: 250,  // quick run through the remaining steps once the plan is back
  sampleStep: 900,  // sample mode has no backend, so it just plays the steps
  finishPause: 300,
  toast: 3500,
};
