import { useRef, useState } from "react";

import { MAX_UPLOAD_BYTES } from "../config.js";

// Checked in the browser so an obviously wrong file never leaves the machine.
// Returns an error message, or null if the file may be uploaded.
export function validateFile(file) {
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
    return "That doesn't look like a PDF. Protocols need to be uploaded as .pdf files.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "That file is over 50 MB. Try a smaller protocol or split the appendices out.";
  }
  return null;
}

export function errorText(error, apiBase) {
  if (error.kind === "validation") return error.message;
  if (error.kind === "unreachable") return `Couldn't reach the backend at ${apiBase}. Is the FastAPI server running?`;
  if (error.kind === "timeout") {
    return `CORA stopped waiting for the server. ${error.message} The server may be busy or the protocol very long. Try again, or upload a shorter file.`;
  }
  return `Processing failed. ${error.message}`;
}

export default function UploadView({ error, apiBase, onFile, onSample }) {
  const input = useRef(null);
  const [drag, setDrag] = useState(false);

  const stop = (e, dragging) => {
    e.preventDefault();
    setDrag(dragging);
  };

  return (
    <section id="uploadView" className="view">
      <div className="hero">
        <h1>Turn a protocol into an operational plan</h1>
        <p>
          Upload a clinical research protocol PDF. The assistant pulls out the visit schedule, procedures, staffing,
          safety reporting, billing triggers and resource needs, then shows a draft for you to review.
        </p>
      </div>

      <label
        id="dropzone"
        className={`dropzone${drag ? " drag" : ""}`}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            input.current.click();
          }
        }}
        onDragEnter={(e) => stop(e, true)}
        onDragOver={(e) => stop(e, true)}
        onDragLeave={(e) => stop(e, false)}
        onDrop={(e) => {
          stop(e, false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
      >
        <input
          ref={input}
          id="fileInput"
          type="file"
          accept="application/pdf,.pdf"
          hidden
          aria-label="Protocol PDF"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
            e.target.value = ""; // so choosing the same file again fires onChange
          }}
        />
        <svg viewBox="0 0 24 24" className="dz-icon" aria-hidden="true">
          <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <strong>Drop a protocol PDF here</strong>
        <span>or click to browse (PDF, up to 50 MB)</span>
      </label>

      <div className="upload-actions">
        <button id="sampleBtn" className="btn btn-secondary" onClick={onSample}>
          Try a sample protocol
        </button>
      </div>

      <p className="privacy-note">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        </svg>
        <span>
          <strong>Public protocols only.</strong> Upload only publicly available protocols (for example from
          ClinicalTrials.gov). Do not upload confidential institutional or sponsor documents, or anything containing
          patient information. CORA never keeps the PDF or its text. The extracted plan and your review decisions may
          be saved so the same protocol opens instantly next time.
        </span>
      </p>

      {error && (
        <div id="uploadError" className="alert" role="alert">
          {errorText(error, apiBase)}{" "}
          <button className="link-btn" onClick={onSample}>
            View sample output instead
          </button>
        </div>
      )}
    </section>
  );
}
