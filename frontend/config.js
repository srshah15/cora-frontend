// Where the FastAPI backend lives. Override with ?api=http://host:port in the URL.
window.APP_CONFIG = {
  apiBase: new URLSearchParams(location.search).get("api") || "http://localhost:8000",
  // Items with confidence below this are flagged for human review.
  reviewThreshold: 0.7,
};
