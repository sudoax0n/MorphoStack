/**
 * Display-only mesh iframe preview (Packet 07).
 *
 * Local Plotly asset, visible failure, physical aspect fit.
 * Does not change scientific mesh export / SA / volume authority.
 */

export const PLOTLY_VENDOR_VERSION = "2.35.2";
export const PLOTLY_VENDOR_PATH = `/vendor/plotly-${PLOTLY_VENDOR_VERSION}.min.js`;
export const MESH_PREVIEW_MESSAGE_TYPE = "morphostack-mesh-preview";

export type MeshBounds = {
  xmin: number;
  ymin: number;
  zmin: number;
  xmax: number;
  ymax: number;
  zmax: number;
};

export type MeshCamera = {
  eye: { x: number; y: number; z: number };
  center: { x: number; y: number; z: number };
  up: { x: number; y: number; z: number };
};

export type MeshPreviewPayloadLike = {
  vertices: number[][];
  faces: number[][];
  source_path: string;
  surface_area_um2: number;
  volume_um3: number;
};

export type MeshPreviewMessage =
  | {
      type: typeof MESH_PREVIEW_MESSAGE_TYPE;
      status: "ok";
      plot_ms: number;
      parse_ms?: number;
      vertex_count: number;
      face_count: number;
    }
  | {
      type: typeof MESH_PREVIEW_MESSAGE_TYPE;
      status: "error";
      message: string;
      stage: string;
    };

/** Same-origin URL for the vendored Plotly build (srcdoc must use absolute URL). */
export function plotlyScriptUrl(
  origin: string = typeof location !== "undefined" ? location.origin : ""
): string {
  const base = String(origin || "").replace(/\/$/, "");
  if (!base) {
    // Offline HTML download fallback: relative path only works under the served app.
    return PLOTLY_VENDOR_PATH;
  }
  return `${base}${PLOTLY_VENDOR_PATH}`;
}

export function meshBounds(vertices: number[][]): MeshBounds {
  let xmin = Number.POSITIVE_INFINITY;
  let ymin = Number.POSITIVE_INFINITY;
  let zmin = Number.POSITIVE_INFINITY;
  let xmax = Number.NEGATIVE_INFINITY;
  let ymax = Number.NEGATIVE_INFINITY;
  let zmax = Number.NEGATIVE_INFINITY;
  for (const vertex of vertices) {
    const x = Number(vertex[0]);
    const y = Number(vertex[1]);
    const z = Number(vertex[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      continue;
    }
    if (x < xmin) xmin = x;
    if (y < ymin) ymin = y;
    if (z < zmin) zmin = z;
    if (x > xmax) xmax = x;
    if (y > ymax) ymax = y;
    if (z > zmax) zmax = z;
  }
  if (!Number.isFinite(xmin)) {
    return { xmin: 0, ymin: 0, zmin: 0, xmax: 1, ymax: 1, zmax: 1 };
  }
  return { xmin, ymin, zmin, xmax, ymax, zmax };
}

/** Physical extents after origin shift to min corner (µm). */
export function meshExtentsUm(bounds: MeshBounds): { dx: number; dy: number; dz: number } {
  return {
    dx: Math.max(1e-9, bounds.xmax - bounds.xmin),
    dy: Math.max(1e-9, bounds.ymax - bounds.ymin),
    dz: Math.max(1e-9, bounds.zmax - bounds.zmin)
  };
}

/**
 * Bounds-derived camera so the full physical AABB is in view (origin-shifted box).
 */
export function meshCameraFromExtents(dx: number, dy: number, dz: number): MeshCamera {
  const cx = dx * 0.5;
  const cy = dy * 0.5;
  const cz = dz * 0.5;
  const r = Math.max(dx, dy, dz) * 1.85;
  return {
    eye: { x: cx + r * 0.72, y: cy + r * 0.72, z: cz + r * 0.55 },
    center: { x: cx, y: cy, z: cz },
    up: { x: 0, y: 0, z: 1 }
  };
}

export function meshPresetCameras(
  dx: number,
  dy: number,
  dz: number
): Record<string, MeshCamera> {
  const cx = dx * 0.5;
  const cy = dy * 0.5;
  const cz = dz * 0.5;
  const r = Math.max(dx, dy, dz) * 2.1;
  const iso = meshCameraFromExtents(dx, dy, dz);
  return {
    iso,
    front: {
      eye: { x: cx, y: cy + r, z: cz },
      center: { x: cx, y: cy, z: cz },
      up: { x: 0, y: 0, z: 1 }
    },
    side: {
      eye: { x: cx + r, y: cy, z: cz },
      center: { x: cx, y: cy, z: cz },
      up: { x: 0, y: 0, z: 1 }
    },
    top: {
      eye: { x: cx, y: cy, z: cz + r },
      center: { x: cx, y: cy, z: cz },
      up: { x: 0, y: 1, z: 0 }
    }
  };
}

function escapeHtml(value: string): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) {
    return value.toExponential(4);
  }
  return value.toFixed(4).replace(/\.?0+$/, "") || "0";
}

export type MeshPreviewHtmlOptions = {
  plotlyUrl?: string;
  formatNumber?: (n: number) => string;
  escapeHtml?: (s: string) => string;
};

/**
 * Build iframe srcdoc HTML for display mesh preview.
 * Failures postMessage to parent and paint a visible error in #plot.
 */
export function meshPreviewHtml(
  payload: MeshPreviewPayloadLike,
  options: MeshPreviewHtmlOptions = {}
): string {
  const esc = options.escapeHtml ?? escapeHtml;
  const fmt = options.formatNumber ?? formatNumber;
  const bounds = meshBounds(payload.vertices);
  const extents = meshExtentsUm(bounds);
  const camera = meshCameraFromExtents(extents.dx, extents.dy, extents.dz);
  const cameras = meshPresetCameras(extents.dx, extents.dy, extents.dz);
  const x = payload.vertices.map((vertex) => vertex[0] - bounds.xmin);
  const y = payload.vertices.map((vertex) => vertex[1] - bounds.ymin);
  const z = payload.vertices.map((vertex) => vertex[2] - bounds.zmin);
  const i = payload.faces.map((face) => face[0]);
  const j = payload.faces.map((face) => face[1]);
  const k = payload.faces.map((face) => face[2]);
  const title = payload.source_path.split(/[\\/]/).pop() ?? "MorphoStack mesh";
  const plotlyUrl = options.plotlyUrl ?? plotlyScriptUrl();
  const vertexCount = payload.vertices.length;
  const faceCount = payload.faces.length;

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${esc(title)} — MorphoStack mesh</title>
  <style>
    html, body { width: 100%; height: 100%; margin: 0; background: #0f172a; color: #e5e7eb; font-family: system-ui, sans-serif; }
    #toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 8px 10px; background: #111827; border-bottom: 1px solid rgba(255,255,255,0.08); }
    #toolbar button, #toolbar label { font-size: 12px; }
    #toolbar button { background: #1f2937; color: #e5e7eb; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 4px 8px; cursor: pointer; }
    #toolbar button:hover { background: #374151; }
    #toolbar input[type="range"] { width: 120px; vertical-align: middle; }
    #plot { width: 100%; height: calc(100% - 44px); box-sizing: border-box; }
    .meta { font-size: 11px; color: #9ca3af; margin-left: auto; }
    #status { font-size: 11px; color: #93c5fd; margin-left: 8px; }
    #status.is-error { color: #fca5a5; font-weight: 600; }
    .mesh-error {
      display: grid; place-items: center; height: 100%; padding: 24px; text-align: center;
      color: #fecaca; background: #1c1917; border: 1px solid #7f1d1d; box-sizing: border-box;
      font-size: 14px; line-height: 1.5;
    }
    .mesh-error code { display: block; margin-top: 8px; font-size: 12px; color: #fde68a; word-break: break-word; }
  </style>
  <script src="${esc(plotlyUrl)}"></script>
</head>
<body>
  <div id="toolbar">
    <button type="button" data-camera="iso">Iso</button>
    <button type="button" data-camera="front">Front</button>
    <button type="button" data-camera="side">Side</button>
    <button type="button" data-camera="top">Top</button>
    <label>Opacity <input id="opacity-range" type="range" min="0.2" max="1" step="0.05" value="0.88" /></label>
    <button id="download-png-btn" type="button">Download PNG</button>
    <span class="meta">Display preview · scientific SA ${fmt(payload.surface_area_um2)} um2 · V ${fmt(payload.volume_um3)} um3 (complete mesh)</span>
    <span id="status">loading Plotly…</span>
  </div>
  <div id="plot"></div>
  <script>
    const MSG = ${JSON.stringify(MESH_PREVIEW_MESSAGE_TYPE)};
    const VERTEX_COUNT = ${vertexCount};
    const FACE_COUNT = ${faceCount};
    const statusEl = document.getElementById("status");
    const plotEl = document.getElementById("plot");
    const tParse0 = performance.now();

    function postParent(payload) {
      try {
        if (window.parent && window.parent !== window) {
          window.parent.postMessage(payload, "*");
        }
      } catch (err) {
        console.error("mesh preview postMessage failed", err);
      }
    }

    function showError(stage, message) {
      const text = String(message || "Unknown mesh preview error");
      console.error("[MorphoStack mesh preview]", stage, text);
      if (statusEl) {
        statusEl.textContent = "error";
        statusEl.classList.add("is-error");
      }
      if (plotEl) {
        plotEl.innerHTML = '<div class="mesh-error"><strong>3D mesh preview failed</strong><div>' +
          stage + '</div><code>' + text.replace(/</g, "&lt;") + '</code>' +
          '<div style="margin-top:10px;color:#cbd5e1;font-size:12px">Display-only preview. Scientific SA/volume on the parent panel are unchanged.</div></div>';
      }
      postParent({ type: MSG, status: "error", message: text, stage: String(stage) });
    }

    function setStatus(text, isError) {
      if (!statusEl) return;
      statusEl.textContent = text;
      statusEl.classList.toggle("is-error", !!isError);
    }

    if (typeof Plotly === "undefined") {
      showError(
        "plotly_load",
        "Plotly failed to load from the local asset (" + ${JSON.stringify(plotlyUrl)} + "). Check offline/network and that /vendor/plotly is served."
      );
    } else {
      const parse_ms = performance.now() - tParse0;
      const trace = {
        type: "mesh3d",
        x: ${JSON.stringify(x)},
        y: ${JSON.stringify(y)},
        z: ${JSON.stringify(z)},
        i: ${JSON.stringify(i)},
        j: ${JSON.stringify(j)},
        k: ${JSON.stringify(k)},
        color: "#38bdf8",
        opacity: 0.88,
        flatshading: true
      };
      const defaultCamera = ${JSON.stringify(camera)};
      const cameras = ${JSON.stringify(cameras)};
      const layout = {
        margin: { l: 0, r: 0, t: 0, b: 0 },
        paper_bgcolor: "#0f172a",
        plot_bgcolor: "#0f172a",
        font: { color: "#e5e7eb" },
        scene: {
          aspectmode: "data",
          camera: defaultCamera,
          xaxis: { title: "X (um)", nticks: 4, color: "#e5e7eb", gridcolor: "rgba(255,255,255,0.18)", backgroundcolor: "#111827" },
          yaxis: { title: "Y (um)", nticks: 4, color: "#e5e7eb", gridcolor: "rgba(255,255,255,0.18)", backgroundcolor: "#111827" },
          zaxis: { title: "Z (um)", nticks: 4, color: "#e5e7eb", gridcolor: "rgba(255,255,255,0.18)", backgroundcolor: "#111827" }
        }
      };
      const tPlot0 = performance.now();
      setStatus("plotting…");
      Promise.resolve(Plotly.newPlot("plot", [trace], layout, { responsive: true, displaylogo: false }))
        .then(function () {
          try {
            if (Plotly.Plots && typeof Plotly.Plots.resize === "function") {
              Plotly.Plots.resize("plot");
            }
          } catch (resizeErr) {
            console.warn("mesh preview resize", resizeErr);
          }
          const plot_ms = performance.now() - tPlot0;
          setStatus("ready · " + plot_ms.toFixed(0) + " ms");
          postParent({
            type: MSG,
            status: "ok",
            plot_ms: plot_ms,
            parse_ms: parse_ms,
            vertex_count: VERTEX_COUNT,
            face_count: FACE_COUNT
          });
        })
        .catch(function (err) {
          showError("newPlot", err && err.message ? err.message : String(err));
        });

      window.addEventListener("message",function(e){if(e.data&&e.data.type==="morphostack-mesh-resize"&&Plotly.Plots)Plotly.Plots.resize("plot")});
      document.querySelectorAll("[data-camera]").forEach(function (button) {
        button.addEventListener("click", function () {
          const key = button.getAttribute("data-camera");
          if (!key || !cameras[key]) return;
          Plotly.relayout("plot", { "scene.camera": cameras[key] }).catch(function (err) {
            showError("relayout", err && err.message ? err.message : String(err));
          });
        });
      });
      document.getElementById("opacity-range").addEventListener("input", function (event) {
        const value = Number(event.target.value);
        Plotly.restyle("plot", { opacity: value }).catch(function (err) {
          showError("restyle", err && err.message ? err.message : String(err));
        });
      });
      document.getElementById("download-png-btn").addEventListener("click", async function () {
        try {
          const dataUrl = await Plotly.toImage("plot", { format: "png", width: 1400, height: 900, scale: 2 });
          const anchor = document.createElement("a");
          anchor.href = dataUrl;
          anchor.download = "morphostack-mesh.png";
          document.body.append(anchor);
          anchor.click();
          anchor.remove();
        } catch (err) {
          showError("toImage", err && err.message ? err.message : String(err));
        }
      });
    }
  </script>
</body>
</html>`;
}

export function isMeshPreviewMessage(data: unknown): data is MeshPreviewMessage {
  if (!data || typeof data !== "object") return false;
  const d = data as Record<string, unknown>;
  return d.type === MESH_PREVIEW_MESSAGE_TYPE && (d.status === "ok" || d.status === "error");
}
