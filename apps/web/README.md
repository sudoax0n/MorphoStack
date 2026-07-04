# MorphoStack Web

Local browser UI for the MorphoStack FastAPI backend.

## Development

Start the backend from the repository root:

```bash
.\.venv\Scripts\morphostack serve
```

Start the frontend from this folder:

```bash
npm install
npm run dev
```

Vite proxies `/api/*` requests to `http://127.0.0.1:8000`.

The UI supports direct TIFF/CZI uploads for normal local use. The path input is
kept as a developer fallback when the backend can access a file directly.
