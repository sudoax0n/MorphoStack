# MorphoStack Web

Local browser UI for the MorphoStack FastAPI backend.

## Development

From the repository root, the easiest development command is:

```bash
.\.venv\Scripts\morphostack dev
```

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
Set `MORPHOSTACK_API_TARGET` to point Vite at a different backend.

The UI supports direct TIFF/CZI uploads for normal local use. The path input is
kept as a developer fallback when the backend can access a file directly.
