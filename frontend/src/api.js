// Every call to the backend goes through this file.

import { apiBase, uploadTimeoutMs } from "./config.js";
import { reviewerHeaders } from "./lib/reviewer.js";

// kind: "unreachable" (no response at all), "timeout" (we gave up waiting),
// or "server" (the backend answered with an error and a message).
export class ApiError extends Error {
  constructor(kind, message, status) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

async function errorFrom(res) {
  const text = await res.text().catch(() => "");
  let detail = text;
  try {
    detail = JSON.parse(text).detail || text;
  } catch {
    /* not JSON; show the text */
  }
  if (typeof detail !== "string") detail = JSON.stringify(detail);
  return new ApiError("server", detail ? detail.slice(0, 200) : `Server returned ${res.status}`, res.status);
}

export async function uploadProtocol(file, { timeoutMs = uploadTimeoutMs() } = {}) {
  const body = new FormData();
  body.append("file", file);

  // fetch has no timeout of its own: without this the processing screen could
  // spin forever. AbortController lets us cancel the request after a limit.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${apiBase()}/api/protocols`, {
      method: "POST",
      body,
      headers: reviewerHeaders(),
      signal: controller.signal,
    });
  } catch (err) {
    if (controller.signal.aborted) {
      throw new ApiError("timeout", `No answer after ${Math.round(timeoutMs / 1000)} seconds.`);
    }
    throw new ApiError("unreachable", err?.message || "Network error");
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

async function send(method, path, json) {
  let res;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      method,
      headers: { ...reviewerHeaders(), ...(json ? { "Content-Type": "application/json" } : {}) },
      body: json ? JSON.stringify(json) : undefined,
    });
  } catch (err) {
    throw new ApiError("unreachable", err?.message || "Network error");
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

export const saveReview = (planId, key, decision) =>
  send("PUT", `/api/plans/${planId}/reviews/${encodeURIComponent(key)}`, decision).then((r) => r.json());

export const deleteReview = (planId, key) =>
  send("DELETE", `/api/plans/${planId}/reviews/${encodeURIComponent(key)}`).then((r) => r.json());

// Returns { blob, filename } for the Word export built by the backend.
export async function exportDocx({ plan, reviews, reviewer, sectionOrder }) {
  const res = await send("POST", "/api/export/docx", {
    plan,
    reviews,
    reviewer: reviewer || null,
    section_order: sectionOrder?.length ? sectionOrder : null,
  });
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
  return { blob: await res.blob(), filename: match?.[1] || "operational-plan.docx" };
}
