# CORA: Clinical Operations Research Assistant

## Backend

### Local setup

The frontend sends uploaded protocol PDFs to a FastAPI backend at
`http://localhost:8000` by default.

To run the current local demo, start the backend in a separate terminal:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

You can verify the backend is running by visiting `http://localhost:8000/health`.

The frontend can then be started in a second terminal.

## Frontend

Plain HTML/CSS/JS, no build step.

### Run it

```bash
cd cora-frontend && python3 -m http.server 5173
```

Then open http://localhost:5173. Click **Try a sample protocol** to see the results view with fictional data, then **Download PDF** for the exported plan.

The backend URL defaults to `http://localhost:8000`. Point it somewhere else with `?api=https://your-app.onrender.com`, or edit `config.js`.

### What the backend needs to provide

| Method | Path | Returns |
| --- | --- | --- |
| `POST` | `/api/protocols` | multipart form with field `file` (the PDF) → plan JSON below |

The PDF export is built in the browser (`pdf-export.js`, using jsPDF), so the backend only has to return JSON.

FastAPI will need CORS enabled for the frontend origin (`CORSMiddleware`).

### Plan JSON

`sample-data.js` is the full reference example. Shape:

```jsonc
{
  "id": "abc123",
  "protocol": { "title", "short_title", "registry_id", "phase", "sponsor",
                "therapeutic_area", "design", "enrollment", "duration", "pages" },
  "visits":     [{ "id": "V1", "name", "day", "window", "type": "Clinic|Phone" }],
  "procedures": [{ "name", "category", "visits": ["V1","V2"], "notes", "source_page", "confidence" }],
  "staffing":   [{ "role", "fte", "responsibilities", "confidence" }],
  "safety":     [{ "event", "timeline", "recipient", "method", "notes", "source_page", "confidence" }],
  "billing":    [{ "item", "designation": "Sponsor|Standard of care|...", "visits", "notes", "confidence" }],
  "equipment":  [{ "item", "purpose", "confidence" }],
  "pharmacy":   { "involved": true, "items": [{ "item", "notes", "confidence" }] },
  "technology": [{ "system", "purpose", "notes", "confidence" }]
}
```

- `confidence` is 0–1. Anything under `reviewThreshold` (0.7, in `config.js`) is flagged for human review.
- `notes` is where the backend explains why something is uncertain. It shows up under the item.
- `source_page` is optional but lets reviewers check the item against the PDF.

### Files

- `index.html`: the three views (upload, processing, results)
- `app.js`: upload handling, rendering, review state
- `pdf-export.js`: builds the downloadable PDF plan (tables, review highlights, sign-off block)
- `styles.css`: light/dark themes, responsive layout, print styles
- `sample-data.js`: fictional sample output (not a real protocol)
- `config.js`: API base URL and review threshold