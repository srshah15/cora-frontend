// Who is reviewing: a display name plus a random id this browser made once.
// The id only keeps reviewers' saved decisions apart. It is NOT a login:
// anyone who copies the id could act as that reviewer.

const NAME_KEY = "cora.reviewer";
const ID_KEY = "cora.reviewerId";

const read = (key) => {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
};
const write = (key, value) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
};

export const getReviewerName = () => read(NAME_KEY);
export const setReviewerName = (name) => write(NAME_KEY, name.trim());

let memoryId = ""; // fallback when localStorage is unavailable

export function getReviewerId() {
  let id = read(ID_KEY) || memoryId;
  if (!id) {
    id = crypto.randomUUID();
    memoryId = id;
    write(ID_KEY, id);
  }
  return id;
}

export function reviewerHeaders() {
  const headers = { "X-Reviewer-Id": getReviewerId() };
  const name = getReviewerName();
  // Header values must be ASCII, so the name is URL-encoded (the backend decodes it).
  if (name) headers["X-Reviewer-Name"] = encodeURIComponent(name);
  return headers;
}
