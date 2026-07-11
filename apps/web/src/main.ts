import "./styles.css";
import {
  ProvisionalPreviewScheduler,
  shouldApplyPreview as shouldApplyPreviewGate,
  claimBusyOwner,
  releaseBusyOwner,
  busyAfterProvisional,
  busyVisibleForLatest,
  trackingBusyMessage,
  type BusyOwner,
  type PreviewQuality as QueuePreviewQuality,
  type TrackingJobBusyInfo
} from "./previewQueue";
import {
  DEFAULT_VOLUME_MAX_BYTES,
  NAVIGATION_ONLY_LABEL,
  SeedMappingError,
  VolumeViewerError,
  VolumeViewerSession,
  fallbackMessage,
  geometryFromLevelPayload,
  isVolumeViewerEnabled,
  objectSeedToWorld,
  setVolumeViewerEnabled,
  waitForPyramidLevelReady,
  worldExtentUm,
  worldToObjectSeed,
  type DisplayLevelResponse,
  type VolumeBlendMode,
  type VolumeFallbackReason,
  type WorldPointUm
} from "./volumeViewer";

/** Shown as path-input placeholder; never treat as a real stack path. */
const PATH_PLACEHOLDER = "D:\\lab-data\\sample.tif";
/** Warn when multipart-uploading stacks at or above this size. */
const LARGE_UPLOAD_WARN_BYTES = 50 * 1024 * 1024;
/** Debounce for provisional (fast) auto-preview after frame/threshold/ROI changes. */
const PREVIEW_DEBOUNCE_MS = 150;
/** Extra settle time before launching authoritative seeded tracking preview. */
const EXACT_PREVIEW_DEBOUNCE_MS = 280;
/** Min client-space drag (px) to accept a Fiji-style circle ROI. Click-only is rejected. */
const MIN_CIRCLE_DRAG_CLIENT_PX = 14;

type VoxelOverride = {
  x_um: number;
  y_um: number;
  z_um: number;
};

type AnalysisProfile = "vesicle" | "rbc" | "active_surfaces";

type RectRoi = {
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
};

type ObjectSeed = {
  x: number;
  y: number;
  frame_index: number;
  radius: number;
  max_tracking_dist_um?: number;
  type?: string;
  points?: { x: number; y: number }[];
  /** Packet 13 provenance — not a tracking-key field. */
  source_revision?: string | null;
  seed_origin?: "ui_2d" | "viewer_3d";
  radius_unit?: "px";
};

type InspectResponse = {
  source_path: string;
  grayscale_shape: number[];
  color_shape: number[];
  voxel_size: VoxelOverride;
  voxel_source: string;
  /** Present after file-mode inspect/session open (server-side upload cache). */
  stack_id?: string;
};

type SessionOpenResponse = {
  stack_id: string;
  source_path: string;
  grayscale_shape: number[];
  color_shape: number[];
  voxel_size: VoxelOverride;
  voxel_source: string;
};

type AnalysisRow = {
  frame_index: number;
  threshold: number;
  profile: AnalysisProfile;
  method: string;
  excluded?: boolean;
  has_contour: boolean;
  area_px2: number;
  perimeter_px: number;
  area_um2: number;
  perimeter_um: number;
  circularity: number;
  bbox_width_um: number;
  bbox_height_um: number;
  aspect_ratio: number;
  elongation: number;
  deformation_index: number;
  extent: number;
  equivalent_diameter_um: number;
  solidity: number;
  mesh_surface_area_um2: number;
  mesh_volume_um3: number;
  mesh_equivalent_sphere_diameter_um: number;
  mesh_sphericity: number;
  skel_perimeter_um?: number;
  skel_perimeter_px?: number;
};

type TrackingRecord = {
  frame_index: number;
  tracked: boolean;
  centroid_x: number | null;
  centroid_y: number | null;
  area_px: number;
  touches_roi_boundary: boolean;
  likely_neighbor_merge: boolean;
  /** Additive reason fields (optional for older API payloads). */
  loss_reason?: string | null;
  merge_suspect?: boolean;
  merge_rejected?: boolean;
  touches_seed_disk?: boolean;
  method?: string | null;
};

type AnalyzeResponse = {
  source_path: string;
  profile: AnalysisProfile;
  frame_count: number;
  valid_frame_count: number;
  excluded_frames?: number[];
  voxel_size: VoxelOverride;
  voxel_source: string;
  object_seed: ObjectSeed | null;
  tracking: TrackingRecord[] | null;
  mesh: null | {
    surface_area_um2: number;
    volume_um3: number;
    equivalent_sphere_diameter_um: number;
    sphericity: number;
  };
  slice_volume: null | {
    method: string;
    volume_um3: number | null;
    partial_volume_um3: number;
    relative_difference_from_mesh: number | null;
    sampled_slice_count: number;
    internal_missing_slice_indices: number[];
    coverage_fraction: number;
    z_step_um: number;
    has_internal_gaps: boolean;
    has_observed_start_cap: boolean;
    has_observed_end_cap: boolean;
    touches_stack_boundary: boolean;
  };
  summary: AnalysisSummary;
  warnings: AnalysisWarning[];
  manifest: Record<string, unknown>;
  rows: AnalysisRow[];
};

type MetricSummary = {
  mean: number;
  min: number;
  max: number;
  std: number;
};

type AnalysisSummary = {
  frame_count: number;
  valid_frame_count: number;
  valid_fraction: number;
  metrics: Record<string, MetricSummary>;
};

type AnalysisWarning = {
  code: string;
  severity: string;
  message: string;
};

type PreviewQuality = QueuePreviewQuality;

type PreviewResponse = {
  source_path: string;
  frame_index: number;
  frame?: number;
  width: number;
  height: number;
  threshold: number | null;
  requested_threshold?: number | null;
  effective_threshold?: number | null;
  threshold_semantics?: string;
  threshold_contract_version?: string;
  method: string;
  area_px2: number;
  perimeter_px: number;
  circularity: number;
  image_url?: string;
  image_png_base64?: string;
  skel_perimeter_um?: number;
  skel_perimeter_px?: number;
  /** provisional = fast one-plane overlay; exact = tracked / authoritative. */
  preview_quality?: PreviewQuality;
  cache_hit?: boolean;
  source_revision?: string;
  tracking_revision?: string | null;
  /**
   * Exact seeded track center in preview-image coordinates (post ROI/Z crop),
   * same frame as the contour. Null when provisional, lost, or untracked.
   * Never substitute the immutable user seed here.
   */
  tracked_center_x?: number | null;
  tracked_center_y?: number | null;
  /** Packet 04: target frame published in exact result cache. */
  exact_available?: boolean;
  exact_pending?: boolean;
  tracking_job?: (TrackingJobBusyInfo & { job_id?: string }) | null;
};

type MeshPreviewResponse = {
  source_path: string;
  has_mesh: boolean;
  downsample: number;
  vertex_count: number;
  face_count: number;
  vertices: number[][];
  faces: number[][];
  surface_area_um2: number;
  volume_um3: number;
  equivalent_sphere_diameter_um: number;
  sphericity: number;
  /** Packet 14: preview geometry is display-only (weld/compact). */
  display_only?: boolean;
  display_method?: string;
  source_vertex_count?: number | null;
  source_face_count?: number | null;
  boundary_edge_count_source?: number | null;
  boundary_edge_count_display?: number | null;
  within_face_budget?: boolean | null;
  result_authority?: {
    geometry_role?: string;
    display_only?: boolean;
    display_method?: string;
    measurement_source?: string;
    measurement_authority_note?: string;
  };
};

type ThresholdResponse = {
  source_path: string;
  source_revision?: string;
  threshold: number;
  method: string;
  threshold_semantics?: string;
  suggestion_scope?: string;
  histogram_domain?: {
    frame?: number | null;
    z_range?: { zmin: number; zmax: number } | null;
    roi?: unknown;
    n_voxels_total?: number;
    n_samples?: number;
    sample_seed?: number;
    dtype?: string;
    finite_only?: boolean;
  };
  authoritative_for?: string[];
  not_authoritative_for?: string[];
  warnings?: string[];
  threshold_contract_version?: string;
};

type BatchSummaryRow = Record<string, string | number | boolean>;

type BatchAnalyzeResponse = {
  file_count: number;
  succeeded_count: number;
  failed_count: number;
  columns: string[];
  rows: BatchSummaryRow[];
};

type SweepSummaryRow = Record<string, string | number | boolean>;

type SweepResponse = {
  source_path: string;
  profile: AnalysisProfile;
  voxel_source: string;
  threshold_count: number;
  best_threshold: number | null;
  columns: string[];
  rows: SweepSummaryRow[];
};

type ProjectSettings = {
  version: 1;
  profile?: AnalysisProfile;
  threshold?: number;
  voxel_size?: VoxelOverride;
  roi?: RectRoi;
  z_range?: {
    zmin: number;
    zmax: number;
  };
  include_mesh?: boolean;
  enable_skeleton?: boolean;
  skeleton_prune_pix?: number;
  prefer_opencv?: boolean;
  sweep?: {
    start?: number;
    stop?: number;
    step?: number;
  };
};

type ValidationDifference = {
  row_id: string;
  column: string;
  expected: string;
  actual: string;
  delta: number | null;
};

type ValidationResponse = {
  passed: boolean;
  expected_path: string;
  actual_path: string;
  tolerance: number;
  compared_rows: number;
  compared_cells: number;
  differences: ValidationDifference[];
};

const CSV_COLUMNS = [
  "frame_index",
  "threshold",
  "profile",
  "method",
  "has_contour",
  "area_px2",
  "perimeter_px",
  "area_um2",
  "perimeter_um",
  "circularity",
  "bbox_width_um",
  "bbox_height_um",
  "aspect_ratio",
  "elongation",
  "deformation_index",
  "extent",
  "equivalent_diameter_um",
  "solidity",
  "mesh_surface_area_um2",
  "mesh_volume_um3",
  "mesh_equivalent_sphere_diameter_um",
  "mesh_sphericity"
] as const;

type LogEntry = {
  timestamp: string;
  action: string;
  details?: string;
};

const frontendLogs: LogEntry[] = [];

function logAction(action: string, details?: string): void {
  const timestamp = new Date().toLocaleTimeString();
  frontendLogs.push({ timestamp, action, details });
  console.log(`[Frontend Log] ${timestamp} - ${action}`, details ?? "");
  updateLogBookUI();
}

function updateLogBookUI(): void {
  const body = document.getElementById("log-results-body");
  if (!body) return;
  if (frontendLogs.length === 0) {
    body.innerHTML = `<tr><td colspan="3" class="muted">No actions recorded yet.</td></tr>`;
    return;
  }
  body.innerHTML = frontendLogs
    .map(
      (log) => `
        <tr>
          <td>${escapeHtml(log.timestamp)}</td>
          <td><strong>${escapeHtml(log.action)}</strong></td>
          <td class="muted">${escapeHtml(log.details ?? "")}</td>
        </tr>
      `
    )
    .reverse()
    .join("");
}

function downloadLogs(): void {
  if (frontendLogs.length === 0) return;
  const json = JSON.stringify(frontendLogs, null, 2);
  const blob = new Blob([json], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "morphostack_ui_logs.json";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

const app = document.querySelector<HTMLDivElement>("#app");

if (!app) {
  throw new Error("Missing #app mount point");
}

app.innerHTML = `
  <header class="topbar">
    <div class="brand">
      <img class="brand-logo" src="/logo.png" width="40" height="40" alt="MorphoStack" />
      <div>
        <h1>MorphoStack</h1>
        <p>Local morphometry for microscopy Z-stacks</p>
      </div>
    </div>
    <div class="status" id="api-status">Checking API...</div>
  </header>

  <section class="project-strip">
    <label>
      Project
      <input id="project-file-input" type="file" accept=".json,application/json" />
    </label>
    <div class="button-row">
      <button id="load-project-btn" class="secondary" type="button">Load Project</button>
      <button id="download-project-btn" class="secondary" type="button">Download Project</button>
    </div>
    <div id="project-status" class="status">No project loaded</div>
  </section>

  <nav class="workflow-strip" aria-label="Prototype workflow">
    <span><strong>1</strong> Load stack</span>
    <span><strong>2</strong> Set voxel/Z/ROI</span>
    <span><strong>3</strong> Preview threshold</span>
    <span><strong>4</strong> Analyze</span>
    <span><strong>5</strong> Download outputs</span>
    <span><strong>6</strong> Log book</span>
  </nav>

  <main class="layout">
    <section class="panel" id="step-1-panel">
      <div class="panel-title">
        <h2><span class="step-badge">1</span> Stack</h2>
        <button id="inspect-btn" type="button">Inspect</button>
      </div>
      <label>
        Stack file
        <input id="file-input" type="file" accept=".tif,.tiff,.lsm,.czi,image/tiff" />
      </label>
      <label>
        Stack path (preferred for large stacks — no browser upload)
        <input id="path-input" type="text" placeholder="${PATH_PLACEHOLDER}" />
      </label>
      <p class="muted" style="margin: 0.35rem 0 0.6rem; font-size: 0.9rem;">
        If both a file and a path are set, the local path is used (no upload). Paste the full path for large CZI/LSM stacks when the API can read the disk.
      </p>
      <div id="session-banner" class="session-banner" hidden>
        <strong>File mode:</strong> first Inspect loads the stack once into server memory.
        Later Preview / Mesh / Analyze use that session and should <em>not</em> re-upload.
        Path mode is still faster for huge CZIs (server reads the file directly).
      </div>
      <p id="session-status" class="session-status muted" hidden></p>
      <h3>Calibration</h3>
      <label style="margin-bottom: 0.5rem; display: block;">
        Calibration Mode
        <select id="calibration-mode" style="width: 100%; padding: 0.4rem; border-radius: 4px; border: 1px solid var(--border); background: var(--bg-input); color: var(--text);">
          <option value="auto" selected>Auto (from metadata)</option>
          <option value="manual">Manual override</option>
        </select>
      </label>
      <div class="grid">
        <label>
          Voxel X (um)
          <input id="voxel-x" type="number" min="0" step="0.0001" value="1" disabled />
        </label>
        <label>
          Voxel Y (um)
          <input id="voxel-y" type="number" min="0" step="0.0001" value="1" disabled />
        </label>
        <label>
          Voxel Z (um)
          <input id="voxel-z" type="number" min="0" step="0.0001" value="1" disabled />
        </label>
      </div>
      <p id="calibration-help" class="calibration-help muted">
        Auto mode reads voxel spacing from TIFF/LSM/CZI metadata when available. Default 1×1×1 µm is a placeholder — do not trust surface area or volume until calibration is verified.
      </p>
      <div id="inspect-output" class="output muted">No stack inspected yet.</div>
    </section>

    <section class="panel" id="step-2-panel">
      <div class="panel-title">
        <h2><span class="step-badge">2</span> Preview & Analyze</h2>
        <div class="button-row">
          <button id="preview-btn" class="secondary" type="button">Preview</button>
          <button id="mesh-preview-btn" class="secondary" type="button">View 3D Mesh</button>
          <button id="analyze-btn" type="button">Analyze</button>
        </div>
      </div>
      <div class="workflow-card">
        <strong>Simple workflow</strong>
        <ol class="workflow-steps">
          <li><b>Inspect</b> the stack (use Stack path for big CZIs)</li>
          <li><b>Pick your object</b> (Select Object on the preview)</li>
          <li>Set <b>threshold</b> until the membrane looks right → Preview</li>
          <li><b>Analyze</b> for CSV metrics · <b>View 3D Mesh</b> for shape</li>
        </ol>
        <p class="fieldset-hint muted" style="margin: 0;">
          Leave mode on <b>Standard</b> for threshold segmentation, single-object tracking, and mesh export.
        </p>
      </div>
      <div class="grid">
        <label class="wide">
          Mode
          <select id="profile-input">
            <option value="vesicle" selected>Standard — GUVs / vesicles (recommended)</option>
            <option value="rbc">Red blood cells (RBC)</option>
            <option value="active_surfaces">Experimental — slow 3D refine (only if Standard fails)</option>
          </select>
          <span id="profile-help" class="inline-status profile-help">
            Standard: select one object, set threshold, then Analyze or View 3D Mesh.
          </span>
        </label>
        <label>
          Threshold
          <input id="threshold-input" type="number" step="1" value="100" />
        </label>
        <label class="button-label">
          Starting guess
          <button id="suggest-threshold-btn" class="secondary" type="button">Suggest Threshold</button>
          <span id="suggest-status" class="inline-status"></span>
        </label>
        <label class="checkbox-row">
          <input id="mesh-input" type="checkbox" checked />
          Compute 3D surface area + volume in Analyze
        </label>
        <div class="skeleton-controls">
          <label class="checkbox-row">
            <input id="skeleton-input" type="checkbox" />
            Enable skeleton (better perimeter)
          </label>
          <label class="skeleton-prune-wrap" for="skeleton-prune-input">
            prune
            <input
              id="skeleton-prune-input"
              type="number"
              min="0"
              step="1"
              value="1"
              inputmode="numeric"
              title="Skeleton spur prune length (px)"
            />
            px
          </label>
        </div>
        <details class="advanced-details">
          <summary>Advanced options</summary>
          <label class="checkbox-row" style="margin-top: 0.5rem;">
            <input id="fallback-input" type="checkbox" />
            Use fallback contours (no OpenCV)
          </label>
          <label class="checkbox-row" style="margin-top: 0.5rem;">
            <input id="show-tracking-debug" type="checkbox" />
            Show tracked centroid after Analyze
          </label>
        </details>
      </div>
      <div id="profile-warning" class="profile-warning" hidden>
        Experimental mode is much slower (minutes on big stacks). You must Select Object first.
        Prefer Standard unless the membrane is too broken for threshold.
      </div>
      <fieldset>
        <legend>Pick this vesicle (recommended)</legend>
        <p class="fieldset-hint muted">
          Click <b>Select Object</b>, then <b>drag a circle</b> that encloses the vesicle (Fiji-style).
          Click-only is not enough — drag from center out to set the real radius.
          MorphoStack tracks that object through Z. Without this, it may grab the largest blob in view.
        </p>
        <div class="button-row fieldset-actions">
          <button id="select-object-btn" class="secondary" type="button">Select Object</button>
          <button id="clear-object-btn" class="secondary" type="button">Clear Object</button>
          <span id="object-seed-status" class="inline-status">No object selected</span>
        </div>
        <div class="grid three" style="margin-top: 10px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;">
          <label>
            Seed Tool
            <select id="object-seed-tool">
              <option value="circle" selected>Circle ROI (drag radius like Fiji)</option>
              <option value="polygon">Polygon (advanced)</option>
            </select>
          </label>
          <label id="seed-radius-container">
            Seed Radius (px)
            <input id="object-seed-radius" type="number" min="1" placeholder="Radius (px)" value="10" />
          </label>
          <label>
            Max Track Dist (um)
            <input id="object-seed-max-dist" type="number" min="0.1" step="0.1" placeholder="Auto" />
          </label>
        </div>
        <div class="overlay-toggles" style="margin-top: 10px; display: flex; flex-wrap: wrap; gap: 12px 16px;">
          <label class="checkbox-row">
            <input id="show-circle-roi-overlay" type="checkbox" checked />
            Show circle ROI
          </label>
          <label class="checkbox-row">
            <input id="show-xy-roi-overlay" type="checkbox" checked />
            Show XY crop box
          </label>
          <label class="checkbox-row">
            <input id="show-selection-overlay" type="checkbox" checked />
            Show selection (green contour / tint)
          </label>
        </div>
        <p class="fieldset-hint muted" style="margin-top: 6px;">
          Uncheck overlays to see the raw membrane; re-check to verify what is selected.
        </p>
      </fieldset>
      <fieldset>
        <legend>Optional: crop box (if field is crowded)</legend>
        <p class="fieldset-hint muted">Drag a box on the preview (when not selecting an object) to crop neighbors away. Optional if you already selected the object.</p>
        <div class="grid four">
          <input id="roi-xmin" type="number" placeholder="xmin" />
          <input id="roi-xmax" type="number" placeholder="xmax" />
          <input id="roi-ymin" type="number" placeholder="ymin" />
          <input id="roi-ymax" type="number" placeholder="ymax" />
        </div>
        <div class="button-row fieldset-actions">
          <button id="clear-roi-btn" class="secondary" type="button">Clear ROI</button>
          <span id="roi-status" class="inline-status">Full field — largest object auto-selected</span>
        </div>
      </fieldset>
      <div class="frame-control-wrap" style="margin: 1.5rem 0; padding: 0.5rem 0.25rem;">
        <label class="frame-control" style="margin-bottom: 0;">
          Preview slice
          <div class="frame-control-row">
            <input id="frame-slider" type="range" min="0" max="0" step="1" value="0" />
            <input id="frame-input" type="number" min="0" step="1" value="0" />
          </div>
          <span id="frame-slice-label" class="inline-status frame-slice-label">Slice 1 of 1</span>
        </label>
      </div>
      <fieldset>
        <legend>Slice range for analysis/3D</legend>
        <div class="range-pair">
          <label>
            Start slice
            <input id="z-start-slider" type="range" min="0" max="1" step="1" value="0" />
          </label>
          <label>
            Stop slice
            <input id="z-stop-slider" type="range" min="1" max="1" step="1" value="1" />
          </label>
        </div>
        <div class="grid two">
          <input id="z-min" type="number" min="0" step="1" placeholder="start" />
          <input id="z-max" type="number" min="0" step="1" placeholder="stop" />
        </div>
        <div class="button-row fieldset-actions">
          <button id="use-full-range-btn" class="secondary" type="button">Use Full Stack</button>
          <span id="z-range-status" class="inline-status">Full stack (all slices)</span>
        </div>
      </fieldset>
      <div id="preview-output" class="preview-output muted">No preview rendered yet.</div>
      <div
        id="volume-viewer-panel"
        class="volume-viewer-panel"
        data-state="idle"
        aria-label="Calibrated 3D volume navigation"
      >
        <div class="volume-viewer-header">
          <h3>3D volume navigation</h3>
          <span class="volume-nav-badge" id="volume-nav-badge">${NAVIGATION_ONLY_LABEL}</span>
        </div>
        <p class="muted" style="margin: 0; font-size: 0.9rem;">
          Optional coarse display level for spatial context. Does not segment or measure.
          2D preview stays available if 3D fails or is turned off.
        </p>
        <div class="volume-viewer-controls">
          <label class="checkbox-row" style="min-width: auto;">
            <input id="volume-viewer-enable" type="checkbox" checked />
            Enable 3D volume
          </label>
          <label>
            Blend
            <select id="volume-blend-mode">
              <option value="mip" selected>MIP</option>
              <option value="composite">Alpha blend</option>
            </select>
          </label>
          <label>
            Opacity
            <input id="volume-opacity" type="range" min="0.05" max="1" step="0.05" value="0.35" />
          </label>
          <button id="volume-reload-btn" class="secondary" type="button">Load / refresh 3D</button>
          <button id="volume-seed-pick-btn" class="secondary" type="button" title="Click in the volume to set the same ObjectSeed as 2D">
            Pick seed in 3D
          </button>
        </div>
        <div id="volume-viewer-canvas-wrap" class="volume-viewer-canvas-wrap" hidden>
          <div id="volume-vtk-root" class="volume-vtk-root"></div>
        </div>
        <div id="volume-viewer-fallback" class="volume-viewer-fallback muted">
          Inspect a stack to build a display-only volume (or use Load / refresh 3D).
        </div>
        <div id="volume-viewer-status" class="volume-viewer-status">Idle</div>
        <div id="volume-viewer-meta" class="volume-viewer-meta" hidden></div>
      </div>
      <div id="mesh-output" class="mesh-output muted">No 3D mesh rendered yet.</div>
      <div id="analysis-summary" class="output muted">No analysis run yet.</div>
    </section>
  </main>

  <section class="results" id="step-3-panel">
    <div class="results-header">
      <h2><span class="step-badge">3</span> Batch</h2>
      <div class="button-row">
        <button id="batch-analyze-btn" type="button">Analyze Batch</button>
        <button id="download-batch-report-btn" class="secondary" type="button" disabled>Download Batch Report</button>
        <button id="download-batch-btn" class="secondary" type="button" disabled>Download Batch CSV</button>
      </div>
    </div>
    <label class="batch-file-label">
      Stack files
      <input id="batch-file-input" type="file" accept=".tif,.tiff,.lsm,.czi,image/tiff" multiple />
    </label>
    <div id="batch-summary" class="output muted">No batch run yet.</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Source</th>
            <th>Status</th>
            <th>Profile</th>
            <th>Frames</th>
            <th>Valid</th>
            <th>Mean area (um2)</th>
            <th>Mean def. index</th>
            <th>Mean circularity</th>
          </tr>
        </thead>
        <tbody id="batch-results-body">
          <tr><td colspan="8" class="muted">Run a batch analysis to populate stack summaries.</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="results">
    <div class="results-header">
      <h2><span class="step-badge">3</span> Threshold Sweep</h2>
      <div class="button-row">
        <button id="sweep-btn" type="button">Run Sweep</button>
        <button id="download-sweep-report-btn" class="secondary" type="button" disabled>Download Sweep Report</button>
        <button id="download-sweep-btn" class="secondary" type="button" disabled>Download Sweep CSV</button>
      </div>
    </div>
    <div class="grid sweep-grid">
      <label>
        Start
        <input id="sweep-start" type="number" step="1" value="50" />
      </label>
      <label>
        Stop
        <input id="sweep-stop" type="number" step="1" value="200" />
      </label>
      <label>
        Step
        <input id="sweep-step" type="number" min="0" step="1" value="10" />
      </label>
    </div>
    <div id="sweep-summary" class="output muted">No threshold sweep run yet.</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Threshold</th>
            <th>Valid fraction</th>
            <th>Valid frames</th>
            <th>Mean area (um2)</th>
            <th>Mean def. index</th>
            <th>Mean circularity</th>
            <th>Warnings</th>
          </tr>
        </thead>
        <tbody id="sweep-results-body">
          <tr><td colspan="7" class="muted">Run a sweep to compare candidate thresholds.</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="results" id="step-4-panel">
    <div class="results-header">
      <h2><span class="step-badge">4</span> CSV Validation</h2>
      <button id="validate-csv-btn" type="button">Validate</button>
    </div>
    <div class="grid validation-grid">
      <label>
        Reference CSV
        <input id="expected-csv-input" type="file" accept=".csv,text/csv" />
      </label>
      <label>
        New CSV
        <input id="actual-csv-input" type="file" accept=".csv,text/csv" />
      </label>
      <label>
        Tolerance
        <input id="validation-tolerance" type="number" min="0" step="0.000001" value="0.000001" />
      </label>
      <label>
        Key column
        <input id="validation-key-column" type="text" value="frame_index" />
      </label>
      <label class="wide">
        Columns
        <input id="validation-columns" type="text" placeholder="area_um2 circularity deformation_index" />
      </label>
      <label class="checkbox-row">
        <input id="validation-all-columns" type="checkbox" />
        Compare all columns
      </label>
    </div>
    <div id="validation-summary" class="output muted">No validation run yet.</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Row</th>
            <th>Column</th>
            <th>Expected</th>
            <th>Actual</th>
            <th>Delta</th>
          </tr>
        </thead>
        <tbody id="validation-results-body">
          <tr><td colspan="5" class="muted">Run validation to show differences.</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="results" id="step-5-panel">
    <div class="results-header">
      <h2><span class="step-badge">5</span> Frame Metrics</h2>
      <div class="button-row">
        <button id="reanalyze-excluded-btn" class="secondary" type="button" disabled>Re-analyze with exclusions</button>
        <button id="download-report-btn" class="secondary" type="button" disabled>Download Report</button>
        <button id="download-manifest-btn" class="secondary" type="button" disabled>Download Manifest</button>
        <button id="download-csv-btn" class="secondary" type="button" disabled>Download CSV</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Exclude</th>
            <th>Frame</th>
            <th>Method</th>
            <th>Contour</th>
            <th>Slice area (um2)</th>
            <th>Slice perimeter (um)</th>
            <th>Eq. diameter (um)</th>
            <th>Aspect</th>
            <th>Elongation</th>
            <th>Def. index</th>
            <th>Solidity</th>
            <th>Circularity</th>
          </tr>
        </thead>
        <tbody id="results-body">
          <tr><td colspan="12" class="muted">Run an analysis to populate metrics.</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="results" id="step-6-panel">
    <div class="results-header">
      <h2><span class="step-badge">6</span> Log Book</h2>
      <div class="button-row">
        <button id="clear-logs-btn" class="secondary" type="button">Clear Logs</button>
        <button id="download-logs-btn" class="secondary" type="button">Export Logs (JSON)</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width: 120px;">Time</th>
            <th style="width: 250px;">Action</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody id="log-results-body">
          <tr><td colspan="3" class="muted">No actions recorded yet.</td></tr>
        </tbody>
      </table>
    </div>
  </section>
`;

const apiStatus = mustElement<HTMLDivElement>("api-status");
const projectStatus = mustElement<HTMLDivElement>("project-status");
const inspectOutput = mustElement<HTMLDivElement>("inspect-output");
const previewOutput = mustElement<HTMLDivElement>("preview-output");
const volumeViewerPanel = mustElement<HTMLDivElement>("volume-viewer-panel");
const volumeViewerCanvasWrap = mustElement<HTMLDivElement>("volume-viewer-canvas-wrap");
const volumeVtkRoot = mustElement<HTMLDivElement>("volume-vtk-root");
const volumeViewerFallback = mustElement<HTMLDivElement>("volume-viewer-fallback");
const volumeViewerStatus = mustElement<HTMLDivElement>("volume-viewer-status");
const volumeViewerMeta = mustElement<HTMLDivElement>("volume-viewer-meta");
const volumeViewerEnable = mustElement<HTMLInputElement>("volume-viewer-enable");
const volumeBlendModeSelect = mustElement<HTMLSelectElement>("volume-blend-mode");
const volumeOpacityInput = mustElement<HTMLInputElement>("volume-opacity");
const meshOutput = mustElement<HTMLDivElement>("mesh-output");
const analysisSummary = mustElement<HTMLDivElement>("analysis-summary");
const batchSummary = mustElement<HTMLDivElement>("batch-summary");
const sweepSummary = mustElement<HTMLDivElement>("sweep-summary");
const validationSummary = mustElement<HTMLDivElement>("validation-summary");
const resultsBody = mustElement<HTMLTableSectionElement>("results-body");
const batchResultsBody = mustElement<HTMLTableSectionElement>("batch-results-body");
const sweepResultsBody = mustElement<HTMLTableSectionElement>("sweep-results-body");
const validationResultsBody = mustElement<HTMLTableSectionElement>("validation-results-body");
const reanalyzeExcludedButton = mustElement<HTMLButtonElement>("reanalyze-excluded-btn");
const downloadCsvButton = mustElement<HTMLButtonElement>("download-csv-btn");
const downloadReportButton = mustElement<HTMLButtonElement>("download-report-btn");
const downloadManifestButton = mustElement<HTMLButtonElement>("download-manifest-btn");
const downloadBatchButton = mustElement<HTMLButtonElement>("download-batch-btn");
const downloadBatchReportButton = mustElement<HTMLButtonElement>("download-batch-report-btn");
const downloadSweepButton = mustElement<HTMLButtonElement>("download-sweep-btn");
const downloadSweepReportButton = mustElement<HTMLButtonElement>("download-sweep-report-btn");
const frameInput = mustElement<HTMLInputElement>("frame-input");
const frameSlider = mustElement<HTMLInputElement>("frame-slider");
const zMinInput = mustElement<HTMLInputElement>("z-min");
const zMaxInput = mustElement<HTMLInputElement>("z-max");
const zStartSlider = mustElement<HTMLInputElement>("z-start-slider");
const zStopSlider = mustElement<HTMLInputElement>("z-stop-slider");
const roiStatus = mustElement<HTMLSpanElement>("roi-status");
const zRangeStatus = mustElement<HTMLSpanElement>("z-range-status");
let latestAnalysis: AnalyzeResponse | null = null;
let latestTracking: TrackingRecord[] | null = null;
let latestBatch: BatchAnalyzeResponse | null = null;
let latestSweep: SweepResponse | null = null;
let latestMeshPreview: MeshPreviewResponse | null = null;
let inspectedFrameCount: number | null = null;
let previewDebounce: number | null = null;
let exactPreviewDebounce: number | null = null;
/** Monotonic token: only the latest scheduled preview generation may update the overlay. */
let previewRequestGen = 0;
/** Server upload-session id for Choose File mode (avoids re-uploading large CZIs). */
let sessionStackId: string | null = null;
/** Identity of the File bound to ``sessionStackId`` (name|size|lastModified). */
let sessionFileKey: string | null = null;
/** In-flight session open so concurrent preview/mesh share one upload. */
let sessionOpenPromise: Promise<string> | null = null;
let exactAbort: AbortController | null = null;
/** Last applied overlay for this generation — prevents provisional overwriting exact. */
let lastAppliedPreview: {
  gen: number;
  frameIndex: number;
  quality: PreviewQuality;
} | null = null;
/**
 * Generation that owns the "Tracking object…" busy indicator.
 * Only that generation may claim or release the DOM overlay.
 */
let busyOwner: BusyOwner | null = null;
/** Exact request still pending for this generation (seeded path). */
let exactPendingGen: number | null = null;
/** Last applied exact tracked center (preview coords); ignored if gen is stale. */
let lastTrackedCenter: {
  gen: number;
  frameIndex: number;
  x: number;
  y: number;
} | null = null;
/** Non-busy exact error status (settled failure); not busy-overlay ownership. */
let lastExactPreviewError: { gen: number; message: string } | null = null;
let selectedObjectSeed: ObjectSeed | null = null;
let excludedFrameIndices = new Set<number>();
let selectObjectMode = false;
let polygonPoints: { imgX: number; imgY: number }[] = [];
let polygonClosed = false;
/** Packet 12: isolated display-only volume session (never science authority). */
let volumeSession: VolumeViewerSession | null = null;
/** Monotonic token so stack switches cancel in-flight pyramid/volume loads. */
let volumeLoadGen = 0;
/** Last display level payload (for seed geometry / stale revision). */
let lastDisplayLevelPayload: DisplayLevelResponse | null = null;
/** Inspected full-stack shape (Z,Y,X) for source seed bounds. */
let inspectedSourceShape: [number, number, number] | null = null;
/** True while 3D seed pick mode is armed (click, no intensity snap). */
let volumeSeedPickMode = false;

mustElement<HTMLSelectElement>("profile-input").addEventListener("change", () => {
  updateProfileHelp();
  updateObjectSeedStatus();
});

mustElement<HTMLInputElement>("file-input").addEventListener("change", () => {
  clearUploadSession();
  updateSessionBanner();
  disposeVolumeViewer("stack source changed");
});

mustElement<HTMLInputElement>("path-input").addEventListener("input", () => {
  updateSessionBanner();
});

mustElement<HTMLInputElement>("path-input").addEventListener("change", () => {
  disposeVolumeViewer("stack path changed");
});

volumeViewerEnable.checked = isVolumeViewerEnabled();
volumeViewerEnable.addEventListener("change", () => {
  setVolumeViewerEnabled(volumeViewerEnable.checked);
  if (!volumeViewerEnable.checked) {
    disposeVolumeViewer("disabled by user");
    setVolumeViewerUiFallback(
      "feature_disabled",
      fallbackMessage("feature_disabled")
    );
    return;
  }
  void loadVolumeViewer({ reason: "enabled" });
});

volumeBlendModeSelect.addEventListener("change", () => {
  const mode = readVolumeBlendMode();
  volumeSession?.setBlendMode(mode);
  if (volumeSession?.readyMeta) {
    updateVolumeMetaLine(volumeSession.readyMeta);
  }
});

volumeOpacityInput.addEventListener("input", () => {
  const gain = Number(volumeOpacityInput.value);
  if (Number.isFinite(gain)) {
    volumeSession?.setOpacityGain(gain);
  }
});

mustElement<HTMLButtonElement>("volume-reload-btn").addEventListener("click", () => {
  void loadVolumeViewer({ reason: "manual refresh" });
});

mustElement<HTMLButtonElement>("volume-seed-pick-btn").addEventListener("click", () => {
  toggleVolumeSeedPickMode();
});

mustElement<HTMLSelectElement>("calibration-mode").addEventListener("change", () => {
  // Session was decoded with prior voxel override; force re-open on next file op.
  if (sessionStackId) {
    clearUploadSession();
  }
});

for (const id of ["voxel-x", "voxel-y", "voxel-z"] as const) {
  mustElement<HTMLInputElement>(id).addEventListener("change", () => {
    if (sessionStackId) {
      clearUploadSession();
    }
  });
}

mustElement<HTMLButtonElement>("inspect-btn").addEventListener("click", () => {
  void inspectStack();
});

mustElement<HTMLSelectElement>("calibration-mode").addEventListener("change", (e) => {
  const select = e.target as HTMLSelectElement;
  const isAuto = select.value === "auto";
  mustElement<HTMLInputElement>("voxel-x").disabled = isAuto;
  mustElement<HTMLInputElement>("voxel-y").disabled = isAuto;
  mustElement<HTMLInputElement>("voxel-z").disabled = isAuto;
});

mustElement<HTMLButtonElement>("analyze-btn").addEventListener("click", () => {
  void analyzeStack();
});

mustElement<HTMLButtonElement>("reanalyze-excluded-btn").addEventListener("click", () => {
  void analyzeStack({ keepExclusions: true });
});

mustElement<HTMLButtonElement>("preview-btn").addEventListener("click", () => {
  void requestAuthoritativePreview();
});

mustElement<HTMLButtonElement>("mesh-preview-btn").addEventListener("click", () => {
  void previewMesh();
});

mustElement<HTMLButtonElement>("suggest-threshold-btn").addEventListener("click", () => {
  void suggestThreshold();
});

mustElement<HTMLInputElement>("skeleton-input").addEventListener("change", () => {
  updateSkeletonPruneVisibility();
  schedulePreview();
});

mustElement<HTMLInputElement>("skeleton-prune-input").addEventListener("change", () => {
  if (mustElement<HTMLInputElement>("skeleton-input").checked) {
    schedulePreview();
  }
});

mustElement<HTMLButtonElement>("clear-roi-btn").addEventListener("click", () => {
  clearRoiFields();
  schedulePreview();
});

mustElement<HTMLButtonElement>("select-object-btn").addEventListener("click", () => {
  selectObjectMode = !selectObjectMode;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = selectObjectMode ? "Cancel Selection" : "Select Object";
  btn.classList.toggle("active", selectObjectMode);
  if (!selectObjectMode) {
    polygonPoints = [];
    polygonClosed = false;
    const overlay = document.getElementById("polygon-overlay");
    if (overlay) {
      overlay.innerHTML = "";
      overlay.setAttribute("hidden", "true");
    }
    // Leaving selection mode: hide transient drag circle unless a seed remains (redraw below).
    const seedEl = document.getElementById("seed-selection") as HTMLDivElement | null;
    if (seedEl && !selectedObjectSeed) {
      seedEl.hidden = true;
    }
  }
  updateObjectSeedStatus();
  // Keep/restore persistent circle ROI overlay when canceling with an existing seed.
  const image = document.getElementById("preview-image") as HTMLImageElement | null;
  if (image && selectedObjectSeed) {
    drawPersistentCircleSeedOverlay(image, selectedObjectSeed, readRoi());
  }
});

mustElement<HTMLInputElement>("show-tracking-debug").addEventListener("change", () => {
  updateTrackingDebugOverlay(globalPreviewFrameIndex(readLocalPreviewFrameIndex()), readRoi());
});

mustElement<HTMLSelectElement>("object-seed-tool").addEventListener("change", () => {
  const toolSelect = mustElement<HTMLSelectElement>("object-seed-tool");
  const isPoly = toolSelect.value === "polygon";
  mustElement<HTMLElement>("seed-radius-container").style.display = isPoly ? "none" : "block";
  polygonPoints = [];
  polygonClosed = false;
  const overlay = document.getElementById("polygon-overlay");
  if (overlay) {
    overlay.innerHTML = "";
    overlay.setAttribute("hidden", "true");
  }
  updateObjectSeedStatus();
});

mustElement<HTMLButtonElement>("clear-object-btn").addEventListener("click", () => {
  clearObjectSeed();
});

mustElement<HTMLButtonElement>("use-full-range-btn").addEventListener("click", () => {
  useFullFrameRange();
});

frameSlider.addEventListener("input", () => {
  frameInput.value = frameSlider.value;
  updateFrameSliceLabel();
  schedulePreview();
});

frameInput.addEventListener("input", () => {
  syncFrameSliderToInput();
  updateFrameSliceLabel();
  schedulePreview();
});

zStartSlider.addEventListener("input", () => {
  const start = Math.min(Number(zStartSlider.value), Number(zStopSlider.value) - 1);
  zMinInput.value = String(Math.max(0, start));
  syncZRangeControls();
});

zStopSlider.addEventListener("input", () => {
  const stop = Math.max(Number(zStopSlider.value), Number(zStartSlider.value) + 1);
  zMaxInput.value = String(stop);
  syncZRangeControls();
});

[zMinInput, zMaxInput].forEach((input) => {
  input.addEventListener("input", () => {
    syncZRangeControls();
  });
});

["roi-xmin", "roi-xmax", "roi-ymin", "roi-ymax"].forEach((id) => {
  mustElement<HTMLInputElement>(id).addEventListener("input", () => {
    updateRoiStatus();
  });
});

mustElement<HTMLButtonElement>("batch-analyze-btn").addEventListener("click", () => {
  void analyzeBatch();
});

mustElement<HTMLButtonElement>("load-project-btn").addEventListener("click", () => {
  void loadProjectFromFile();
});

mustElement<HTMLButtonElement>("download-project-btn").addEventListener("click", () => {
  downloadCurrentProject();
});

mustElement<HTMLButtonElement>("sweep-btn").addEventListener("click", () => {
  void runSweep();
});

mustElement<HTMLButtonElement>("validate-csv-btn").addEventListener("click", () => {
  void validateCsv();
});

downloadCsvButton.addEventListener("click", () => {
  downloadLatestCsv();
});

downloadManifestButton.addEventListener("click", () => {
  downloadLatestManifest();
});

downloadReportButton.addEventListener("click", () => {
  downloadLatestReport();
});

downloadBatchButton.addEventListener("click", () => {
  downloadLatestBatchCsv();
});

downloadBatchReportButton.addEventListener("click", () => {
  downloadLatestBatchReport();
});

downloadSweepButton.addEventListener("click", () => {
  downloadLatestSweepCsv();
});

downloadSweepReportButton.addEventListener("click", () => {
  downloadLatestSweepReport();
});

// Scroll-into-view workflow strip navigation
const workflowSpans = document.querySelectorAll(".workflow-strip span");
workflowSpans.forEach((span, index) => {
  span.addEventListener("click", () => {
    const stepId = `step-${index + 1}-panel`;
    const element = document.getElementById(stepId);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
});

// Log Book controls
mustElement<HTMLButtonElement>("clear-logs-btn").addEventListener("click", () => {
  frontendLogs.length = 0;
  logAction("Clear Logs", "User cleared the log book.");
});

mustElement<HTMLButtonElement>("download-logs-btn").addEventListener("click", () => {
  downloadLogs();
});

/** How long to keep retrying /api/health after load (dev race: Vite ready before uvicorn worker). */
const HEALTH_RETRY_MS = 45_000;
const HEALTH_RETRY_INTERVAL_MS = 500;
let healthPollTimer: number | null = null;

void startHealthPolling();
updateSkeletonPruneVisibility();
updateFrameSliceLabel();
updateSessionBanner();
updateProfileHelp();
wireOverlayToggles();
updateObjectSeedStatus();

function stopHealthPolling(): void {
  if (healthPollTimer !== null) {
    window.clearTimeout(healthPollTimer);
    healthPollTimer = null;
  }
}

/**
 * One-shot health probe. Returns true when API reports ok.
 * Does not leave a permanent offline banner without retries (see startHealthPolling).
 */
async function refreshHealth(): Promise<boolean> {
  try {
    const payload = await apiGet<{ ok: boolean; version: string }>("/api/health");
    if (payload.ok) {
      apiStatus.textContent = `API ${payload.version}`;
      apiStatus.className = "status ok";
      return true;
    }
    apiStatus.textContent = "API unavailable";
    apiStatus.className = "status warn";
    return false;
  } catch {
    apiStatus.textContent = "Connecting to API…";
    apiStatus.className = "status warn";
    return false;
  }
}

/**
 * Retry health until the API is up or the budget expires.
 * Fixes morphostack dev race: browser opens while uvicorn --reload child is still starting.
 */
function startHealthPolling(): void {
  stopHealthPolling();
  const deadline = Date.now() + HEALTH_RETRY_MS;
  apiStatus.textContent = "Connecting to API…";
  apiStatus.className = "status warn";

  const tick = async (): Promise<void> => {
    const ok = await refreshHealth();
    if (ok) {
      stopHealthPolling();
      return;
    }
    if (Date.now() >= deadline) {
      apiStatus.textContent = "API offline — run morphostack dev or morphostack app";
      apiStatus.className = "status warn";
      stopHealthPolling();
      return;
    }
    healthPollTimer = window.setTimeout(() => {
      void tick();
    }, HEALTH_RETRY_INTERVAL_MS);
  };
  void tick();
}

async function ensureApiOnline(): Promise<void> {
  // Short burst of retries so Inspect right after load still wins the startup race.
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    try {
      const payload = await apiGet<{ ok: boolean; version: string }>("/api/health");
      if (payload.ok) {
        apiStatus.textContent = `API ${payload.version}`;
        apiStatus.className = "status ok";
        stopHealthPolling();
        return;
      }
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, HEALTH_RETRY_INTERVAL_MS));
  }
  apiStatus.textContent = "API offline — run morphostack dev or morphostack app";
  apiStatus.className = "status warn";
  throw new Error(
    "MorphoStack API is offline. Start it with `morphostack dev` (recommended) or `morphostack app`, then retry Inspect."
  );
}

async function loadProjectFromFile(): Promise<void> {
  try {
    const file = selectedRequiredFile("project-file-input", "Project JSON");
    const payload = JSON.parse(await file.text()) as unknown;
    const settings = validateProjectSettings(payload);
    applyProjectSettings(settings);
    projectStatus.textContent = file.name;
    projectStatus.className = "status ok";
    logAction("Load Project Settings", `Successfully loaded settings from "${file.name}".`);
  } catch (error) {
    projectStatus.textContent = errorMessage(error);
    projectStatus.className = "status warn";
    logAction("Load Project Settings Failed", `Error: ${errorMessage(error)}`);
  }
}

function downloadCurrentProject(): void {
  try {
    const project = currentProjectSettings();
    const json = `${JSON.stringify(project, null, 2)}\n`;
    const blob = new Blob([json], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "morphostack.project.json";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    projectStatus.textContent = "Project downloaded";
    projectStatus.className = "status ok";
    logAction("Download Project Settings", `Saved settings config as "morphostack.project.json".`);
  } catch (error) {
    projectStatus.textContent = errorMessage(error);
    projectStatus.className = "status warn";
    logAction("Download Project Settings Failed", `Error: ${errorMessage(error)}`);
  }
}

function uploadStatusMarkup(label: string, percent: number | null): string {
  if (percent === null) {
    return `${escapeHtml(label)}<div class="upload-progress indeterminate" aria-hidden="true"><span></span></div>`;
  }
  const clamped = Math.max(0, Math.min(100, percent));
  return `${escapeHtml(label)} (${clamped}%)<div class="upload-progress" aria-hidden="true"><span style="width:${clamped}%"></span></div>`;
}

async function inspectStack(): Promise<void> {
  let usedUpload = false;
  try {
    const source = resolveStackSource();
    usedUpload = source.kind === "file";
    await ensureApiOnline();
    let payload: InspectResponse;
    if (source.kind === "path") {
      clearUploadSession();
      inspectOutput.innerHTML = uploadStatusMarkup("Inspecting stack (local path)", null);
      logAction("Inspect Stack Started", `Local path "${source.path}"`);
      payload = await apiPost<InspectResponse>("/api/inspect", {
        path: source.path,
        voxel: readVoxel()
      });
    } else {
      const file = source.file;
      const sizeMb = file.size / (1024 * 1024);
      const large = file.size >= LARGE_UPLOAD_WARN_BYTES;
      const label = large
        ? `Loading large file ${file.name} (${sizeMb.toFixed(0)} MB) into server memory (once)`
        : `Loading ${file.name} into server memory`;
      inspectOutput.innerHTML = uploadStatusMarkup(label, 0);
      logAction(
        "Inspect Stack Started",
        large
          ? `Upload-once session for large file "${file.name}" (${sizeMb.toFixed(1)} MB)`
          : `Upload-once session for "${file.name}"`
      );
      // /upload/inspect opens a server session (stack_id) so later ops skip re-upload.
      payload = await apiUploadPost<InspectResponse>(
        "/api/upload/inspect",
        inspectUploadForm(file),
        (percent) => {
          inspectOutput.innerHTML = uploadStatusMarkup(label, percent);
        }
      );
      if (payload.stack_id) {
        rememberUploadSession(payload.stack_id, file);
      }
    }
    const sessionNote =
      payload.stack_id != null
        ? `<br /><span class="session-ok">Server session ready — previews will not re-upload.</span>`
        : "";
    inspectOutput.innerHTML = `
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Grayscale: ${payload.grayscale_shape.join(" x ")}<br />
      Color: ${payload.color_shape.join(" x ")}<br />
      Voxel: x=${formatNumber(payload.voxel_size.x_um)} um,
      y=${formatNumber(payload.voxel_size.y_um)} um,
      z=${formatNumber(payload.voxel_size.z_um)} um<br />
      ${voxelSourceMarkup(payload.voxel_source)}${sessionNote}
    `;
    applyVoxelDefaultStyling(payload.voxel_source);
    updateSessionBanner();

    // Auto-populate the visible voxel input fields if in Auto calibration mode
    const mode = mustElement<HTMLSelectElement>("calibration-mode").value;
    if (mode === "auto") {
      mustElement<HTMLInputElement>("voxel-x").value = formatInputNumber(payload.voxel_size.x_um);
      mustElement<HTMLInputElement>("voxel-y").value = formatInputNumber(payload.voxel_size.y_um);
      mustElement<HTMLInputElement>("voxel-z").value = formatInputNumber(payload.voxel_size.z_um);
    }

    inspectedFrameCount = payload.grayscale_shape[0] ?? null;
    if (payload.grayscale_shape.length >= 3) {
      inspectedSourceShape = [
        Number(payload.grayscale_shape[0]),
        Number(payload.grayscale_shape[1]),
        Number(payload.grayscale_shape[2])
      ];
    } else {
      inspectedSourceShape = null;
    }
    syncZRangeControls({ initializeFullRange: true });
    logAction(
      "Inspect Stack Succeeded",
      `Source: "${payload.source_path}", Shape: [${payload.grayscale_shape.join(", ")}], Voxel source: ${payload.voxel_source}${
        payload.stack_id ? `, stack_id: ${payload.stack_id}` : ""
      }`
    );
    // Display-only volume: never blocks inspect/2D; fails open to 2D workflow.
    void loadVolumeViewer({ reason: "inspect" });
  } catch (error) {
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    inspectOutput.textContent = msg;
    logAction("Inspect Stack Failed", `Error: ${msg}`);
  }
}

function readShowCircleRoiOverlay(): boolean {
  const el = document.getElementById("show-circle-roi-overlay");
  return el instanceof HTMLInputElement ? el.checked : true;
}

function readShowXyRoiOverlay(): boolean {
  const el = document.getElementById("show-xy-roi-overlay");
  return el instanceof HTMLInputElement ? el.checked : true;
}

function readShowSelectionOverlay(): boolean {
  const el = document.getElementById("show-selection-overlay");
  return el instanceof HTMLInputElement ? el.checked : true;
}

function previewJsonBody(stackRef: { path?: string; stack_id?: string }): Record<string, unknown> {
  return {
    ...stackRef,
    threshold: readNumber("threshold-input"),
    frame_index: globalPreviewFrameIndex(readLocalPreviewFrameIndex()),
    voxel: readVoxel(),
    roi: readRoi(),
    z_range: readZRange(),
    prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
    object_seed: selectedObjectSeed,
    enable_skeleton: readEnableSkeleton(),
    skeleton_prune_pix: readSkeletonPrunePix(),
    show_selection: readShowSelectionOverlay(),
    image_transport: "url"
  };
}

function shouldApplyPreview(
  gen: number,
  frameIndex: number,
  quality: PreviewQuality
): boolean {
  return shouldApplyPreviewGate(gen, previewRequestGen, frameIndex, quality, lastAppliedPreview);
}

function bumpPreviewGeneration(): number {
  const prevGen = previewRequestGen;
  previewRequestGen += 1;
  lastAppliedPreview = null;
  // Old generation loses busy ownership; do not leave its text visible.
  if (busyOwner !== null && busyOwner.gen === prevGen) {
    busyOwner = null;
    hidePreviewBusyOverlayDom();
  }
  if (exactPendingGen === prevGen) {
    exactPendingGen = null;
  }
  if (lastTrackedCenter !== null && lastTrackedCenter.gen === prevGen) {
    // Stale tracked marker is dropped until the new gen applies exact.
    lastTrackedCenter = null;
  }
  if (lastExactPreviewError !== null && lastExactPreviewError.gen === prevGen) {
    lastExactPreviewError = null;
    paintExactPreviewErrorDom();
  }
  return previewRequestGen;
}

function syncBusyOverlayDom(): void {
  if (busyVisibleForLatest(busyOwner, previewRequestGen) && busyOwner) {
    showPreviewBusyOverlayDom(busyOwner.message);
  } else {
    hidePreviewBusyOverlayDom();
  }
}

function claimTrackingBusy(gen: number, message: string): void {
  busyOwner = claimBusyOwner(busyOwner, gen, previewRequestGen, message);
  syncBusyOverlayDom();
}

function releaseTrackingBusy(gen: number): void {
  busyOwner = releaseBusyOwner(busyOwner, gen);
  syncBusyOverlayDom();
}

/** Settled exact error is not busy ownership — separate non-blocking caption. */
function setExactPreviewError(gen: number, message: string): void {
  if (gen !== previewRequestGen) {
    return;
  }
  lastExactPreviewError = { gen, message };
  paintExactPreviewErrorDom();
}

function clearExactPreviewErrorForGen(gen: number): void {
  if (lastExactPreviewError !== null && lastExactPreviewError.gen === gen) {
    lastExactPreviewError = null;
  }
  paintExactPreviewErrorDom();
}

function paintExactPreviewErrorDom(): void {
  const canvas = document.querySelector(".preview-canvas");
  let banner = document.getElementById("exact-preview-error");
  const show =
    lastExactPreviewError !== null && lastExactPreviewError.gen === previewRequestGen;
  if (!show) {
    if (banner) {
      banner.hidden = true;
      banner.textContent = "";
    }
    return;
  }
  if (!(canvas instanceof HTMLElement)) {
    return;
  }
  if (!(banner instanceof HTMLElement)) {
    banner = document.createElement("div");
    banner.id = "exact-preview-error";
    banner.className = "exact-preview-error";
    canvas.append(banner);
  }
  banner.textContent = lastExactPreviewError!.message;
  banner.hidden = false;
}

function cancelPendingPreviewTimers(): void {
  if (previewDebounce !== null) {
    window.clearTimeout(previewDebounce);
    previewDebounce = null;
  }
  if (exactPreviewDebounce !== null) {
    window.clearTimeout(exactPreviewDebounce);
    exactPreviewDebounce = null;
  }
}

async function fetchPreviewPayload(
  fastPreview: boolean,
  signal: AbortSignal
): Promise<PreviewResponse> {
  const source = resolveStackSource();
  if (source.kind === "path") {
    return apiPost<PreviewResponse>(
      "/api/preview",
      { ...previewJsonBody({ path: source.path }), fast_preview: fastPreview },
      signal
    );
  }
  const stackId = await ensureUploadSession(source.file, {
    onProgress: (percent) => {
      if (!signal.aborted && !document.getElementById("preview-image")) {
        previewOutput.innerHTML = uploadStatusMarkup(
          `Loading ${source.file.name} into server memory (once)`,
          percent
        );
      }
    }
  });
  if (signal.aborted) {
    throw new DOMException("Aborted", "AbortError");
  }
  return apiPost<PreviewResponse>(
    "/api/preview",
    { ...previewJsonBody({ stack_id: stackId }), fast_preview: fastPreview },
    signal
  );
}

function previewQualityOf(payload: PreviewResponse, fallback: PreviewQuality): PreviewQuality {
  return payload.preview_quality === "provisional" || payload.preview_quality === "exact"
    ? payload.preview_quality
    : fallback;
}

/**
 * Single provisional runner used by the generation-aware scheduler.
 * Throws AbortError when the signal aborts so the scheduler can hand off.
 */
async function executeProvisionalFetch(gen: number, signal: AbortSignal): Promise<void> {
  if (gen !== previewRequestGen) {
    return;
  }
  const roi = readRoi();
  let usedUpload = false;
  try {
    usedUpload = resolveStackSource().kind === "file";
    if (!document.getElementById("preview-image")) {
      previewOutput.textContent = "Rendering preview…";
    } else if (!selectedObjectSeed) {
      claimTrackingBusy(gen, "Rendering preview…");
    } else {
      claimTrackingBusy(gen, "Provisional preview…");
    }
    const payload = await fetchPreviewPayload(true, signal);
    if (signal.aborted || gen !== previewRequestGen) {
      // Stale/aborted: do not release a newer generation's busy ownership.
      return;
    }
    const quality = previewQualityOf(payload, selectedObjectSeed ? "provisional" : "exact");
    if (!shouldApplyPreview(gen, payload.frame_index, quality)) {
      return;
    }
    renderPreview(payload, roi);
    lastAppliedPreview = { gen, frameIndex: payload.frame_index, quality };
    // Tracking text only while matching exact request is still pending.
    busyOwner = busyAfterProvisional(
      busyOwner,
      gen,
      previewRequestGen,
      exactPendingGen,
      Boolean(selectedObjectSeed) && quality === "provisional",
      trackingBusyMessage(null, globalPreviewFrameIndex(readLocalPreviewFrameIndex()))
    );
    syncBusyOverlayDom();
    logAction(
      "Preview Stack Frame Succeeded",
      `Frame: ${payload.frame_index}, quality=${quality}, Method: ${payload.method}`
    );
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    if (gen !== previewRequestGen) {
      return;
    }
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    if (!document.getElementById("preview-image")) {
      previewOutput.textContent = msg;
    }
    releaseTrackingBusy(gen);
    logAction("Preview Stack Frame Failed", `Error: ${msg}`);
  }
}

const provisionalScheduler = new ProvisionalPreviewScheduler(
  () => previewRequestGen,
  executeProvisionalFetch
);

function runProvisionalPreview(gen: number): void {
  provisionalScheduler.request(gen);
}

/** Manual Preview button / seed pick: authoritative path (exact when seed present). */
async function requestAuthoritativePreview(): Promise<void> {
  if (!hasStackInput()) {
    return;
  }
  cancelPendingPreviewTimers();
  const gen = bumpPreviewGeneration();
  provisionalScheduler.cancel();
  exactAbort?.abort();
  exactPendingGen = selectedObjectSeed ? gen : null;
  if (selectedObjectSeed) {
    // Provisional first; exact subscription claims busy when target is missing.
    runProvisionalPreview(gen);
  } else {
    releaseTrackingBusy(gen);
  }
  await runExactPreview(gen);
}

/** Legacy entry used by seed apply/clear: authoritative refresh. */
async function previewStack(_fastPreview = false): Promise<void> {
  await requestAuthoritativePreview();
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const id = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = (): void => {
      window.clearTimeout(id);
      signal.removeEventListener("abort", onAbort);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function applyExactPayload(gen: number, payload: PreviewResponse, roi: RectRoi | null): void {
  const quality = previewQualityOf(payload, "exact");
  if (!shouldApplyPreview(gen, payload.frame_index, quality)) {
    return;
  }
  // Never paint provisional as exact via this path.
  if (quality !== "exact" && payload.exact_available !== true) {
    return;
  }
  renderPreview(payload, roi);
  lastAppliedPreview = { gen, frameIndex: payload.frame_index, quality: "exact" };
  applyTrackedCenterFromPayload(gen, payload);
  if (exactPendingGen === gen) {
    exactPendingGen = null;
  }
  clearExactPreviewErrorForGen(gen);
  releaseTrackingBusy(gen);
}

/**
 * Exact path (seeded): subscribe to packet-03 job + cache.
 * Does not launch a second science walk; browser abort only cancels display polling.
 */
async function runExactPreview(gen: number): Promise<void> {
  if (gen !== previewRequestGen) {
    return;
  }
  // Without a seed there is no Z tracker — one-plane path is enough (await it).
  if (!selectedObjectSeed) {
    provisionalScheduler.cancel();
    exactPendingGen = null;
    const ac = new AbortController();
    try {
      await executeProvisionalFetch(gen, ac.signal);
    } catch (error) {
      if (!isAbortError(error)) {
        throw error;
      }
    }
    releaseTrackingBusy(gen);
    return;
  }
  exactAbort?.abort();
  exactAbort = new AbortController();
  const signal = exactAbort.signal;
  exactPendingGen = gen;
  const targetFrame = globalPreviewFrameIndex(readLocalPreviewFrameIndex());
  claimTrackingBusy(gen, trackingBusyMessage(null, targetFrame));
  const roi = readRoi();
  let usedUpload = false;
  try {
    usedUpload = resolveStackSource().kind === "file";
    if (!document.getElementById("preview-image")) {
      previewOutput.textContent = trackingBusyMessage(null, targetFrame);
    }
    let payload = await fetchPreviewPayload(false, signal);
    if (signal.aborted || gen !== previewRequestGen) {
      if (exactPendingGen === gen) {
        exactPendingGen = null;
      }
      releaseTrackingBusy(gen);
      return;
    }

    // Cache hit / already published: paint exact immediately.
    if (payload.exact_available !== false && previewQualityOf(payload, "exact") === "exact") {
      applyExactPayload(gen, payload, roi);
      logAction(
        "Exact Preview Succeeded",
        `Frame: ${payload.frame_index}, cache_hit=${Boolean(payload.cache_hit)}, method=${payload.method}`
      );
      return;
    }

    // Pending: bounded poll of job status + exact re-fetch (no aggressive tight loop).
    let jobId = payload.tracking_job?.job_id ?? null;
    let delayMs = 100;
    const deadline = Date.now() + 90_000;
    while (gen === previewRequestGen && !signal.aborted && Date.now() < deadline) {
      const job = payload.tracking_job as TrackingJobBusyInfo | null | undefined;
      const busyMsg = trackingBusyMessage(job, targetFrame);
      if (busyMsg) {
        claimTrackingBusy(gen, busyMsg);
      }
      if (job?.state === "failed") {
        if (exactPendingGen === gen) {
          exactPendingGen = null;
        }
        releaseTrackingBusy(gen);
        setExactPreviewError(
          gen,
          `Tracked contour unavailable: ${job.message || job.error_code || "failed"}`
        );
        logAction("Exact Preview Failed", `job failed: ${job.message || job.error_code}`);
        return;
      }
      if (job?.state === "cancelled") {
        if (exactPendingGen === gen) {
          exactPendingGen = null;
        }
        releaseTrackingBusy(gen);
        setExactPreviewError(gen, "Tracking cancelled");
        logAction("Exact Preview Cancelled", `job_id=${jobId ?? "?"}`);
        return;
      }

      await sleep(delayMs, signal);
      delayMs = Math.min(Math.round(delayMs * 1.4), 600);

      if (jobId) {
        try {
          const st = await apiGet<TrackingJobBusyInfo & { job_id?: string; available_exact_frames?: number[] }>(
            `/api/tracking/jobs/${jobId}`
          );
          if (gen !== previewRequestGen || signal.aborted) {
            return;
          }
          const msg = trackingBusyMessage(st, targetFrame);
          if (msg) {
            claimTrackingBusy(gen, msg);
          }
          if (st.state === "failed") {
            if (exactPendingGen === gen) {
              exactPendingGen = null;
            }
            releaseTrackingBusy(gen);
            setExactPreviewError(
              gen,
              `Tracked contour unavailable: ${st.message || st.error_code || "failed"}`
            );
            return;
          }
          if (st.state === "cancelled") {
            if (exactPendingGen === gen) {
              exactPendingGen = null;
            }
            releaseTrackingBusy(gen);
            setExactPreviewError(gen, "Tracking cancelled");
            return;
          }
        } catch {
          // Status poll soft-fail; retry exact preview body.
        }
      }

      payload = await fetchPreviewPayload(false, signal);
      if (signal.aborted || gen !== previewRequestGen) {
        if (exactPendingGen === gen) {
          exactPendingGen = null;
        }
        releaseTrackingBusy(gen);
        return;
      }
      if (!jobId && payload.tracking_job?.job_id) {
        jobId = payload.tracking_job.job_id;
      }
      if (payload.exact_available !== false && previewQualityOf(payload, "exact") === "exact") {
        applyExactPayload(gen, payload, roi);
        logAction(
          "Exact Preview Succeeded",
          `Frame: ${payload.frame_index}, cache_hit=${Boolean(payload.cache_hit)}, method=${payload.method}, polled=true`
        );
        return;
      }
    }

    if (gen === previewRequestGen && !signal.aborted) {
      if (exactPendingGen === gen) {
        exactPendingGen = null;
      }
      releaseTrackingBusy(gen);
      setExactPreviewError(gen, "Tracked contour unavailable: timed out waiting for exact frame");
      logAction("Exact Preview Failed", "poll timeout");
    }
  } catch (error) {
    if (isAbortError(error)) {
      if (exactPendingGen === gen) {
        exactPendingGen = null;
      }
      // Display abort only — does not cancel the shared authoritative job.
      releaseTrackingBusy(gen);
      return;
    }
    if (gen !== previewRequestGen) {
      if (exactPendingGen === gen) {
        exactPendingGen = null;
      }
      releaseTrackingBusy(gen);
      return;
    }
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    if (exactPendingGen === gen) {
      exactPendingGen = null;
    }
    releaseTrackingBusy(gen);
    setExactPreviewError(gen, `Tracked contour unavailable: ${msg}`);
    const canvas = document.querySelector(".preview-canvas");
    if (!canvas) {
      previewOutput.textContent = msg;
    }
    logAction("Exact Preview Failed", `Error: ${msg}`);
  }
}

function schedulePreview(): void {
  if (!hasStackInput()) {
    return;
  }
  const gen = bumpPreviewGeneration();
  // Supersede in-flight exact *display* polling only (not the shared job).
  exactAbort?.abort();
  // Exact pending until cache hit / job terminal for this gen.
  exactPendingGen = selectedObjectSeed ? gen : null;
  if (selectedObjectSeed) {
    // Do not claim global "Tracking object…" merely because a seed exists —
    // caption updates when exact subscription starts after provisional paint.
    releaseTrackingBusy(gen);
  } else {
    releaseTrackingBusy(gen);
  }
  // Coalesced provisional current-plane request (only immediate scrub compute).
  if (previewDebounce !== null) {
    window.clearTimeout(previewDebounce);
  }
  previewDebounce = window.setTimeout(() => {
    previewDebounce = null;
    if (gen === previewRequestGen) {
      runProvisionalPreview(gen);
    }
  }, PREVIEW_DEBOUNCE_MS);

  if (exactPreviewDebounce !== null) {
    window.clearTimeout(exactPreviewDebounce);
    exactPreviewDebounce = null;
  }
  if (selectedObjectSeed) {
    exactPreviewDebounce = window.setTimeout(() => {
      exactPreviewDebounce = null;
      if (gen === previewRequestGen) {
        void runExactPreview(gen);
      }
    }, EXACT_PREVIEW_DEBOUNCE_MS);
  }
}

function hasStackInput(): boolean {
  return stackPathOrNull() !== null || selectedFile() !== null;
}

async function previewMesh(): Promise<void> {
  const meshBtn = mustElement<HTMLButtonElement>("mesh-preview-btn");
  let usedUpload = false;
  let elapsedTimer: number | null = null;
  let statusPhase: "loading" | "computing" = "computing";
  let loadingLabel = "Loading stack into server memory";
  const startedAt = Date.now();
  const setMeshStatus = (label: string, percent: number | null = null): void => {
    const elapsed = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
    const withTime = percent === null ? `${label} (${elapsed}s)` : label;
    meshOutput.innerHTML = uploadStatusMarkup(withTime, percent);
  };
  meshBtn.disabled = true;
  try {
    const profile = readProfile();
    if (profile === "active_surfaces" && selectedObjectSeed === null) {
      const msg =
        "Experimental mode requires Select Object first (pick the vesicle on the preview). Or switch Mode to Standard.";
      meshOutput.textContent = msg;
      meshOutput.className = "mesh-output muted";
      logAction("Render 3D Mesh Blocked", msg);
      return;
    }
    if (profile !== "active_surfaces" && selectedObjectSeed === null) {
      // Proceed, but surface the recommendation immediately so users know.
      meshOutput.className = "mesh-output muted";
    }

    const source = resolveStackSource();
    usedUpload = source.kind === "file";
    const needsSessionOpen = source.kind === "file" && !hasActiveUploadSession(source.file);
    statusPhase = needsSessionOpen ? "loading" : "computing";
    loadingLabel = needsSessionOpen
      ? `Loading ${source.file.name} into server memory`
      : "Computing mesh…";
    setMeshStatus(statusPhase === "loading" ? loadingLabel : "Computing mesh…", null);
    elapsedTimer = window.setInterval(() => {
      // Never leave session-active mesh stuck on "Uploading…"; only show loading while opening session.
      if (statusPhase === "loading") {
        setMeshStatus(loadingLabel, null);
      } else {
        setMeshStatus("Computing mesh…", null);
      }
    }, 1000);
    logAction(
      "Render 3D Mesh Started",
      selectedObjectSeed
        ? `profile=${profile}, seed=(${selectedObjectSeed.x},${selectedObjectSeed.y})`
        : `profile=${profile}, no object seed (Select Object recommended)`
    );
    let payload: MeshPreviewResponse;
    if (source.kind === "path") {
      statusPhase = "computing";
      setMeshStatus("Computing mesh…", null);
      payload = await apiPost<MeshPreviewResponse>("/api/mesh-preview", {
        path: source.path,
        threshold: readNumber("threshold-input"),
        profile,
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange(),
        prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
        downsample: 1,
        max_faces: 12000,
        object_seed: selectedObjectSeed
      });
    } else {
      const stackId = await ensureUploadSession(source.file, {
        onProgress: (percent) => {
          statusPhase = "loading";
          loadingLabel = `Loading ${source.file.name} into server memory`;
          setMeshStatus(loadingLabel, percent);
        }
      });
      statusPhase = "computing";
      setMeshStatus("Computing mesh…", null);
      payload = await apiPost<MeshPreviewResponse>("/api/mesh-preview", {
        stack_id: stackId,
        threshold: readNumber("threshold-input"),
        profile,
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange(),
        prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
        downsample: 1,
        max_faces: 12000,
        object_seed: selectedObjectSeed
      });
    }
    renderMeshPreview(payload);
    logAction("Render 3D Mesh Succeeded", `Vertices: ${payload.vertex_count}, Faces: ${payload.face_count}`);
  } catch (error) {
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    meshOutput.textContent = msg;
    meshOutput.className = "mesh-output muted";
    logAction("Render 3D Mesh Failed", `Error: ${msg}`);
  } finally {
    if (elapsedTimer !== null) {
      window.clearInterval(elapsedTimer);
    }
    meshBtn.disabled = false;
  }
}

async function suggestThreshold(): Promise<void> {
  const status = mustElement<HTMLSpanElement>("suggest-status");
  status.textContent = "Suggesting...";
  status.className = "inline-status";
  showPreviewBusyOverlay("Suggesting threshold...");
  logAction("Suggest Threshold Started");
  let usedUpload = false;
  try {
    const source = resolveStackSource();
    usedUpload = source.kind === "file";
    let payload: ThresholdResponse;
    if (source.kind === "path") {
      payload = await apiPost<ThresholdResponse>("/api/threshold", {
        path: source.path,
        method: "auto",
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange()
      });
    } else {
      const stackId = await ensureUploadSession(source.file);
      payload = await apiPost<ThresholdResponse>("/api/threshold", {
        stack_id: stackId,
        method: "auto",
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange()
      });
    }
    mustElement<HTMLInputElement>("threshold-input").value = formatInputNumber(payload.threshold);
    const methodLabel = formatThresholdMethodLabel(payload.method);
    const scopeLabel = formatSuggestionScopeLabel(payload.suggestion_scope || "stack_sample");
    status.textContent =
      `Suggested ${formatNumber(payload.threshold)} · ${methodLabel} · ${scopeLabel} · starting guess. ` +
      `Seeded exact tracking uses a local per-slice gate.`;
    status.className = "inline-status ok";
    status.title = (payload.warnings || []).join(" ");
    hidePreviewBusyOverlay();
    logAction(
      "Suggest Threshold Succeeded",
      `Suggested: ${payload.threshold} (${payload.method}, ${payload.suggestion_scope || "stack_sample"}, ui_starting_guess)`
    );
    schedulePreview();
  } catch (error) {
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    status.textContent = msg;
    status.className = "inline-status warn";
    hidePreviewBusyOverlay();
    logAction("Suggest Threshold Failed", `Error: ${msg}`);
  }
}

function showPreviewBusyOverlayDom(message: string): void {
  const canvas = document.querySelector(".preview-canvas");
  if (!(canvas instanceof HTMLElement)) {
    return;
  }
  let overlay = document.getElementById("preview-busy-overlay");
  if (!(overlay instanceof HTMLElement)) {
    overlay = document.createElement("div");
    overlay.id = "preview-busy-overlay";
    overlay.className = "preview-busy-overlay";
    canvas.append(overlay);
  }
  overlay.textContent = message;
  overlay.hidden = false;
}

function hidePreviewBusyOverlayDom(): void {
  const overlay = document.getElementById("preview-busy-overlay");
  if (overlay) {
    overlay.hidden = true;
  }
}

/** @deprecated Prefer claim/release helpers; kept for non-preview call sites. */
function showPreviewBusyOverlay(message: string): void {
  showPreviewBusyOverlayDom(message);
}

function hidePreviewBusyOverlay(): void {
  hidePreviewBusyOverlayDom();
}

function applyTrackedCenterFromPayload(gen: number, payload: PreviewResponse): void {
  if (gen !== previewRequestGen) {
    return;
  }
  const x = payload.tracked_center_x;
  const y = payload.tracked_center_y;
  if (
    payload.preview_quality === "exact" &&
    typeof x === "number" &&
    typeof y === "number" &&
    Number.isFinite(x) &&
    Number.isFinite(y)
  ) {
    lastTrackedCenter = { gen, frameIndex: payload.frame_index, x, y };
  } else if (gen === previewRequestGen) {
    lastTrackedCenter = null;
  }
}

async function analyzeStack(options: { keepExclusions?: boolean } = {}): Promise<void> {
  if (options.keepExclusions) {
    syncExcludedFramesFromTable();
  } else {
    excludedFrameIndices = new Set<number>();
  }
  latestAnalysis = null;
  downloadCsvButton.disabled = true;
  downloadReportButton.disabled = true;
  downloadManifestButton.disabled = true;
  reanalyzeExcludedButton.disabled = true;
  const excluded = Array.from(excludedFrameIndices).sort((a, b) => a - b);
  let usedUpload = false;
  try {
    const profile = readProfile();
    if (profile === "active_surfaces" && selectedObjectSeed === null) {
      const msg =
        "Experimental mode requires Select Object first (pick the vesicle on the preview). Or switch Mode to Standard.";
      analysisSummary.textContent = msg;
      resultsBody.innerHTML = `<tr><td colspan="12" class="muted">Select Object required for Experimental mode.</td></tr>`;
      logAction("Analyze Stack Blocked", msg);
      return;
    }
    const source = resolveStackSource();
    usedUpload = source.kind === "file";
    const needsSessionOpen = source.kind === "file" && !hasActiveUploadSession(source.file);
    const analyzeLabel = needsSessionOpen
      ? `Loading ${source.file.name} into server memory${excluded.length ? ` (excluding ${excluded.length} frames)` : ""}`
      : `Analyzing stack${excluded.length ? ` (excluding ${excluded.length} frames)` : ""}`;
    analysisSummary.innerHTML = uploadStatusMarkup(analyzeLabel, needsSessionOpen ? 0 : null);
    resultsBody.innerHTML = `<tr><td colspan="12" class="muted">Running analysis...</td></tr>`;
    logAction(
      "Analyze Stack Started",
      source.kind === "file"
        ? `File "${source.file.name}"${excluded.length ? `, excluding frames: ${excluded.join(", ")}` : ""}${
            needsSessionOpen ? " (opening session)" : " (session)"
          }`
        : `Local path "${source.path}"${excluded.length ? `, excluding frames: ${excluded.join(", ")}` : ""}`
    );
    let payload: AnalyzeResponse;
    if (source.kind === "path") {
      payload = await apiPost<AnalyzeResponse>("/api/analyze", {
        path: source.path,
        threshold: readNumber("threshold-input"),
        profile,
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange(),
        include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
        enable_skeleton: readEnableSkeleton(),
        skeleton_prune_pix: readSkeletonPrunePix(),
        prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
        object_seed: selectedObjectSeed,
        excluded_frames: excluded
      });
    } else {
      const stackId = await ensureUploadSession(source.file, {
        onProgress: (percent) => {
          analysisSummary.innerHTML = uploadStatusMarkup(analyzeLabel, percent);
        }
      });
      analysisSummary.innerHTML = uploadStatusMarkup("Analyzing stack", null);
      payload = await apiPost<AnalyzeResponse>("/api/analyze", {
        stack_id: stackId,
        threshold: readNumber("threshold-input"),
        profile,
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange(),
        include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
        enable_skeleton: readEnableSkeleton(),
        skeleton_prune_pix: readSkeletonPrunePix(),
        prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
        object_seed: selectedObjectSeed,
        excluded_frames: excluded
      });
    }
    excludedFrameIndices = new Set(payload.excluded_frames ?? excluded);
    renderAnalysis(payload);
    logAction("Analyze Stack Succeeded", `Source: "${payload.source_path}", Valid frames: ${payload.valid_frame_count}/${payload.frame_count}`);
  } catch (error) {
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    analysisSummary.textContent = msg;
    resultsBody.innerHTML = `<tr><td colspan="12" class="muted">Analysis failed.</td></tr>`;
    logAction("Analyze Stack Failed", `Error: ${msg}`);
  }
}

async function analyzeBatch(): Promise<void> {
  latestBatch = null;
  downloadBatchButton.disabled = true;
  downloadBatchReportButton.disabled = true;
  batchSummary.textContent = "Analyzing batch...";
  batchResultsBody.innerHTML = `<tr><td colspan="8" class="muted">Running batch analysis...</td></tr>`;
  try {
    const files = selectedBatchFiles();
    logAction("Batch Analyze Started", `Files selected: ${files.length}`);
    const payload = await apiUploadPost<BatchAnalyzeResponse>("/api/upload/batch", batchUploadForm(files));
    renderBatch(payload);
    logAction("Batch Analyze Succeeded", `Files: ${payload.file_count}, Succeeded: ${payload.succeeded_count}, Failed: ${payload.failed_count}`);
  } catch (error) {
    batchSummary.textContent = errorMessage(error);
    batchResultsBody.innerHTML = `<tr><td colspan="8" class="muted">Batch analysis failed.</td></tr>`;
    logAction("Batch Analyze Failed", `Error: ${errorMessage(error)}`);
  }
}

async function runSweep(): Promise<void> {
  latestSweep = null;
  downloadSweepButton.disabled = true;
  downloadSweepReportButton.disabled = true;
  sweepSummary.textContent = "Running threshold sweep...";
  sweepResultsBody.innerHTML = `<tr><td colspan="7" class="muted">Running sweep...</td></tr>`;
  let usedUpload = false;
  try {
    const source = resolveStackSource();
    usedUpload = source.kind === "file";
    logAction(
      "Threshold Sweep Started",
      source.kind === "file" ? `File "${source.file.name}"` : `Local path "${source.path}"`
    );
    let payload: SweepResponse;
    if (source.kind === "path") {
      payload = await apiPost<SweepResponse>("/api/sweep", {
        path: source.path,
        start: readNumber("sweep-start"),
        stop: readNumber("sweep-stop"),
        step: readNumber("sweep-step"),
        profile: readProfile(),
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange(),
        include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
        prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked
      });
    } else {
      const stackId = await ensureUploadSession(source.file);
      payload = await apiPost<SweepResponse>("/api/sweep", {
        stack_id: stackId,
        start: readNumber("sweep-start"),
        stop: readNumber("sweep-stop"),
        step: readNumber("sweep-step"),
        profile: readProfile(),
        voxel: readVoxel(),
        roi: readRoi(),
        z_range: readZRange(),
        include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
        prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked
      });
    }
    renderSweep(payload);
    logAction("Threshold Sweep Succeeded", `Source: "${payload.source_path}", Thresholds tested: ${payload.threshold_count}`);
  } catch (error) {
    const msg = errorMessage(error, usedUpload ? "upload" : "general");
    sweepSummary.textContent = msg;
    sweepResultsBody.innerHTML = `<tr><td colspan="7" class="muted">Sweep failed.</td></tr>`;
    logAction("Threshold Sweep Failed", `Error: ${msg}`);
  }
}

async function validateCsv(): Promise<void> {
  validationSummary.textContent = "Validating...";
  validationResultsBody.innerHTML = `<tr><td colspan="5" class="muted">Running validation...</td></tr>`;
  try {
    const expectedFile = selectedRequiredFile("expected-csv-input", "Reference CSV");
    const actualFile = selectedRequiredFile("actual-csv-input", "New CSV");
    logAction("CSV Validation Started", `Expected: "${expectedFile.name}", Actual: "${actualFile.name}"`);
    const payload = await apiUploadPost<ValidationResponse>("/api/upload/validate", validationUploadForm());
    renderValidation(payload);
    logAction("CSV Validation Succeeded", `Passed: ${payload.passed}, Rows compared: ${payload.compared_rows}, Differences: ${payload.differences.length}`);
  } catch (error) {
    validationSummary.textContent = errorMessage(error);
    validationResultsBody.innerHTML = `<tr><td colspan="5" class="muted">Validation failed.</td></tr>`;
    logAction("CSV Validation Failed", `Error: ${errorMessage(error)}`);
  }
}

function renderSweep(payload: SweepResponse): void {
  latestSweep = payload;
  downloadSweepButton.disabled = payload.rows.length === 0;
  downloadSweepReportButton.disabled = payload.rows.length === 0;
  sweepSummary.innerHTML = `
    <strong>${escapeHtml(payload.source_path)}</strong><br />
    Profile: ${escapeHtml(payload.profile)}<br />
    Thresholds: ${payload.threshold_count}<br />
    Best threshold: ${payload.best_threshold === null ? "" : formatNumber(payload.best_threshold)}<br />
    Voxel source: ${escapeHtml(payload.voxel_source)}
  `;

  if (payload.rows.length === 0) {
    sweepResultsBody.innerHTML = `<tr><td colspan="7" class="muted">No sweep rows returned.</td></tr>`;
    return;
  }

  sweepResultsBody.innerHTML = payload.rows
    .map(
      (row) => `
        <tr>
          <td>${formatUnknownNumber(row.threshold)}</td>
          <td>${formatUnknownNumber(row.valid_fraction)}</td>
          <td>${formatUnknownNumber(row.valid_frame_count)}</td>
          <td>${formatUnknownNumber(row.area_um2_mean)}</td>
          <td>${formatUnknownNumber(row.deformation_index_mean)}</td>
          <td>${formatUnknownNumber(row.circularity_mean)}</td>
          <td>${escapeHtml(String(row.warning_codes ?? ""))}</td>
        </tr>
      `
    )
    .join("");
}

function previewImageSource(payload: PreviewResponse): string {
  if (payload.image_url?.trim()) {
    const url = payload.image_url.trim();
    if (/^https?:\/\//i.test(url) || url.startsWith("/api/")) {
      return url;
    }
    return `/api/${url.replace(/^\/+/, "")}`;
  }
  if (payload.image_png_base64) {
    return `data:image/png;base64,${payload.image_png_base64}`;
  }
  throw new Error("Preview response did not contain an image.");
}

function formatThresholdMethodLabel(method: string): string {
  const m = (method || "").toLowerCase();
  if (m === "robust_otsu") {
    return "robust Otsu";
  }
  if (m === "otsu") {
    return "Otsu";
  }
  if (m === "percentile") {
    return "percentile";
  }
  if (m === "constant") {
    return "constant";
  }
  return method || "auto";
}

function formatSuggestionScopeLabel(scope: string): string {
  const s = (scope || "stack_sample").toLowerCase();
  if (s === "stack_sample") {
    return "stack sample";
  }
  if (s === "current_slice") {
    return "current slice";
  }
  if (s === "roi_current_slice") {
    return "ROI current slice";
  }
  return scope;
}

function formatRequestedThreshold(payload: PreviewResponse): string {
  const req = payload.requested_threshold;
  if (typeof req === "number" && Number.isFinite(req)) {
    return formatNumber(req);
  }
  const thr = payload.threshold;
  if (typeof thr === "number" && Number.isFinite(thr)) {
    return formatNumber(thr);
  }
  return "—";
}

function previewQualityCaption(payload: PreviewResponse): string {
  const quality = previewQualityOf(payload, selectedObjectSeed ? "provisional" : "exact");
  if (!selectedObjectSeed) {
    return "";
  }
  const requested = formatRequestedThreshold(payload);
  if (quality === "provisional") {
    return (
      `<br /><span class="preview-quality provisional">` +
      `Provisional overlay · requested threshold ${escapeHtml(requested)} · not the tracked contour` +
      `</span>`
    );
  }
  const sem = (payload.threshold_semantics || "").toLowerCase();
  const trackLost =
    sem === "seeded_unavailable" ||
    payload.method.includes("lost") ||
    payload.method.includes("fail") ||
    payload.method.includes("gap") ||
    payload.method.includes("reject") ||
    (payload.area_px2 === 0 && !payload.method.includes("hidden"));
  if (trackLost || sem === "seeded_unavailable") {
    return (
      `<br /><span class="preview-quality unavailable">` +
      `Exact result unavailable · requested ${escapeHtml(requested)}` +
      `</span>`
    );
  }
  const cacheNote = payload.cache_hit ? " · cache" : "";
  if (sem === "polar_ridge") {
    return (
      `<br /><span class="preview-quality exact">` +
      `Tracked contour · polar ridge (no scalar intensity gate) · requested ${escapeHtml(requested)}${cacheNote}` +
      `</span>`
    );
  }
  const eff = payload.effective_threshold;
  if (typeof eff === "number" && Number.isFinite(eff)) {
    return (
      `<br /><span class="preview-quality exact">` +
      `Tracked contour · effective threshold ${escapeHtml(formatNumber(eff))} (seeded adaptive) · requested ${escapeHtml(requested)}${cacheNote}` +
      `</span>`
    );
  }
  return (
    `<br /><span class="preview-quality exact">` +
    `Tracked contour (authoritative) · requested ${escapeHtml(requested)}${cacheNote}` +
    `</span>`
  );
}

function renderPreview(payload: PreviewResponse, renderedRoi: RectRoi | null): void {
  const sliceLabel = payload.frame_index + 1;
  const skeletonCaption = previewSkeletonCaption(payload);
  const qualityCaption = previewQualityCaption(payload);
  const seedCaption = selectedObjectSeed
    ? `<br /><span class="seed-label">${selectedObjectSeed.type === "polygon" ? "Polygon" : "Circle"} <b>Seed</b> (immutable selection): (${Math.round(selectedObjectSeed.x)}, ${Math.round(selectedObjectSeed.y)}) r=${Math.round(selectedObjectSeed.radius)} px · frame ${selectedObjectSeed.frame_index}</span>`
    : "";
  const trackedX = payload.tracked_center_x;
  const trackedY = payload.tracked_center_y;
  const hasTracked =
    payload.preview_quality === "exact" &&
    typeof trackedX === "number" &&
    typeof trackedY === "number" &&
    Number.isFinite(trackedX) &&
    Number.isFinite(trackedY);
  const trackedCaption = hasTracked
    ? `<br /><span class="tracked-center-label"><b>Tracked center</b> (current): (${Math.round(trackedX as number)}, ${Math.round(trackedY as number)}) · preview coords</span>`
    : selectedObjectSeed && payload.preview_quality === "exact"
      ? `<br /><span class="tracked-center-unavailable">Tracked center: unavailable on this slice</span>`
      : "";
  previewOutput.className = "preview-output";
  previewOutput.innerHTML = `
    <div class="preview-canvas">
      <img
        id="preview-image"
        src="${previewImageSource(payload)}"
        alt="Segmentation preview for slice ${sliceLabel} (frame index ${payload.frame_index})"
      />
      <div id="roi-selection" class="roi-selection" hidden></div>
      <div id="seed-selection" class="seed-selection" hidden></div>
      <svg id="tracked-center-overlay" class="tracked-center-overlay" hidden></svg>
      <svg id="polygon-overlay" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;" hidden></svg>
      <svg id="tracking-debug-overlay" class="tracking-debug-overlay" hidden></svg>
    </div>
    <div>
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Slice ${sliceLabel} (frame ${payload.frame_index}), ${escapeHtml(payload.method)} contour<br />
      Area ${formatNumber(payload.area_px2)} px2,
      perimeter ${formatNumber(payload.perimeter_px)} px,
      circularity ${formatNumber(payload.circularity)}
      ${skeletonCaption}
      ${qualityCaption}
      ${seedCaption}
      ${trackedCaption}
    </div>
  `;
  // Restore busy overlay / error banner if this generation still owns them
  // (innerHTML wiped DOM).
  syncBusyOverlayDom();
  paintExactPreviewErrorDom();
  attachPreviewRoiSelector(payload, renderedRoi);
  updateTrackingDebugOverlay(payload.frame_index, renderedRoi);
  applyOverlayVisibility(renderedRoi);
  drawTrackedCenterOverlay(payload, renderedRoi);
}

/** Show/hide circle ROI, XY crop box, and re-request preview when selection visibility changes. */
function applyOverlayVisibility(renderedRoi: RectRoi | null = null): void {
  const image = document.getElementById("preview-image") as HTMLImageElement | null;
  const seedSelection = document.getElementById("seed-selection") as HTMLDivElement | null;
  const roiSelection = document.getElementById("roi-selection") as HTMLDivElement | null;
  const poly = document.getElementById("polygon-overlay");

  if (!readShowCircleRoiOverlay()) {
    if (seedSelection) {
      seedSelection.hidden = true;
    }
    if (poly) {
      poly.setAttribute("hidden", "true");
    }
  } else if (image && selectedObjectSeed) {
    const paintCircle = () => {
      // Immutable user seed ROI — never moved to tracked center.
      drawPersistentCircleSeedOverlay(image, selectedObjectSeed!, renderedRoi ?? readRoi());
    };
    if (image.complete && image.naturalWidth > 0) {
      requestAnimationFrame(paintCircle);
    } else {
      image.addEventListener("load", () => requestAnimationFrame(paintCircle), { once: true });
    }
  }

  if (!readShowXyRoiOverlay() && roiSelection) {
    roiSelection.hidden = true;
  }
}

/** Distinct cyan/magenta crosshair for current tracked center (exact only). */
function drawTrackedCenterOverlay(
  payload: PreviewResponse,
  renderedRoi: RectRoi | null
): void {
  const overlay = document.getElementById("tracked-center-overlay") as SVGSVGElement | null;
  const image = document.getElementById("preview-image") as HTMLImageElement | null;
  if (!overlay || !image) {
    return;
  }
  const x = payload.tracked_center_x;
  const y = payload.tracked_center_y;
  const show =
    payload.preview_quality === "exact" &&
    typeof x === "number" &&
    typeof y === "number" &&
    Number.isFinite(x) &&
    Number.isFinite(y) &&
    (lastTrackedCenter === null ||
      lastTrackedCenter.gen === previewRequestGen);
  if (!show) {
    overlay.setAttribute("hidden", "true");
    overlay.innerHTML = "";
    return;
  }
  const paint = () => {
    const roiOffsetX = renderedRoi ? renderedRoi.xmin : 0;
    const roiOffsetY = renderedRoi ? renderedRoi.ymin : 0;
    // Payload centers are already in the preview-image (post-crop) frame.
    const clientPt = imageToClientPoint(x as number, y as number, image);
    void roiOffsetX;
    void roiOffsetY;
    overlay.removeAttribute("hidden");
    overlay.innerHTML = `
      <circle cx="${clientPt.x}" cy="${clientPt.y}" r="6" class="tracked-center-marker" />
      <line x1="${clientPt.x - 10}" y1="${clientPt.y}" x2="${clientPt.x + 10}" y2="${clientPt.y}" class="tracked-center-cross" />
      <line x1="${clientPt.x}" y1="${clientPt.y - 10}" x2="${clientPt.x}" y2="${clientPt.y + 10}" class="tracked-center-cross" />
      <text x="${clientPt.x + 10}" y="${clientPt.y - 10}" class="tracked-center-text">tracked</text>
    `;
  };
  if (image.complete && image.naturalWidth > 0) {
    requestAnimationFrame(paint);
  } else {
    image.addEventListener("load", () => requestAnimationFrame(paint), { once: true });
  }
}

function wireOverlayToggles(): void {
  for (const id of ["show-circle-roi-overlay", "show-xy-roi-overlay", "show-selection-overlay"] as const) {
    const el = document.getElementById(id);
    if (!(el instanceof HTMLInputElement)) {
      continue;
    }
    el.addEventListener("change", () => {
      if (id === "show-selection-overlay") {
        // Contour/tint are baked into the PNG — re-render.
        schedulePreview();
        return;
      }
      applyOverlayVisibility(readRoi());
    });
  }
}

function previewSkeletonCaption(payload: PreviewResponse): string {
  const hasSkelUm = payload.skel_perimeter_um !== undefined && payload.skel_perimeter_um !== null;
  const hasSkelPx = payload.skel_perimeter_px !== undefined && payload.skel_perimeter_px !== null;
  if (hasSkelUm || hasSkelPx) {
    const parts: string[] = [];
    if (hasSkelUm) {
      parts.push(`${formatNumber(payload.skel_perimeter_um as number)} um`);
    }
    if (hasSkelPx) {
      parts.push(`${formatNumber(payload.skel_perimeter_px as number)} px`);
    }
    return `<br />Skeleton perimeter: ${parts.join(", ")}`;
  }
  if (readEnableSkeleton()) {
    return `<br /><span class="muted">Skeleton enabled</span>`;
  }
  return "";
}

function voxelSourceMarkup(source: string): string {
  if (source === "default") {
    return `<span class="voxel-source voxel-source-default">Voxel source: default (uncalibrated 1×1×1 µm)</span>`;
  }
  if (source === "override") {
    return `<span class="voxel-source voxel-source-override">Voxel source: manual override</span>`;
  }
  return `<span class="voxel-source voxel-source-metadata">Voxel source: ${escapeHtml(source)}</span>`;
}

function applyVoxelDefaultStyling(source: string): void {
  const voxelInputs = ["voxel-x", "voxel-y", "voxel-z"].map((id) => mustElement<HTMLInputElement>(id));
  const scary = source === "default";
  for (const input of voxelInputs) {
    input.classList.toggle("voxel-default-warning", scary);
  }
}

function updateTrackingDebugOverlay(frameIndex: number, renderedRoi: RectRoi | null): void {
  const overlay = document.getElementById("tracking-debug-overlay") as SVGSVGElement | null;
  const image = document.getElementById("preview-image") as HTMLImageElement | null;
  const enabled = mustElement<HTMLInputElement>("show-tracking-debug").checked;
  if (!overlay || !image || !enabled || !latestTracking) {
    if (overlay) {
      overlay.setAttribute("hidden", "true");
      overlay.innerHTML = "";
    }
    return;
  }
  const record = latestTracking.find((entry) => entry.frame_index === frameIndex);
  if (!record || !record.tracked || record.centroid_x === null || record.centroid_y === null) {
    overlay.setAttribute("hidden", "true");
    overlay.innerHTML = "";
    return;
  }
  const roiOffsetX = renderedRoi ? renderedRoi.xmin : 0;
  const roiOffsetY = renderedRoi ? renderedRoi.ymin : 0;
  const clientPt = imageToClientPoint(
    record.centroid_x - roiOffsetX,
    record.centroid_y - roiOffsetY,
    image
  );
  overlay.removeAttribute("hidden");
  overlay.innerHTML = `
    <circle cx="${clientPt.x}" cy="${clientPt.y}" r="5" class="tracking-centroid" />
    <text x="${clientPt.x + 8}" y="${clientPt.y - 8}" class="tracking-centroid-label">tracked</text>
  `;
}

function attachPreviewRoiSelector(payload: PreviewResponse, renderedRoi: RectRoi | null): void {
  const image = mustElement<HTMLImageElement>("preview-image");
  const selection = mustElement<HTMLDivElement>("roi-selection");
  const seedSelection = mustElement<HTMLDivElement>("seed-selection");
  let start: { x: number; y: number; clientX: number; clientY: number } | null = null;

  image.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    
    const rect = image.getBoundingClientRect();
    const tool = mustElement<HTMLSelectElement>("object-seed-tool").value;

    if (selectObjectMode && tool === "polygon") {
      // Polygon drawing mode click
      const clickX = event.clientX - rect.left;
      const clickY = event.clientY - rect.top;
      
      const imgPt = clientToImagePoint(event.clientX, event.clientY, image);

      if (polygonClosed) {
        polygonPoints = [];
        polygonClosed = false;
      }

      // Check if clicking near the first point to close it (if >= 3 points exist)
      if (polygonPoints.length >= 3) {
        const firstClientPt = imageToClientPoint(polygonPoints[0].imgX, polygonPoints[0].imgY, image);
        const dist = Math.sqrt((clickX - firstClientPt.x) ** 2 + (clickY - firstClientPt.y) ** 2);
        if (dist < 10) {
          closeAndApplyPolygon(image, payload, renderedRoi);
          return;
        }
      }

      polygonPoints.push({ imgX: imgPt.x, imgY: imgPt.y });
      updatePolygonOverlay(image);
      return;
    }

    // Normal circle seed or ROI crop drag selection
    start = pointerToClientPoint(event, image);
    image.setPointerCapture(event.pointerId);
    if (!selectObjectMode) {
      drawSelection(selection, start.x, start.y, start.x, start.y);
    } else {
      drawSeedSelection(seedSelection, start.x, start.y, 0);
    }
  });

  image.addEventListener("pointermove", (event) => {
    const tool = mustElement<HTMLSelectElement>("object-seed-tool").value;
    if (selectObjectMode && tool === "polygon") {
      if (polygonPoints.length > 0 && !polygonClosed) {
        updatePolygonOverlay(image, { x: event.clientX, y: event.clientY });
      }
      return;
    }

    if (!start) {
      return;
    }
    const current = pointerToClientPoint(event, image);
    if (!selectObjectMode) {
      drawSelection(selection, start.x, start.y, current.x, current.y);
    } else {
      const radius = Math.sqrt((current.x - start.x) ** 2 + (current.y - start.y) ** 2);
      drawSeedSelection(seedSelection, start.x, start.y, radius);
    }
  });

  image.addEventListener("pointerup", (event) => {
    const tool = mustElement<HTMLSelectElement>("object-seed-tool").value;
    if (selectObjectMode && tool === "polygon") {
      return;
    }

    if (!start) {
      return;
    }
    const end = pointerToClientPoint(event, image);
    image.releasePointerCapture(event.pointerId);

    if (selectObjectMode) {
      const radiusClient = Math.sqrt((end.x - start.x) ** 2 + (end.y - start.y) ** 2);
      // Fiji-style circle: require a real drag so tiny clicks don't invent r≈10.
      if (radiusClient < MIN_CIRCLE_DRAG_CLIENT_PX) {
        start = null;
        seedSelection.hidden = true;
        const status = mustElement<HTMLSpanElement>("object-seed-status");
        status.textContent = "Drag to set circle radius";
        status.className = "inline-status warn";
        return;
      }
      const radiusImg = Math.max(1, clientRadiusToImageRadius(radiusClient, image));
      mustElement<HTMLInputElement>("object-seed-radius").value = String(Math.round(radiusImg));
      applyObjectSeedClick(start, image, payload, renderedRoi, radiusImg);
      start = null;
      // Overlay stays until Clear / next re-render redraws from selectedObjectSeed.
      return;
    }

    applyDraggedRoi(start, end, image, renderedRoi);
    start = null;
  });

  image.addEventListener("pointercancel", () => {
    start = null;
    selection.hidden = true;
    seedSelection.hidden = true;
  });

  image.addEventListener("dblclick", (event) => {
    const tool = mustElement<HTMLSelectElement>("object-seed-tool").value;
    if (selectObjectMode && tool === "polygon") {
      event.preventDefault();
      if (polygonPoints.length >= 3) {
        closeAndApplyPolygon(image, payload, renderedRoi);
      }
    }
  });
}

function pointerToClientPoint(event: PointerEvent, image: HTMLImageElement): { x: number; y: number; clientX: number; clientY: number } {
  const rect = image.getBoundingClientRect();
  return {
    x: clamp(event.clientX - rect.left, 0, rect.width),
    y: clamp(event.clientY - rect.top, 0, rect.height),
    clientX: event.clientX,
    clientY: event.clientY
  };
}

function clientToImagePoint(
  clientX: number,
  clientY: number,
  image: HTMLImageElement
): { x: number; y: number } {
  const rect = image.getBoundingClientRect();
  const style = window.getComputedStyle(image);

  const borderLeft = parseFloat(style.borderLeftWidth) || 0;
  const borderTop = parseFloat(style.borderTopWidth) || 0;
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingTop = parseFloat(style.paddingTop) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  const paddingBottom = parseFloat(style.paddingBottom) || 0;

  // content-box dimensions
  const wBox = image.clientWidth - paddingLeft - paddingRight;
  const hBox = image.clientHeight - paddingTop - paddingBottom;

  const wSrc = image.naturalWidth || image.width;
  const hSrc = image.naturalHeight || image.height;

  if (wBox <= 0 || hBox <= 0 || wSrc <= 0 || hSrc <= 0) {
    return { x: 0, y: 0 };
  }

  // contain logic
  const scale = Math.min(wBox / wSrc, hBox / hSrc);
  const wRendered = wSrc * scale;
  const hRendered = hSrc * scale;

  const xOffset = (wBox - wRendered) / 2;
  const yOffset = (hBox - hRendered) / 2;

  // Viewport client coord to content-box relative
  const xContent = clientX - rect.left - borderLeft - paddingLeft;
  const yContent = clientY - rect.top - borderTop - paddingTop;

  const xImg = Math.round((xContent - xOffset) / scale);
  const yImg = Math.round((yContent - yOffset) / scale);

  return {
    x: clamp(xImg, 0, wSrc - 1),
    y: clamp(yImg, 0, hSrc - 1)
  };
}

function imageToClientPoint(
  imgX: number,
  imgY: number,
  image: HTMLImageElement
): { x: number; y: number } {
  const style = window.getComputedStyle(image);

  const borderLeft = parseFloat(style.borderLeftWidth) || 0;
  const borderTop = parseFloat(style.borderTopWidth) || 0;
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingTop = parseFloat(style.paddingTop) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  const paddingBottom = parseFloat(style.paddingBottom) || 0;

  const wBox = image.clientWidth - paddingLeft - paddingRight;
  const hBox = image.clientHeight - paddingTop - paddingBottom;

  const wSrc = image.naturalWidth || image.width;
  const hSrc = image.naturalHeight || image.height;

  if (wBox <= 0 || hBox <= 0 || wSrc <= 0 || hSrc <= 0) {
    return { x: 0, y: 0 };
  }

  const scale = Math.min(wBox / wSrc, hBox / hSrc);
  const wRendered = wSrc * scale;
  const hRendered = hSrc * scale;

  const xOffset = (wBox - wRendered) / 2;
  const yOffset = (hBox - hRendered) / 2;

  const xContent = imgX * scale + xOffset;
  const yContent = imgY * scale + yOffset;

  return {
    x: xContent + borderLeft + paddingLeft,
    y: yContent + borderTop + paddingTop
  };
}

function updatePolygonOverlay(image: HTMLImageElement, currentPointerClient?: { x: number; y: number }): void {
  const svg = document.getElementById("polygon-overlay") as unknown as SVGElement | null;
  if (!svg) return;

  svg.innerHTML = "";
  if (polygonPoints.length === 0) {
    svg.setAttribute("hidden", "true");
    return;
  }
  svg.removeAttribute("hidden");

  // Draw lines
  let pathD = "";
  polygonPoints.forEach((pt, idx) => {
    const clientPt = imageToClientPoint(pt.imgX, pt.imgY, image);
    if (idx === 0) {
      pathD += `M ${clientPt.x} ${clientPt.y}`;
    } else {
      pathD += ` L ${clientPt.x} ${clientPt.y}`;
    }
  });

  if (currentPointerClient && !polygonClosed) {
    // draw line to current cursor
    const rect = image.getBoundingClientRect();
    const relativeX = currentPointerClient.x - rect.left;
    const relativeY = currentPointerClient.y - rect.top;
    pathD += ` L ${relativeX} ${relativeY}`;
  }

  if (polygonClosed && polygonPoints.length >= 3) {
    pathD += " Z";
  }

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", pathD);
  path.setAttribute("fill", polygonClosed ? "rgba(255, 220, 0, 0.2)" : "none");
  path.setAttribute("stroke", "#ffd700");
  path.setAttribute("stroke-width", "2");
  svg.appendChild(path);

  // Draw circles for points
  polygonPoints.forEach((pt) => {
    const clientPt = imageToClientPoint(pt.imgX, pt.imgY, image);
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(clientPt.x));
    circle.setAttribute("cy", String(clientPt.y));
    circle.setAttribute("r", "4");
    circle.setAttribute("fill", "#ffd700");
    circle.setAttribute("stroke", "#000");
    circle.setAttribute("stroke-width", "1");
    svg.appendChild(circle);
  });
}

function clientRadiusToImageRadius(radiusClient: number, image: HTMLImageElement): number {
  const scale = imageDisplayScale(image);
  if (scale <= 0) {
    return radiusClient;
  }
  return radiusClient / scale;
}

function imageRadiusToClientRadius(radiusImg: number, image: HTMLImageElement): number {
  const scale = imageDisplayScale(image);
  if (scale <= 0) {
    return radiusImg;
  }
  return radiusImg * scale;
}

/** CSS-pixel scale for object-fit:contain preview (isotropic). */
function imageDisplayScale(image: HTMLImageElement): number {
  const style = window.getComputedStyle(image);
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingTop = parseFloat(style.paddingTop) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  const paddingBottom = parseFloat(style.paddingBottom) || 0;
  const wBox = image.clientWidth - paddingLeft - paddingRight;
  const hBox = image.clientHeight - paddingTop - paddingBottom;
  const wSrc = image.naturalWidth || image.width;
  const hSrc = image.naturalHeight || image.height;
  if (wBox <= 0 || hBox <= 0 || wSrc <= 0 || hSrc <= 0) {
    return 0;
  }
  return Math.min(wBox / wSrc, hBox / hSrc);
}

function drawSelection(selection: HTMLDivElement, startX: number, startY: number, endX: number, endY: number): void {
  const left = Math.min(startX, endX);
  const top = Math.min(startY, endY);
  const width = Math.abs(endX - startX);
  const height = Math.abs(endY - startY);
  selection.hidden = false;
  selection.style.left = `${left}px`;
  selection.style.top = `${top}px`;
  selection.style.width = `${width}px`;
  selection.style.height = `${height}px`;
}

function drawSeedSelection(selection: HTMLDivElement, centerX: number, centerY: number, radius: number): void {
  const r = Math.max(0, radius);
  if (r < 1 || !Number.isFinite(centerX) || !Number.isFinite(centerY)) {
    selection.hidden = true;
    return;
  }
  selection.hidden = false;
  selection.style.left = `${centerX - r}px`;
  selection.style.top = `${centerY - r}px`;
  selection.style.width = `${2 * r}px`;
  selection.style.height = `${2 * r}px`;
}

/** Yellow full-radius circle for a committed circle seed (not polygon). */
function drawPersistentCircleSeedOverlay(
  image: HTMLImageElement,
  seed: ObjectSeed,
  renderedRoi: RectRoi | null
): void {
  const seedSelection = document.getElementById("seed-selection") as HTMLDivElement | null;
  if (!seedSelection) {
    return;
  }
  if (seed.type === "polygon") {
    seedSelection.hidden = true;
    return;
  }
  // Image not laid out yet → skip (caller retries on load).
  if (image.naturalWidth <= 0 || image.clientWidth <= 0) {
    seedSelection.hidden = true;
    return;
  }
  const scale = imageDisplayScale(image);
  if (scale <= 0) {
    seedSelection.hidden = true;
    return;
  }
  const roiOffsetX = renderedRoi?.xmin ?? 0;
  const roiOffsetY = renderedRoi?.ymin ?? 0;
  const clientPt = imageToClientPoint(seed.x - roiOffsetX, seed.y - roiOffsetY, image);
  const radiusClient = imageRadiusToClientRadius(seed.radius, image);
  // Clamp to image box so a bad seed never paints a page-sized circle.
  const maxR = Math.max(image.clientWidth, image.clientHeight);
  drawSeedSelection(seedSelection, clientPt.x, clientPt.y, Math.min(radiusClient, maxR));
}

function hideCircleSeedOverlay(): void {
  const seedSelection = document.getElementById("seed-selection") as HTMLDivElement | null;
  if (seedSelection) {
    seedSelection.hidden = true;
  }
}

function applyDraggedRoi(
  start: { x: number; y: number; clientX: number; clientY: number },
  end: { x: number; y: number; clientX: number; clientY: number },
  image: HTMLImageElement,
  renderedRoi: RectRoi | null
): void {
  const rect = image.getBoundingClientRect();
  const dragWidth = Math.abs(end.x - start.x);
  const dragHeight = Math.abs(end.y - start.y);
  if (dragWidth < 4 || dragHeight < 4 || rect.width <= 0 || rect.height <= 0) {
    mustElement<HTMLDivElement>("roi-selection").hidden = true;
    return;
  }

  const startImg = clientToImagePoint(start.clientX, start.clientY, image);
  const endImg = clientToImagePoint(end.clientX, end.clientY, image);

  const baseX = renderedRoi?.xmin ?? 0;
  const baseY = renderedRoi?.ymin ?? 0;
  
  const xmin = baseX + Math.min(startImg.x, endImg.x);
  const xmax = baseX + Math.max(startImg.x, endImg.x);
  const ymin = baseY + Math.min(startImg.y, endImg.y);
  const ymax = baseY + Math.max(startImg.y, endImg.y);

  setRoiFields({
    xmin,
    xmax: Math.max(xmax, xmin + 1),
    ymin,
    ymax: Math.max(ymax, ymin + 1)
  });
  schedulePreview();
}

function applyObjectSeedClick(
  point: { clientX: number; clientY: number },
  image: HTMLImageElement,
  payload: PreviewResponse,
  renderedRoi: RectRoi | null,
  radiusImg: number
): void {
  const rect = image.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  const pointImg = clientToImagePoint(point.clientX, point.clientY, image);

  const baseX = renderedRoi?.xmin ?? 0;
  const baseY = renderedRoi?.ymin ?? 0;
  const imgX = baseX + pointImg.x;
  const imgY = baseY + pointImg.y;

  const maxDistVal = parseFloat(mustElement<HTMLInputElement>("object-seed-max-dist").value);
  const max_tracking_dist_um = isNaN(maxDistVal) ? undefined : maxDistVal;

  selectedObjectSeed = {
    x: imgX,
    y: imgY,
    frame_index: payload.frame_index,
    radius: radiusImg,
    max_tracking_dist_um,
    type: "circle",
    seed_origin: "ui_2d",
    radius_unit: "px",
    source_revision: lastDisplayLevelPayload?.display_volume_spec?.source_revision ?? null
  };
  selectObjectMode = false;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = "Select Object";
  btn.classList.remove("active");
  updateObjectSeedStatus();
  syncVolumeSeedMarkerFromSelection();
  logAction("Set Object Seed", `Coordinate (${imgX}, ${imgY}) r=${Math.round(radiusImg)} on frame ${payload.frame_index}`);
  void previewStack();
}

function closeAndApplyPolygon(image: HTMLImageElement, payload: PreviewResponse, renderedRoi: RectRoi | null): void {
  polygonClosed = true;
  updatePolygonOverlay(image);

  const xs = polygonPoints.map(p => p.imgX);
  const ys = polygonPoints.map(p => p.imgY);
  const centroidX = xs.reduce((a, b) => a + b, 0) / xs.length;
  const centroidY = ys.reduce((a, b) => a + b, 0) / ys.length;
  const maxDist = Math.max(...polygonPoints.map(p => Math.sqrt((p.imgX - centroidX)**2 + (p.imgY - centroidY)**2)));

  const maxDistVal = parseFloat(mustElement<HTMLInputElement>("object-seed-max-dist").value);
  const max_tracking_dist_um = isNaN(maxDistVal) ? undefined : maxDistVal;

  const baseX = renderedRoi?.xmin ?? 0;
  const baseY = renderedRoi?.ymin ?? 0;

  selectedObjectSeed = {
    x: baseX + centroidX,
    y: baseY + centroidY,
    frame_index: payload.frame_index,
    radius: maxDist,
    max_tracking_dist_um,
    type: "polygon",
    points: polygonPoints.map(p => ({ x: baseX + p.imgX, y: baseY + p.imgY }))
  };

  selectObjectMode = false;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = "Select Object";
  btn.classList.remove("active");
  updateObjectSeedStatus();
  logAction("Set Object Seed (Polygon)", `Polygon with ${polygonPoints.length} vertices, centroid (${Math.round(centroidX)}, ${Math.round(centroidY)}) on frame ${payload.frame_index}`);
  void previewStack();
}

function clearObjectSeed(): void {
  selectedObjectSeed = null;
  polygonPoints = [];
  polygonClosed = false;
  lastTrackedCenter = null;
  lastExactPreviewError = null;
  exactPendingGen = null;
  busyOwner = null;
  hidePreviewBusyOverlayDom();
  paintExactPreviewErrorDom();
  const overlay = document.getElementById("polygon-overlay");
  if (overlay) {
    overlay.innerHTML = "";
    overlay.setAttribute("hidden", "true");
  }
  hideCircleSeedOverlay();
  selectObjectMode = false;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = "Select Object";
  btn.classList.remove("active");
  volumeSession?.clearSeedMarker();
  volumeSeedPickMode = false;
  volumeSession?.setSeedPickEnabled(false);
  updateVolumeSeedPickButton();
  updateObjectSeedStatus();
  logAction("Clear Object Seed", "User cleared the selected object seed.");
  void previewStack();
}

function updateObjectSeedStatus(): void {
  const status = mustElement<HTMLSpanElement>("object-seed-status");
  if (selectObjectMode) {
    const tool = mustElement<HTMLSelectElement>("object-seed-tool").value;
    if (tool === "polygon") {
      status.textContent = "Click points on preview to draw polygon. Double-click to finish.";
    } else {
      status.textContent =
        "Drag a circle that encloses the vesicle (Fiji-style). Click-only is not enough.";
    }
    status.className = "inline-status warn";
  } else if (selectedObjectSeed) {
    const origin =
      selectedObjectSeed.seed_origin === "viewer_3d" ? " · from 3D" : selectedObjectSeed.seed_origin === "ui_2d" ? " · from 2D" : "";
    if (selectedObjectSeed.type === "polygon") {
      status.textContent = `Polygon ROI: center (${Math.round(selectedObjectSeed.x)}, ${Math.round(selectedObjectSeed.y)}) r=${Math.round(selectedObjectSeed.radius)} px · frame ${selectedObjectSeed.frame_index}${origin}`;
    } else {
      status.textContent = `Circle ROI: center (${Math.round(selectedObjectSeed.x)}, ${Math.round(selectedObjectSeed.y)}) r=${Math.round(selectedObjectSeed.radius)} px · frame ${selectedObjectSeed.frame_index}${origin}`;
    }
    status.className = "inline-status ok";
  } else {
    const profile = mustElement<HTMLSelectElement>("profile-input").value;
    if (profile === "active_surfaces") {
      status.textContent = "Select Object required for Experimental mode";
      status.className = "inline-status warn";
    } else {
      // Multi-object fields: without a seed Standard/RBC grab largest blob.
      status.textContent = "Select Object recommended (else largest blob is used)";
      status.className = "inline-status warn";
    }
  }
}

function updateFrameRange(): void {
  const count = effectivePreviewFrameCount();
  const maxFrame = count - 1;
  frameSlider.max = String(maxFrame);
  frameInput.max = String(maxFrame);
  const clamped = clamp(Math.trunc(Number(frameInput.value) || 0), 0, maxFrame);
  frameInput.value = String(clamped);
  frameSlider.value = String(clamped);
  updateFrameSliceLabel();
}

function updateFrameSliceLabel(): void {
  const label = document.getElementById("frame-slice-label");
  if (!label) {
    return;
  }
  const count = Math.max(1, effectivePreviewFrameCount());
  const n = clamp(Math.trunc(Number(frameInput.value) || 0), 0, count - 1);
  label.textContent = `Slice ${n + 1} of ${count}`;
}

function syncZRangeControls(options: { initializeFullRange?: boolean } = {}): void {
  const count = Math.max(1, inspectedFrameCount ?? 1);
  zStartSlider.max = String(Math.max(0, count - 1));
  zStopSlider.max = String(count);

  if (options.initializeFullRange || (zMinInput.value.trim() === "" && zMaxInput.value.trim() === "")) {
    zMinInput.value = "0";
    zMaxInput.value = String(count);
  }

  try {
    const zRange = readZRange();
    if (zRange) {
      const start = clamp(zRange.zmin, 0, Math.max(0, count - 1));
      const stop = clamp(zRange.zmax, start + 1, count);
      zMinInput.value = String(start);
      zMaxInput.value = String(stop);
      zStartSlider.value = String(start);
      zStopSlider.value = String(stop);
      zRangeStatus.textContent = `Using slices ${start + 1}–${stop} of ${count} (API indices ${start}..${stop - 1})`;
      zRangeStatus.className = "inline-status";
      logAction("Set Z Range", `Using slices ${start + 1}–${stop} of ${count} (API indices ${start}..${stop - 1})`);
    }
  } catch (error) {
    zRangeStatus.textContent = errorMessage(error);
    zRangeStatus.className = "inline-status warn";
  }
  updateFrameRange();
}

function useFullFrameRange(): void {
  const count = Math.max(1, inspectedFrameCount ?? 1);
  zMinInput.value = "0";
  zMaxInput.value = String(count);
  syncZRangeControls();
}

function effectivePreviewFrameCount(): number {
  const fallbackCount = inspectedFrameCount ?? 1;
  try {
    const zRange = readZRange();
    if (zRange) {
      return Math.max(1, zRange.zmax - zRange.zmin);
    }
  } catch {
    return Math.max(1, fallbackCount);
  }
  return Math.max(1, fallbackCount);
}

function syncFrameSliderToInput(): void {
  const maxFrame = Number(frameSlider.max);
  const clamped = clamp(Math.trunc(Number(frameInput.value) || 0), 0, Number.isFinite(maxFrame) ? maxFrame : 0);
  frameSlider.value = String(clamped);
}

function setRoiFields(roi: RectRoi): void {
  mustElement<HTMLInputElement>("roi-xmin").value = String(roi.xmin);
  mustElement<HTMLInputElement>("roi-xmax").value = String(roi.xmax);
  mustElement<HTMLInputElement>("roi-ymin").value = String(roi.ymin);
  mustElement<HTMLInputElement>("roi-ymax").value = String(roi.ymax);
  updateRoiStatus();
  logAction("Set ROI", `${roi.xmin}:${roi.xmax}, ${roi.ymin}:${roi.ymax}`);
}

function clearRoiFields(): void {
  ["roi-xmin", "roi-xmax", "roi-ymin", "roi-ymax"].forEach((id) => {
    mustElement<HTMLInputElement>(id).value = "";
  });
  const selection = document.getElementById("roi-selection");
  if (selection instanceof HTMLDivElement) {
    selection.hidden = true;
  }
  updateRoiStatus();
  logAction("Clear ROI", "Reset ROI bounds to full XY frame.");
}

function updateRoiStatus(): void {
  try {
    const roi = readRoi();
    if (roi) {
      roiStatus.textContent = `ROI active — analysis limited to this box (${roi.xmin}:${roi.xmax}, ${roi.ymin}:${roi.ymax})`;
      roiStatus.className = "inline-status ok";
    } else {
      roiStatus.textContent = "Full field — largest object auto-selected";
      roiStatus.className = "inline-status";
    }
  } catch (error) {
    roiStatus.textContent = errorMessage(error);
    roiStatus.className = "inline-status warn";
  }
}

function renderMeshPreview(payload: MeshPreviewResponse): void {
  if (!payload.has_mesh || payload.vertices.length === 0 || payload.faces.length === 0) {
    latestMeshPreview = null;
    meshOutput.textContent = selectedObjectSeed
      ? "No 3D mesh for the selected object. Check threshold, seed position/radius, and slice range."
      : "No 3D mesh could be created. Try Select Object, adjust threshold, or tighten ROI/Z range.";
    meshOutput.className = "mesh-output muted";
    return;
  }

  latestMeshPreview = payload;
  const srcV = payload.source_vertex_count ?? payload.vertex_count;
  const srcF = payload.source_face_count ?? payload.face_count;
  const method = payload.display_method ?? payload.result_authority?.display_method ?? "weld_compact";
  meshOutput.className = "mesh-output";
  meshOutput.innerHTML = `
    <div>
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      <span class="inline-status warn">Display mesh only (${escapeHtml(method)}) — not a scientific full export</span><br />
      Display: ${payload.vertex_count} vertices, ${payload.face_count} faces
      (source complete ${srcV} v / ${srcF} f), sampling x${payload.downsample}<br />
      View: calibrated, unaligned contour stack<br />
      Scientific surface area ${formatNumber(payload.surface_area_um2)} um2,
      scientific volume ${formatNumber(payload.volume_um3)} um3,
      sphericity ${formatNumber(payload.sphericity)}
      <span class="muted">(measured on complete mesh before display weld/compact)</span>
    </div>
    <div class="button-row mesh-export-row">
      <button id="download-mesh-obj-btn" class="secondary" type="button">Display OBJ</button>
      <button id="download-mesh-stl-btn" class="secondary" type="button">Display STL</button>
      <button id="download-mesh-ply-btn" class="secondary" type="button">Display PLY</button>
      <button id="download-mesh-glb-btn" class="secondary" type="button">Display GLB</button>
      <button id="download-mesh-html-btn" class="secondary" type="button">Display HTML</button>
      <span class="inline-status muted">Downloads are display/preview geometry only. Full scientific export uses server mesh-export (complete mesh).</span>
    </div>
    <iframe id="mesh-frame" title="3D display mesh preview"></iframe>
  `;
  mustElement<HTMLIFrameElement>("mesh-frame").srcdoc = meshPreviewHtml(payload);
  mustElement<HTMLButtonElement>("download-mesh-obj-btn").addEventListener("click", () => {
    downloadLatestMeshFile("obj");
  });
  mustElement<HTMLButtonElement>("download-mesh-stl-btn").addEventListener("click", () => {
    downloadLatestMeshFile("stl");
  });
  mustElement<HTMLButtonElement>("download-mesh-ply-btn").addEventListener("click", () => {
    downloadLatestMeshFile("ply");
  });
  mustElement<HTMLButtonElement>("download-mesh-glb-btn").addEventListener("click", () => {
    downloadLatestMeshFile("glb");
  });
  mustElement<HTMLButtonElement>("download-mesh-html-btn").addEventListener("click", () => {
    downloadLatestMeshHtml();
  });
}

function meshPreviewHtml(payload: MeshPreviewResponse): string {
  const bounds = meshBounds(payload.vertices);
  const x = payload.vertices.map((vertex) => vertex[0] - bounds.xmin);
  const y = payload.vertices.map((vertex) => vertex[1] - bounds.ymin);
  const z = payload.vertices.map((vertex) => vertex[2] - bounds.zmin);
  const i = payload.faces.map((face) => face[0]);
  const j = payload.faces.map((face) => face[1]);
  const k = payload.faces.map((face) => face[2]);
  const title = payload.source_path.split(/[\\/]/).pop() ?? "MorphoStack mesh";
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)} — MorphoStack mesh</title>
  <style>
    html, body { width: 100%; height: 100%; margin: 0; background: #0f172a; color: #e5e7eb; font-family: system-ui, sans-serif; }
    #toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 8px 10px; background: #111827; border-bottom: 1px solid rgba(255,255,255,0.08); }
    #toolbar button, #toolbar label { font-size: 12px; }
    #toolbar button { background: #1f2937; color: #e5e7eb; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 4px 8px; cursor: pointer; }
    #toolbar button:hover { background: #374151; }
    #toolbar input[type="range"] { width: 120px; vertical-align: middle; }
    #plot { width: 100%; height: calc(100% - 44px); }
    .meta { font-size: 11px; color: #9ca3af; margin-left: auto; }
  </style>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>
  <div id="toolbar">
    <button type="button" data-camera="iso">Iso</button>
    <button type="button" data-camera="front">Front</button>
    <button type="button" data-camera="side">Side</button>
    <button type="button" data-camera="top">Top</button>
    <label>Opacity <input id="opacity-range" type="range" min="0.2" max="1" step="0.05" value="0.88" /></label>
    <button id="download-png-btn" type="button">Download PNG</button>
    <span class="meta">Display preview · scientific SA ${formatNumber(payload.surface_area_um2)} um2 · V ${formatNumber(payload.volume_um3)} um3 (complete mesh)</span>
  </div>
  <div id="plot"></div>
  <script>
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
    const layout = {
      margin: { l: 0, r: 0, t: 0, b: 0 },
      paper_bgcolor: "#0f172a",
      plot_bgcolor: "#0f172a",
      font: { color: "#e5e7eb" },
      scene: {
        aspectmode: "auto",
        xaxis: { title: "X (um)", nticks: 4, color: "#e5e7eb", gridcolor: "rgba(255,255,255,0.18)", backgroundcolor: "#111827" },
        yaxis: { title: "Y (um)", nticks: 4, color: "#e5e7eb", gridcolor: "rgba(255,255,255,0.18)", backgroundcolor: "#111827" },
        zaxis: { title: "Z (um)", nticks: 4, color: "#e5e7eb", gridcolor: "rgba(255,255,255,0.18)", backgroundcolor: "#111827" }
      }
    };
    const cameras = {
      iso: { eye: { x: 1.6, y: 1.6, z: 1.2 } },
      front: { eye: { x: 0, y: 2.2, z: 0 } },
      side: { eye: { x: 2.2, y: 0, z: 0 } },
      top: { eye: { x: 0, y: 0, z: 2.2 } }
    };
    Plotly.newPlot("plot", [trace], layout, { responsive: true, displaylogo: false });
    document.querySelectorAll("[data-camera]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-camera");
        if (!key || !cameras[key]) return;
        Plotly.relayout("plot", { "scene.camera": cameras[key] });
      });
    });
    document.getElementById("opacity-range").addEventListener("input", (event) => {
      const value = Number(event.target.value);
      Plotly.restyle("plot", { opacity: value });
    });
    document.getElementById("download-png-btn").addEventListener("click", async () => {
      const dataUrl = await Plotly.toImage("plot", { format: "png", width: 1400, height: 900, scale: 2 });
      const anchor = document.createElement("a");
      anchor.href = dataUrl;
      anchor.download = "morphostack-mesh.png";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    });
  </script>
</body>
</html>`;
}

function meshBounds(vertices: number[][]): {
  xmin: number;
  ymin: number;
  zmin: number;
} {
  return vertices.reduce(
    (bounds, vertex) => ({
      xmin: Math.min(bounds.xmin, vertex[0]),
      ymin: Math.min(bounds.ymin, vertex[1]),
      zmin: Math.min(bounds.zmin, vertex[2])
    }),
    { xmin: Number.POSITIVE_INFINITY, ymin: Number.POSITIVE_INFINITY, zmin: Number.POSITIVE_INFINITY }
  );
}

function syncExcludedFramesFromTable(): void {
  const next = new Set<number>();
  resultsBody.querySelectorAll<HTMLInputElement>("input[data-exclude-frame]").forEach((input) => {
    if (input.checked) {
      next.add(Number(input.dataset.excludeFrame));
    }
  });
  excludedFrameIndices = next;
}

function renderAnalysis(payload: AnalyzeResponse): void {
  latestAnalysis = payload;
  latestTracking = payload.tracking;
  downloadCsvButton.disabled = payload.rows.length === 0;
  downloadReportButton.disabled = false;
  downloadManifestButton.disabled = false;
  reanalyzeExcludedButton.disabled = payload.rows.length === 0;
  const meshText = payload.mesh
    ? `<br />3D mesh surface area: ${formatNumber(payload.mesh.surface_area_um2)} um2, mesh volume: ${formatNumber(payload.mesh.volume_um3)} um3, sphericity: ${formatNumber(payload.mesh.sphericity)}`
    : "";
  const sliceVolumeText = payload.slice_volume
    ? payload.slice_volume.volume_um3 === null
      ? `<br />Slice-integrated volume: withheld because contour coverage is incomplete.`
      : `<br />Slice-integrated volume (trapezoidal): ${formatNumber(payload.slice_volume.volume_um3)} um3${
          payload.slice_volume.relative_difference_from_mesh === null
            ? ""
            : `, mesh difference ${formatNumber(payload.slice_volume.relative_difference_from_mesh * 100)}%`
        }`
    : "";
  const warningText =
    payload.warnings.length > 0
      ? `<div class="warning-list">${payload.warnings.map((warning) => `<div><strong>${escapeHtml(warning.severity)}</strong>: ${escapeHtml(warning.message)}</div>`).join("")}</div>`
      : "";
  const summaryText = renderSummaryMetrics(payload.summary);
  analysisSummary.innerHTML = `
    <strong>${escapeHtml(payload.source_path)}</strong><br />
    Profile: ${escapeHtml(payload.profile)}<br />
    Frames: ${payload.frame_count}, valid: ${payload.valid_frame_count}${
      payload.excluded_frames && payload.excluded_frames.length > 0
        ? `, excluded: ${payload.excluded_frames.join(", ")}`
        : ""
    }<br />
    ${voxelSourceMarkup(payload.voxel_source)}${summaryText}${meshText}${sliceVolumeText}
    ${warningText}
  `;
  applyVoxelDefaultStyling(payload.voxel_source);
  updateTrackingDebugOverlay(globalPreviewFrameIndex(readLocalPreviewFrameIndex()), readRoi());

  const showSkelUm = payload.rows.some((row) => row.skel_perimeter_um !== undefined && row.skel_perimeter_um !== null);
  const showSkelPx = payload.rows.some((row) => row.skel_perimeter_px !== undefined && row.skel_perimeter_px !== null);
  const colCount = 12 + (showSkelUm ? 1 : 0) + (showSkelPx ? 1 : 0);
  const resultsTable = resultsBody.closest("table");
  const theadRow = resultsTable?.querySelector("thead tr");
  if (theadRow) {
    theadRow.innerHTML = `
      <th>Exclude</th>
      <th>Frame</th>
      <th>Method</th>
      <th>Contour</th>
      <th>Area (um2)</th>
      <th>Perimeter (um)</th>
      <th>Eq. diameter (um)</th>
      <th>Aspect</th>
      <th>Elongation</th>
      <th>Def. index</th>
      <th>Solidity</th>
      <th>Circularity</th>
      ${showSkelUm ? "<th>Skel perimeter (um)</th>" : ""}
      ${showSkelPx ? "<th>Skel perimeter (px)</th>" : ""}
    `;
  }

  if (payload.rows.length === 0) {
    resultsBody.innerHTML = `<tr><td colspan="${colCount}" class="muted">No rows returned.</td></tr>`;
    return;
  }

  resultsBody.innerHTML = payload.rows
    .map(
      (row) => `
        <tr class="${row.excluded ? "frame-excluded" : ""}">
          <td><input type="checkbox" data-exclude-frame="${row.frame_index}" ${row.excluded ? "checked" : ""} aria-label="Exclude frame ${row.frame_index}" /></td>
          <td>${row.frame_index}</td>
          <td>${escapeHtml(row.method)}</td>
          <td>${row.has_contour ? "yes" : "no"}</td>
          <td>${formatNumber(row.area_um2)}</td>
          <td>${formatNumber(row.perimeter_um)}</td>
          <td>${formatNumber(row.equivalent_diameter_um)}</td>
          <td>${formatNumber(row.aspect_ratio)}</td>
          <td>${formatNumber(row.elongation)}</td>
          <td>${formatNumber(row.deformation_index)}</td>
          <td>${formatNumber(row.solidity)}</td>
          <td>${formatNumber(row.circularity)}</td>
          ${showSkelUm ? `<td>${row.skel_perimeter_um !== undefined && row.skel_perimeter_um !== null ? formatNumber(row.skel_perimeter_um) : "—"}</td>` : ""}
          ${showSkelPx ? `<td>${row.skel_perimeter_px !== undefined && row.skel_perimeter_px !== null ? formatNumber(row.skel_perimeter_px) : "—"}</td>` : ""}
        </tr>
      `
    )
    .join("");
}

function renderSummaryMetrics(summary: AnalysisSummary): string {
  const area = summary.metrics.area_um2;
  const circularity = summary.metrics.circularity;
  const diameter = summary.metrics.equivalent_diameter_um;
  if (!area && !circularity && !diameter) {
    return "";
  }
  const parts: string[] = [];
  if (area) {
    parts.push(`mean area ${formatNumber(area.mean)} um2`);
  }
  if (diameter) {
    parts.push(`mean eq. diameter ${formatNumber(diameter.mean)} um`);
  }
  if (circularity) {
    parts.push(`mean circularity ${formatNumber(circularity.mean)}`);
  }
  return `<br />Summary: ${parts.join(", ")}`;
}

function renderBatch(payload: BatchAnalyzeResponse): void {
  latestBatch = payload;
  downloadBatchButton.disabled = payload.rows.length === 0;
  downloadBatchReportButton.disabled = payload.rows.length === 0;
  batchSummary.innerHTML = `
    Files: ${payload.file_count}<br />
    Succeeded: ${payload.succeeded_count}, failed: ${payload.failed_count}
  `;

  if (payload.rows.length === 0) {
    batchResultsBody.innerHTML = `<tr><td colspan="8" class="muted">No batch rows returned.</td></tr>`;
    return;
  }

  batchResultsBody.innerHTML = payload.rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(String(row.source_path ?? ""))}</td>
          <td>${escapeHtml(String(row.status ?? ""))}</td>
          <td>${escapeHtml(String(row.profile ?? ""))}</td>
          <td>${formatUnknownNumber(row.frame_count)}</td>
          <td>${formatUnknownNumber(row.valid_frame_count)}</td>
          <td>${formatUnknownNumber(row.area_um2_mean)}</td>
          <td>${formatUnknownNumber(row.deformation_index_mean)}</td>
          <td>${formatUnknownNumber(row.circularity_mean)}</td>
        </tr>
      `
    )
    .join("");
}

function renderValidation(payload: ValidationResponse): void {
  validationSummary.className = payload.passed ? "output validation-pass" : "output validation-fail";
  validationSummary.innerHTML = `
    Result: <strong>${payload.passed ? "PASS" : "FAIL"}</strong><br />
    Reference: ${escapeHtml(payload.expected_path)}<br />
    New: ${escapeHtml(payload.actual_path)}<br />
    Rows compared: ${payload.compared_rows}, cells compared: ${payload.compared_cells}, tolerance: ${formatNumber(payload.tolerance)}
  `;

  if (payload.differences.length === 0) {
    validationResultsBody.innerHTML = `<tr><td colspan="5" class="muted">No differences found.</td></tr>`;
    return;
  }

  validationResultsBody.innerHTML = payload.differences
    .slice(0, 20)
    .map(
      (difference) => `
        <tr>
          <td>${escapeHtml(difference.row_id)}</td>
          <td>${escapeHtml(difference.column)}</td>
          <td>${escapeHtml(difference.expected)}</td>
          <td>${escapeHtml(difference.actual)}</td>
          <td>${difference.delta === null ? "" : formatNumber(difference.delta)}</td>
        </tr>
      `
    )
    .join("");
}

function downloadLatestCsv(): void {
  if (!latestAnalysis || latestAnalysis.rows.length === 0) {
    return;
  }

  const csv = rowsToCsv(latestAnalysis.rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const filename = csvFilename(latestAnalysis.source_path);
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", `Downloaded analysis CSV: "${filename}"`);
}

function downloadLatestBatchCsv(): void {
  if (!latestBatch || latestBatch.rows.length === 0) {
    return;
  }

  const csv = genericRowsToCsv(latestBatch.rows, latestBatch.columns);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "morphostack_batch_summary.csv";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", 'Downloaded batch summary CSV: "morphostack_batch_summary.csv"');
}

function downloadLatestBatchReport(): void {
  if (!latestBatch || latestBatch.rows.length === 0) {
    return;
  }

  const markdown = batchReportMarkdown(latestBatch);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "morphostack_batch_report.md";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", 'Downloaded batch Markdown report: "morphostack_batch_report.md"');
}

function downloadLatestReport(): void {
  if (!latestAnalysis) {
    return;
  }

  const markdown = analysisReportMarkdown(latestAnalysis);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const filename = reportFilename(latestAnalysis.source_path);
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", `Downloaded analysis Markdown report: "${filename}"`);
}

function downloadLatestSweepCsv(): void {
  if (!latestSweep || latestSweep.rows.length === 0) {
    return;
  }

  const csv = genericRowsToCsv(latestSweep.rows, latestSweep.columns);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const filename = sweepFilename(latestSweep.source_path);
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", `Downloaded sweep CSV: "${filename}"`);
}

function downloadLatestSweepReport(): void {
  if (!latestSweep || latestSweep.rows.length === 0) {
    return;
  }

  const markdown = sweepReportMarkdown(latestSweep);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const filename = sweepReportFilename(latestSweep.source_path);
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", `Downloaded sweep Markdown report: "${filename}"`);
}

function downloadLatestManifest(): void {
  if (!latestAnalysis) {
    return;
  }

  const json = `${JSON.stringify(latestAnalysis.manifest, null, 2)}\n`;
  const blob = new Blob([json], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const filename = manifestFilename(latestAnalysis.source_path);
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction("Export File", `Downloaded analysis JSON manifest: "${filename}"`);
}

type MeshDownloadFormat = "obj" | "stl" | "ply" | "glb";

function meshBaseFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-mesh";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-mesh";
  return baseName.replace(/[^a-z0-9._-]+/gi, "_");
}

function meshObjText(payload: MeshPreviewResponse): string {
  const lines = ["# MorphoStack mesh export"];
  for (const vertex of payload.vertices) {
    lines.push(`v ${vertex[0]} ${vertex[1]} ${vertex[2]}`);
  }
  for (const face of payload.faces) {
    lines.push(`f ${face[0] + 1} ${face[1] + 1} ${face[2] + 1}`);
  }
  return `${lines.join("\n")}\n`;
}

function meshStlText(payload: MeshPreviewResponse): string {
  const lines = ["solid morphostack"];
  for (const face of payload.faces) {
    const triangle = face.map((index) => payload.vertices[index]);
    const edgeA = [
      triangle[1][0] - triangle[0][0],
      triangle[1][1] - triangle[0][1],
      triangle[1][2] - triangle[0][2]
    ];
    const edgeB = [
      triangle[2][0] - triangle[0][0],
      triangle[2][1] - triangle[0][1],
      triangle[2][2] - triangle[0][2]
    ];
    const normal = [
      edgeA[1] * edgeB[2] - edgeA[2] * edgeB[1],
      edgeA[2] * edgeB[0] - edgeA[0] * edgeB[2],
      edgeA[0] * edgeB[1] - edgeA[1] * edgeB[0]
    ];
    const norm = Math.hypot(normal[0], normal[1], normal[2]) || 1;
    lines.push(`  facet normal ${normal[0] / norm} ${normal[1] / norm} ${normal[2] / norm}`);
    lines.push("    outer loop");
    for (const vertex of triangle) {
      lines.push(`      vertex ${vertex[0]} ${vertex[1]} ${vertex[2]}`);
    }
    lines.push("    endloop");
    lines.push("  endfacet");
  }
  lines.push("endsolid morphostack");
  return `${lines.join("\n")}\n`;
}

function meshPlyText(payload: MeshPreviewResponse): string {
  const header = [
    "ply",
    "format ascii 1.0",
    `element vertex ${payload.vertices.length}`,
    "property float x",
    "property float y",
    "property float z",
    `element face ${payload.faces.length}`,
    "property list uchar int vertex_indices",
    "end_header"
  ];
  const body = payload.vertices.map((vertex) => `${vertex[0]} ${vertex[1]} ${vertex[2]}`);
  for (const face of payload.faces) {
    body.push(`3 ${face[0]} ${face[1]} ${face[2]}`);
  }
  return `${header.join("\n")}\n${body.join("\n")}\n`;
}

function align4(length: number): number {
  return (length + 3) & ~3;
}

function meshGlbBlob(payload: MeshPreviewResponse): Blob {
  const vertices = new Float32Array(payload.vertices.flat());
  const indices = new Uint32Array(payload.faces.flat());
  const mins = [Infinity, Infinity, Infinity];
  const maxs = [-Infinity, -Infinity, -Infinity];
  for (let index = 0; index < vertices.length; index += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = vertices[index + axis];
      mins[axis] = Math.min(mins[axis], value);
      maxs[axis] = Math.max(maxs[axis], value);
    }
  }
  const vertexBytes = new Uint8Array(vertices.buffer, vertices.byteOffset, vertices.byteLength);
  const indexBytes = new Uint8Array(indices.buffer, indices.byteOffset, indices.byteLength);
  const vertexPaddedLen = align4(vertexBytes.length);
  const indexOffset = vertexPaddedLen;
  const binBody = new Uint8Array(align4(vertexPaddedLen + indexBytes.length));
  binBody.set(vertexBytes, 0);
  binBody.set(indexBytes, indexOffset);
  const gltf = {
    asset: { version: "2.0", generator: "MorphoStack" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1, mode: 4 }] }],
    buffers: [{ byteLength: binBody.length }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: vertexBytes.length, target: 34962 },
      { buffer: 0, byteOffset: indexOffset, byteLength: indexBytes.length, target: 34963 }
    ],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: payload.vertices.length,
        type: "VEC3",
        min: mins,
        max: maxs
      },
      {
        bufferView: 1,
        componentType: 5125,
        count: indices.length,
        type: "SCALAR"
      }
    ]
  };
  const jsonBytes = new TextEncoder().encode(JSON.stringify(gltf));
  const jsonPaddedLen = align4(jsonBytes.length);
  const jsonChunk = new Uint8Array(jsonPaddedLen);
  jsonChunk.set(jsonBytes);
  for (let index = jsonBytes.length; index < jsonPaddedLen; index += 1) {
    jsonChunk[index] = 0x20;
  }
  const totalLength = 12 + 8 + jsonPaddedLen + 8 + binBody.length;
  const output = new Uint8Array(totalLength);
  const view = new DataView(output.buffer);
  output.set(new Uint8Array([0x67, 0x6c, 0x54, 0x46]), 0);
  view.setUint32(4, 2, true);
  view.setUint32(8, totalLength, true);
  let offset = 12;
  view.setUint32(offset, jsonPaddedLen, true);
  output.set(new Uint8Array([0x4a, 0x53, 0x4f, 0x4e]), offset + 4);
  output.set(jsonChunk, offset + 8);
  offset += 8 + jsonPaddedLen;
  view.setUint32(offset, binBody.length, true);
  output.set(new Uint8Array([0x42, 0x49, 0x4e, 0x00]), offset + 4);
  output.set(binBody, offset + 8);
  return new Blob([output], { type: "model/gltf-binary" });
}

function meshFileBlob(payload: MeshPreviewResponse, format: MeshDownloadFormat): Blob {
  if (format === "obj") {
    return new Blob([meshObjText(payload)], { type: "text/plain;charset=utf-8" });
  }
  if (format === "stl") {
    return new Blob([meshStlText(payload)], { type: "text/plain;charset=utf-8" });
  }
  if (format === "ply") {
    return new Blob([meshPlyText(payload)], { type: "text/plain;charset=utf-8" });
  }
  return meshGlbBlob(payload);
}

function downloadLatestMeshFile(format: MeshDownloadFormat): void {
  if (!latestMeshPreview) {
    return;
  }
  const blob = meshFileBlob(latestMeshPreview, format);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  // Packet 14: client rebuild is display/preview only — never labelled as full scientific mesh.
  anchor.download = `${meshBaseFilename(latestMeshPreview.source_path)}_display_mesh.${format}`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction(
    "Export Display Mesh",
    `Downloaded display-only preview mesh ${format.toUpperCase()}: "${anchor.download}" (not full scientific export)`
  );
}

function downloadLatestMeshHtml(): void {
  if (!latestMeshPreview) {
    return;
  }

  const html = meshPreviewHtml(latestMeshPreview);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const filename = meshHtmlFilename(latestMeshPreview.source_path).replace(
    /_mesh\.html$/i,
    "_display_mesh.html"
  );
  anchor.download = filename.endsWith(".html") ? filename : `${filename}_display_mesh.html`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  logAction(
    "Export Display Mesh",
    `Downloaded display-only mesh HTML: "${anchor.download}" (not full scientific export)`
  );
}

function analysisReportMarkdown(payload: AnalyzeResponse): string {
  const manifest = payload.manifest;
  const lines = [
    "# MorphoStack Analysis Report",
    "",
    "## Run Settings",
    "",
    `- Source: \`${payload.source_path}\``,
    `- Source SHA-256: \`${String(manifest.source_sha256 ?? "not recorded")}\``,
    `- Profile: \`${payload.profile}\``,
    `- Threshold: \`${String(manifest.threshold ?? "")}\``,
    `- ROI: \`${manifest.roi === null || manifest.roi === undefined ? "full stack" : JSON.stringify(manifest.roi)}\``,
    `- Z range: \`${manifest.z_range === null || manifest.z_range === undefined ? "full stack" : JSON.stringify(manifest.z_range)}\``,
    `- Include mesh: \`${String(manifest.include_mesh ?? false)}\``,
    `- Enable skeleton: \`${String(manifest.enable_skeleton ?? false)}\``,
    `- Skeleton prune (px): \`${String(manifest.skeleton_prune_pix ?? "")}\``,
    `- Prefer OpenCV contours: \`${String(manifest.prefer_opencv ?? true)}\``,
    `- Voxel source: \`${payload.voxel_source}\``,
    `- Voxel size: x=${formatNumber(payload.voxel_size.x_um)} um, y=${formatNumber(payload.voxel_size.y_um)} um, z=${formatNumber(payload.voxel_size.z_um)} um`,
    "",
    "## Frame Summary",
    "",
    `- Frames: ${payload.frame_count}`,
    `- Valid frames: ${payload.valid_frame_count}`,
    `- Valid fraction: ${formatNumber(payload.summary.valid_fraction)}`,
    ""
  ];

  if (payload.warnings.length > 0) {
    lines.push("## Warnings", "");
    payload.warnings.forEach((warning) => {
      lines.push(`- \`${warning.code}\` (${warning.severity}): ${warning.message}`);
    });
    lines.push("");
  }

  const metricEntries = Object.entries(payload.summary.metrics);
  if (metricEntries.length > 0) {
    lines.push("## Metric Summary", "");
    lines.push("| Metric | Mean | Min | Max | Std |");
    lines.push("| --- | ---: | ---: | ---: | ---: |");
    metricEntries.forEach(([name, values]) => {
      lines.push(
        `| ${name} | ${formatNumber(values.mean)} | ${formatNumber(values.min)} | ${formatNumber(values.max)} | ${formatNumber(values.std)} |`
      );
    });
    lines.push("");
  }

  if (payload.mesh) {
    lines.push("## Mesh Summary", "");
    lines.push(`- Surface area: ${formatNumber(payload.mesh.surface_area_um2)} um2`);
    lines.push(`- Volume: ${formatNumber(payload.mesh.volume_um3)} um3`);
    lines.push(`- Equivalent sphere diameter: ${formatNumber(payload.mesh.equivalent_sphere_diameter_um)} um`);
    lines.push(`- Sphericity: ${formatNumber(payload.mesh.sphericity)}`);
    lines.push("");
  }

  const rows = payload.rows.slice(0, 10);
  if (rows.length > 0) {
    const showSkelUm = rows.some((row) => row.skel_perimeter_um !== undefined && row.skel_perimeter_um !== null);
    const showSkelPx = rows.some((row) => row.skel_perimeter_px !== undefined && row.skel_perimeter_px !== null);
    lines.push(`## First ${rows.length} Frame Rows`, "");
    lines.push(
      `| Frame | Contour | Area (um2) | Perimeter (um) | Circularity | Deformation index${showSkelUm ? " | Skel perimeter (um)" : ""}${showSkelPx ? " | Skel perimeter (px)" : ""} |`
    );
    lines.push(
      `| ---: | :---: | ---: | ---: | ---: | ---:${showSkelUm ? " | ---:" : ""}${showSkelPx ? " | ---:" : ""} |`
    );
    rows.forEach((row) => {
      const skelUm =
        showSkelUm
          ? ` | ${row.skel_perimeter_um !== undefined && row.skel_perimeter_um !== null ? formatNumber(row.skel_perimeter_um) : "—"}`
          : "";
      const skelPx =
        showSkelPx
          ? ` | ${row.skel_perimeter_px !== undefined && row.skel_perimeter_px !== null ? formatNumber(row.skel_perimeter_px) : "—"}`
          : "";
      lines.push(
        `| ${row.frame_index} | ${row.has_contour ? "yes" : "no"} | ${formatNumber(row.area_um2)} | ${formatNumber(row.perimeter_um)} | ${formatNumber(row.circularity)} | ${formatNumber(row.deformation_index)}${skelUm}${skelPx} |`
      );
    });
    lines.push("");
  }

  return `${lines.join("\n").trim()}\n`;
}

function batchReportMarkdown(payload: BatchAnalyzeResponse): string {
  const lines = [
    "# MorphoStack Batch Report",
    "",
    "## Batch Summary",
    "",
    `- Files: ${payload.file_count}`,
    `- Succeeded: ${payload.succeeded_count}`,
    `- Failed: ${payload.failed_count}`,
    "",
    "## Stack Summary",
    "",
    "| Source | SHA-256 | Status | Profile | Frames | Valid | Valid fraction | Mean area (um2) | Mean circularity | Mean deformation index | Warnings |",
    "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
  ];

  payload.rows.forEach((row) => {
    lines.push(
      [
        "|",
        markdownCell(String(row.source_path ?? "")),
        markdownCell(String(row.source_sha256 ?? "")),
        markdownCell(String(row.status ?? "")),
        markdownCell(String(row.profile ?? "")),
        formatUnknownNumber(row.frame_count),
        formatUnknownNumber(row.valid_frame_count),
        formatUnknownNumber(row.valid_fraction),
        formatUnknownNumber(row.area_um2_mean),
        formatUnknownNumber(row.circularity_mean),
        formatUnknownNumber(row.deformation_index_mean),
        markdownCell(String(row.warning_codes ?? "")),
        "|"
      ].join(" ")
    );
  });
  lines.push("");

  const failedRows = payload.rows.filter((row) => row.status !== "ok");
  if (failedRows.length > 0) {
    lines.push("## Failures", "");
    failedRows.forEach((row) => {
      lines.push(`- ${String(row.source_path ?? "")}: ${String(row.error_message ?? "")}`);
    });
    lines.push("");
  }

  return `${lines.join("\n").trim()}\n`;
}

function sweepReportMarkdown(payload: SweepResponse): string {
  const bestRow =
    payload.best_threshold === null
      ? undefined
      : payload.rows.find((row) => Number(row.threshold) === payload.best_threshold);
  const lines = [
    "# MorphoStack Threshold Sweep Report",
    "",
    "## Sweep Summary",
    "",
    `- Source: \`${payload.source_path}\``,
    `- Profile: \`${payload.profile}\``,
    `- Thresholds tested: ${payload.threshold_count}`,
    `- Best threshold: ${payload.best_threshold === null ? "none" : formatNumber(payload.best_threshold)}`,
    `- Voxel source: \`${payload.voxel_source}\``,
    ""
  ];

  if (bestRow) {
    lines.push(
      "## Best Threshold Metrics",
      "",
      `- Valid frames: ${formatUnknownNumber(bestRow.valid_frame_count)}`,
      `- Valid fraction: ${formatUnknownNumber(bestRow.valid_fraction)}`,
      `- Mean area: ${formatUnknownNumber(bestRow.area_um2_mean)} um2`,
      `- Mean circularity: ${formatUnknownNumber(bestRow.circularity_mean)}`,
      `- Mean deformation index: ${formatUnknownNumber(bestRow.deformation_index_mean)}`,
      `- Warnings: ${String(bestRow.warning_codes ?? "") || "none"}`,
      ""
    );
  }

  lines.push(
    "## Threshold Rows",
    "",
    "| Threshold | Valid fraction | Valid frames | Mean area (um2) | Mean circularity | Mean deformation index | Warnings |",
    "| ---: | ---: | ---: | ---: | ---: | ---: | --- |"
  );
  payload.rows.forEach((row) => {
    lines.push(
      [
        "|",
        formatUnknownNumber(row.threshold),
        formatUnknownNumber(row.valid_fraction),
        formatUnknownNumber(row.valid_frame_count),
        formatUnknownNumber(row.area_um2_mean),
        formatUnknownNumber(row.circularity_mean),
        formatUnknownNumber(row.deformation_index_mean),
        markdownCell(String(row.warning_codes ?? "")),
        "|"
      ].join(" ")
    );
  });
  lines.push("");

  return `${lines.join("\n").trim()}\n`;
}

function currentProjectSettings(): ProjectSettings {
  const roi = readRoi();
  const zRange = readZRange();
  return {
    version: 1,
    profile: readProfile(),
    threshold: readNumber("threshold-input"),
    voxel_size: readVoxel() ?? undefined,
    roi: roi ?? undefined,
    z_range: zRange ?? undefined,
    include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
    enable_skeleton: readEnableSkeleton(),
    skeleton_prune_pix: readSkeletonPrunePix(),
    prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
    sweep: {
      start: readNumber("sweep-start"),
      stop: readNumber("sweep-stop"),
      step: readNumber("sweep-step")
    }
  };
}

function validateProjectSettings(payload: unknown): ProjectSettings {
  if (!isRecord(payload)) {
    throw new Error("Project settings must be a JSON object.");
  }
  if (payload.version !== 1) {
    throw new Error("Project settings version must be 1.");
  }

  const settings: ProjectSettings = { version: 1 };
  if (payload.profile !== undefined) {
    if (payload.profile !== "vesicle" && payload.profile !== "rbc" && payload.profile !== "active_surfaces") {
      throw new Error("Project profile must be vesicle, rbc, or active_surfaces.");
    }
    settings.profile = payload.profile;
  }
  if (payload.threshold !== undefined) {
    settings.threshold = finiteNumber(payload.threshold, "threshold");
  }
  if (payload.voxel_size !== undefined) {
    if (!isRecord(payload.voxel_size)) {
      throw new Error("Project voxel_size must be an object.");
    }
    settings.voxel_size = {
      x_um: positiveNumber(payload.voxel_size.x_um, "voxel_size.x_um"),
      y_um: positiveNumber(payload.voxel_size.y_um, "voxel_size.y_um"),
      z_um: positiveNumber(payload.voxel_size.z_um, "voxel_size.z_um")
    };
  }
  if (payload.roi !== undefined) {
    if (!isRecord(payload.roi)) {
      throw new Error("Project roi must be an object.");
    }
    settings.roi = {
      xmin: finiteNumber(payload.roi.xmin, "roi.xmin"),
      xmax: finiteNumber(payload.roi.xmax, "roi.xmax"),
      ymin: finiteNumber(payload.roi.ymin, "roi.ymin"),
      ymax: finiteNumber(payload.roi.ymax, "roi.ymax")
    };
  }
  if (payload.z_range !== undefined) {
    if (!isRecord(payload.z_range)) {
      throw new Error("Project z_range must be an object.");
    }
    settings.z_range = {
      zmin: finiteNumber(payload.z_range.zmin, "z_range.zmin"),
      zmax: finiteNumber(payload.z_range.zmax, "z_range.zmax")
    };
  }
  if (payload.include_mesh !== undefined) {
    settings.include_mesh = booleanValue(payload.include_mesh, "include_mesh");
  }
  if (payload.enable_skeleton !== undefined) {
    settings.enable_skeleton = booleanValue(payload.enable_skeleton, "enable_skeleton");
  }
  if (payload.skeleton_prune_pix !== undefined) {
    settings.skeleton_prune_pix = finiteNumber(payload.skeleton_prune_pix, "skeleton_prune_pix");
  }
  if (payload.prefer_opencv !== undefined) {
    settings.prefer_opencv = booleanValue(payload.prefer_opencv, "prefer_opencv");
  }
  if (payload.sweep !== undefined) {
    if (!isRecord(payload.sweep)) {
      throw new Error("Project sweep must be an object.");
    }
    settings.sweep = {};
    if (payload.sweep.start !== undefined) {
      settings.sweep.start = finiteNumber(payload.sweep.start, "sweep.start");
    }
    if (payload.sweep.stop !== undefined) {
      settings.sweep.stop = finiteNumber(payload.sweep.stop, "sweep.stop");
    }
    if (payload.sweep.step !== undefined) {
      settings.sweep.step = positiveNumber(payload.sweep.step, "sweep.step");
    }
  }
  return settings;
}

function applyProjectSettings(settings: ProjectSettings): void {
  if (settings.profile !== undefined) {
    mustElement<HTMLSelectElement>("profile-input").value = settings.profile;
  }
  if (settings.threshold !== undefined) {
    mustElement<HTMLInputElement>("threshold-input").value = formatInputNumber(settings.threshold);
  }
  if (settings.voxel_size !== undefined) {
    mustElement<HTMLSelectElement>("calibration-mode").value = "manual";
    const vx = mustElement<HTMLInputElement>("voxel-x");
    const vy = mustElement<HTMLInputElement>("voxel-y");
    const vz = mustElement<HTMLInputElement>("voxel-z");
    vx.value = formatInputNumber(settings.voxel_size.x_um);
    vy.value = formatInputNumber(settings.voxel_size.y_um);
    vz.value = formatInputNumber(settings.voxel_size.z_um);
    vx.disabled = false;
    vy.disabled = false;
    vz.disabled = false;
  }
  if (settings.roi !== undefined) {
    mustElement<HTMLInputElement>("roi-xmin").value = formatInputNumber(settings.roi.xmin);
    mustElement<HTMLInputElement>("roi-xmax").value = formatInputNumber(settings.roi.xmax);
    mustElement<HTMLInputElement>("roi-ymin").value = formatInputNumber(settings.roi.ymin);
    mustElement<HTMLInputElement>("roi-ymax").value = formatInputNumber(settings.roi.ymax);
    updateRoiStatus();
  }
  if (settings.z_range !== undefined) {
    mustElement<HTMLInputElement>("z-min").value = formatInputNumber(settings.z_range.zmin);
    mustElement<HTMLInputElement>("z-max").value = formatInputNumber(settings.z_range.zmax);
    syncZRangeControls();
  }
  if (settings.include_mesh !== undefined) {
    mustElement<HTMLInputElement>("mesh-input").checked = settings.include_mesh;
  }
  if (settings.enable_skeleton !== undefined) {
    mustElement<HTMLInputElement>("skeleton-input").checked = settings.enable_skeleton;
  }
  if (settings.skeleton_prune_pix !== undefined) {
    mustElement<HTMLInputElement>("skeleton-prune-input").value = formatInputNumber(settings.skeleton_prune_pix);
  }
  updateSkeletonPruneVisibility();
  if (settings.prefer_opencv !== undefined) {
    mustElement<HTMLInputElement>("fallback-input").checked = !settings.prefer_opencv;
  }
  if (settings.sweep !== undefined) {
    if (settings.sweep.start !== undefined) {
      mustElement<HTMLInputElement>("sweep-start").value = formatInputNumber(settings.sweep.start);
    }
    if (settings.sweep.stop !== undefined) {
      mustElement<HTMLInputElement>("sweep-stop").value = formatInputNumber(settings.sweep.stop);
    }
    if (settings.sweep.step !== undefined) {
      mustElement<HTMLInputElement>("sweep-step").value = formatInputNumber(settings.sweep.step);
    }
  }
}

function analysisCsvColumns(rows: AnalysisRow[]): string[] {
  const columns: string[] = [...CSV_COLUMNS];
  if (rows.some((row) => row.skel_perimeter_um !== undefined && row.skel_perimeter_um !== null)) {
    columns.push("skel_perimeter_um");
  }
  if (rows.some((row) => row.skel_perimeter_px !== undefined && row.skel_perimeter_px !== null)) {
    columns.push("skel_perimeter_px");
  }
  return columns;
}

function rowsToCsv(rows: AnalysisRow[]): string {
  const columns = analysisCsvColumns(rows);
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row[column as keyof AnalysisRow])).join(","))
  ];
  return `${lines.join("\r\n")}\r\n`;
}

function genericRowsToCsv(rows: BatchSummaryRow[], columns: string[]): string {
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(","))
  ];
  return `${lines.join("\r\n")}\r\n`;
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  if (!/[",\r\n]/.test(text)) {
    return text;
  }
  return `"${text.replace(/"/g, "\"\"")}"`;
}

function markdownCell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function csvFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-analysis";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-analysis";
  const safeName = baseName.replace(/[^a-z0-9._-]+/gi, "_");
  return `${safeName}_metrics.csv`;
}

function manifestFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-analysis";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-analysis";
  const safeName = baseName.replace(/[^a-z0-9._-]+/gi, "_");
  return `${safeName}_manifest.json`;
}

function reportFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-analysis";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-analysis";
  const safeName = baseName.replace(/[^a-z0-9._-]+/gi, "_");
  return `${safeName}_report.md`;
}

function meshHtmlFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-mesh";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-mesh";
  const safeName = baseName.replace(/[^a-z0-9._-]+/gi, "_");
  return `${safeName}_mesh.html`;
}

function sweepFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-sweep";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-sweep";
  const safeName = baseName.replace(/[^a-z0-9._-]+/gi, "_");
  return `${safeName}_threshold_sweep.csv`;
}

function sweepReportFilename(sourcePath: string): string {
  const rawName = sourcePath.split(/[\\/]/).pop() || "morphostack-sweep";
  const baseName = rawName.replace(/\.[^.]+$/, "") || "morphostack-sweep";
  const safeName = baseName.replace(/[^a-z0-9._-]+/gi, "_");
  return `${safeName}_threshold_sweep_report.md`;
}

async function apiGet<T>(url: string): Promise<T> {
  const response = await fetch(url);
  return parseResponse<T>(response);
}

async function apiPost<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal
  });
  return parseResponse<T>(response);
}

function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return false;
  }
  const name = "name" in error ? String((error as { name?: unknown }).name) : "";
  return name === "AbortError";
}

function fileIdentity(file: File): string {
  return `${file.name}|${file.size}|${file.lastModified}`;
}

function clearUploadSession(): void {
  sessionStackId = null;
  sessionFileKey = null;
  sessionOpenPromise = null;
  updateSessionBanner();
}

function readVolumeBlendMode(): VolumeBlendMode {
  return volumeBlendModeSelect.value === "composite" ? "composite" : "mip";
}

function disposeVolumeViewer(reason?: string): void {
  volumeLoadGen += 1;
  volumeSeedPickMode = false;
  lastDisplayLevelPayload = null;
  updateVolumeSeedPickButton();
  if (volumeSession) {
    volumeSession.dispose();
    volumeSession = null;
  }
  volumeVtkRoot.replaceChildren();
  volumeViewerCanvasWrap.hidden = true;
  if (reason) {
    volumeViewerFallback.hidden = false;
    volumeViewerFallback.textContent = `3D volume cleared (${reason}). 2D preview remains available.`;
    volumeViewerStatus.textContent = "Idle";
    volumeViewerStatus.classList.remove("is-error");
    volumeViewerMeta.hidden = true;
    volumeViewerMeta.textContent = "";
    volumeViewerPanel.dataset.state = "idle";
  }
}

function updateVolumeSeedPickButton(): void {
  const btn = document.getElementById("volume-seed-pick-btn");
  if (!(btn instanceof HTMLButtonElement)) return;
  const ready = volumeSession !== null && volumeViewerPanel.dataset.state === "ready";
  btn.disabled = !ready;
  btn.textContent = volumeSeedPickMode ? "Cancel 3D seed pick" : "Pick seed in 3D";
  btn.classList.toggle("active", volumeSeedPickMode);
}

function toggleVolumeSeedPickMode(): void {
  if (!volumeSession || volumeViewerPanel.dataset.state !== "ready") {
    volumeSeedPickMode = false;
    updateVolumeSeedPickButton();
    return;
  }
  volumeSeedPickMode = !volumeSeedPickMode;
  volumeSession.setSeedPickEnabled(volumeSeedPickMode);
  updateVolumeSeedPickButton();
  if (volumeSeedPickMode) {
    volumeViewerStatus.textContent = `Click in the volume to place a source-level seed (${NAVIGATION_ONLY_LABEL}). Orbit drag still works if you move the mouse.`;
    volumeViewerStatus.classList.remove("is-error");
  } else if (volumeSession.readyMeta) {
    volumeViewerStatus.textContent = `Ready · level ${volumeSession.readyMeta.level} · ${NAVIGATION_ONLY_LABEL}`;
  }
}

function readSourceVoxelForMapping(): { voxel: VoxelOverride; known: boolean } {
  const mode = mustElement<HTMLSelectElement>("calibration-mode").value;
  const x = Number(mustElement<HTMLInputElement>("voxel-x").value);
  const y = Number(mustElement<HTMLInputElement>("voxel-y").value);
  const z = Number(mustElement<HTMLInputElement>("voxel-z").value);
  const voxel = {
    x_um: Number.isFinite(x) && x > 0 ? x : 1,
    y_um: Number.isFinite(y) && y > 0 ? y : 1,
    z_um: Number.isFinite(z) && z > 0 ? z : 1
  };
  // Manual override is known. Auto with only the 1×1×1 placeholder is unknown calibration.
  const placeholder = voxel.x_um === 1 && voxel.y_um === 1 && voxel.z_um === 1;
  const known = mode === "manual" || !placeholder;
  return { voxel, known };
}

function applyObjectSeedFrom3D(world: WorldPointUm): void {
  const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
  try {
    if (!volumeSession || !lastDisplayLevelPayload || !inspectedSourceShape) {
      throw new SeedMappingError("3D volume geometry not ready; load volume first", "invalid_geometry");
    }
    const { voxel, known } = readSourceVoxelForMapping();
    const geometry = geometryFromLevelPayload(
      lastDisplayLevelPayload,
      inspectedSourceShape,
      voxel,
      known
    );
    const radiusRaw = Number(mustElement<HTMLInputElement>("object-seed-radius").value);
    const radiusPx = Number.isFinite(radiusRaw) && radiusRaw > 0 ? radiusRaw : 10;
    const maxDistVal = parseFloat(mustElement<HTMLInputElement>("object-seed-max-dist").value);
    const max_tracking_dist_um = isNaN(maxDistVal) ? undefined : maxDistVal;
    const mapped = worldToObjectSeed(world, geometry, radiusPx, {
      clampZ: true,
      maxTrackingDistUm: max_tracking_dist_um,
      expectedRevision: geometry.sourceRevision
    });
    selectedObjectSeed = {
      x: mapped.x,
      y: mapped.y,
      frame_index: mapped.frame_index,
      radius: mapped.radius,
      max_tracking_dist_um: mapped.max_tracking_dist_um,
      type: "circle",
      source_revision: mapped.source_revision,
      seed_origin: "viewer_3d",
      radius_unit: "px"
    };
    // Jump 2D scrubber to seed frame (global index).
    if (inspectedFrameCount != null && selectedObjectSeed.frame_index < inspectedFrameCount) {
      frameInput.value = String(selectedObjectSeed.frame_index);
      frameSlider.value = String(selectedObjectSeed.frame_index);
      updateFrameSliceLabel();
    }
    mustElement<HTMLInputElement>("object-seed-radius").value = String(Math.round(mapped.radius));
    volumeSeedPickMode = false;
    volumeSession.setSeedPickEnabled(false);
    updateVolumeSeedPickButton();
    void volumeSession.setSeedMarker(selectedObjectSeed, geometry);
    updateObjectSeedStatus();
    const t1 = typeof performance !== "undefined" ? performance.now() : Date.now();
    const worldBack = objectSeedToWorld(selectedObjectSeed, geometry);
    logAction(
      "Set Object Seed (3D)",
      `source=(${mapped.x}, ${mapped.y}, z=${mapped.frame_index}) r=${mapped.radius} px · origin=viewer_3d · revision=${mapped.source_revision ?? "none"} · pick_ms=${(t1 - t0).toFixed(1)} · world≈(${worldBack.x_um.toFixed(2)}, ${worldBack.y_um.toFixed(2)}, ${worldBack.z_um.toFixed(2)}) ${known ? "µm" : "µm(uncalibrated)"}`
    );
    volumeViewerStatus.textContent = `Seed from 3D · frame ${mapped.frame_index} · (${mapped.x}, ${mapped.y}) r=${Math.round(mapped.radius)} px · ${NAVIGATION_ONLY_LABEL}`;
    // Same Milestone A path as 2D seed — no separate 3D tracker.
    void previewStack();
  } catch (error) {
    const msg =
      error instanceof SeedMappingError
        ? error.message
        : errorMessage(error);
    volumeViewerStatus.textContent = msg;
    volumeViewerStatus.classList.add("is-error");
    logAction("3D Seed Mapping Failed", msg);
  }
}

function syncVolumeSeedMarkerFromSelection(): void {
  if (!volumeSession || !selectedObjectSeed || !lastDisplayLevelPayload || !inspectedSourceShape) {
    volumeSession?.clearSeedMarker();
    return;
  }
  try {
    const { voxel, known } = readSourceVoxelForMapping();
    const geometry = geometryFromLevelPayload(
      lastDisplayLevelPayload,
      inspectedSourceShape,
      voxel,
      known
    );
    void volumeSession.setSeedMarker(selectedObjectSeed, geometry);
  } catch {
    volumeSession.clearSeedMarker();
  }
}

function setVolumeViewerUiLoading(message: string): void {
  volumeViewerPanel.dataset.state = "loading";
  volumeViewerStatus.textContent = message;
  volumeViewerStatus.classList.remove("is-error");
  volumeViewerFallback.hidden = false;
  volumeViewerFallback.textContent = message;
  volumeViewerCanvasWrap.hidden = true;
  volumeViewerMeta.hidden = true;
}

function setVolumeViewerUiFallback(reason: VolumeFallbackReason, message: string): void {
  volumeViewerPanel.dataset.state = "fallback";
  volumeViewerStatus.textContent = message;
  volumeViewerStatus.classList.add("is-error");
  volumeViewerFallback.hidden = false;
  volumeViewerFallback.textContent = message;
  volumeViewerCanvasWrap.hidden = true;
  volumeViewerMeta.hidden = reason === "feature_disabled";
  if (reason !== "feature_disabled") {
    volumeViewerMeta.hidden = false;
    volumeViewerMeta.textContent = `fallback=${reason}; ${NAVIGATION_ONLY_LABEL}`;
  }
}

function updateVolumeMetaLine(meta: NonNullable<VolumeViewerSession["readyMeta"]>): void {
  const extent = worldExtentUm(meta.shapeZyx, meta.spacingUm);
  volumeViewerMeta.hidden = false;
  volumeViewerMeta.textContent = [
    `level=${meta.level}`,
    `shape_zyx=${meta.shapeZyx.join("×")}`,
    `dtype=${meta.dtype}`,
    `spacing_um=${meta.spacingUm.x_um}/${meta.spacingUm.y_um}/${meta.spacingUm.z_um}`,
    `extent_um≈${extent.x.toFixed(2)}×${extent.y.toFixed(2)}×${extent.z.toFixed(2)}`,
    `bytes=${meta.transferBytes}`,
    `blend=${meta.blendMode}`,
    `load_ms=${meta.loadMs.toFixed(0)}`,
    `display_only=true`
  ].join(" · ");
}

type VolumePerfRecord = {
  reason: string;
  t0: number;
  tPyramidReady?: number;
  tLevelDownloaded?: number;
  tGpuReady?: number;
  tFallback?: number;
  firstPaintMs?: number;
  gpuMountMs?: number;
  transferBytes?: number;
  level?: number;
  fallbackReason?: string;
  ok: boolean;
};

function volumePerfNow(): number {
  return typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
}

function publishVolumePerf(record: VolumePerfRecord): void {
  const w = window as Window & { __morphostackVolumePerf?: VolumePerfRecord[] };
  if (!Array.isArray(w.__morphostackVolumePerf)) {
    w.__morphostackVolumePerf = [];
  }
  w.__morphostackVolumePerf.push(record);
  // Cap history so long sessions do not grow unbounded.
  if (w.__morphostackVolumePerf.length > 32) {
    w.__morphostackVolumePerf.splice(0, w.__morphostackVolumePerf.length - 32);
  }
}

/**
 * Build/load bounded display pyramid level and mount VTK viewer.
 * Never calls analyze/mesh metric endpoints; 2D path stays independent.
 */
async function loadVolumeViewer(options: { reason: string } = { reason: "manual" }): Promise<void> {
  const gen = ++volumeLoadGen;
  const perf: VolumePerfRecord = { reason: options.reason, t0: volumePerfNow(), ok: false };
  if (volumeSession) {
    volumeSession.dispose();
    volumeSession = null;
  }
  volumeVtkRoot.replaceChildren();
  volumeViewerCanvasWrap.hidden = true;

  if (!volumeViewerEnable.checked || !isVolumeViewerEnabled()) {
    setVolumeViewerUiFallback("feature_disabled", fallbackMessage("feature_disabled"));
    perf.ok = false;
    perf.fallbackReason = "feature_disabled";
    perf.tFallback = volumePerfNow();
    publishVolumePerf(perf);
    return;
  }

  setVolumeViewerUiLoading(`Building display volume (${options.reason})…`);
  try {
    await ensureApiOnline();
    if (gen !== volumeLoadGen) return;

    const source = resolveStackSource();
    const voxel = readVoxel();
    let buildBody: Record<string, unknown>;
    if (source.kind === "path") {
      buildBody = {
        path: source.path,
        voxel,
        max_level_bytes: DEFAULT_VOLUME_MAX_BYTES,
        background: true
      };
    } else {
      const stackId = await ensureUploadSession(source.file);
      if (gen !== volumeLoadGen) return;
      buildBody = {
        stack_id: stackId,
        voxel,
        max_level_bytes: DEFAULT_VOLUME_MAX_BYTES,
        background: true
      };
    }

    const buildPayload = await apiPost<{
      cache_key?: string;
      state?: string;
      levels_ready?: number[];
      error?: string | null;
    }>("/api/display-pyramid/build", buildBody);
    if (gen !== volumeLoadGen) return;

    const cacheKey = String(buildPayload.cache_key ?? "").trim();
    if (!cacheKey) {
      throw new VolumeViewerError(
        "endpoint_error",
        fallbackMessage("endpoint_error", "build response missing cache_key")
      );
    }
    setVolumeViewerUiLoading(
      `Display pyramid ${buildPayload.state ?? "queued"} — waiting for coarse level…`
    );
    await waitForPyramidLevelReady({
      cacheKey,
      intervalMs: 200,
      timeoutMs: 120_000,
      isCancelled: () => gen !== volumeLoadGen,
      pollStatus: (key) =>
        apiPost("/api/display-pyramid/status", { cache_key: key })
    });
    if (gen !== volumeLoadGen) return;
    perf.tPyramidReady = volumePerfNow();

    setVolumeViewerUiLoading("Downloading bounded display level…");
    const levelPayload = await apiPost<DisplayLevelResponse>("/api/display-pyramid/level", {
      cache_key: cacheKey,
      max_bytes: DEFAULT_VOLUME_MAX_BYTES,
      include_binary: true
    });
    if (gen !== volumeLoadGen) return;
    perf.tLevelDownloaded = volumePerfNow();

    // Hard isolation: never pass this payload into analyze/mesh metric code paths.
    if (levelPayload.display_volume_spec && levelPayload.display_volume_spec.display_only === false) {
      throw new VolumeViewerError(
        "endpoint_error",
        "Refusing non-display volume for navigation viewer"
      );
    }

    setVolumeViewerUiLoading("Uploading volume to GPU…");
    volumeViewerFallback.hidden = true;
    volumeViewerCanvasWrap.hidden = false;
    const { voxel: srcVoxel, known: calKnown } = readSourceVoxelForMapping();
    const session = await VolumeViewerSession.mount({
      container: volumeVtkRoot,
      payload: levelPayload,
      blendMode: readVolumeBlendMode(),
      opacityGain: Number(volumeOpacityInput.value) || 0.35,
      maxBytes: DEFAULT_VOLUME_MAX_BYTES,
      sourceShapeZyx: inspectedSourceShape ?? undefined,
      sourceVoxelSize: srcVoxel,
      calibrationKnown: calKnown,
      onWorldPick: (world) => {
        applyObjectSeedFrom3D(world);
      }
    });
    if (gen !== volumeLoadGen) {
      session.dispose();
      return;
    }
    volumeSession = session;
    lastDisplayLevelPayload = levelPayload;
    const meta = session.readyMeta;
    volumeViewerPanel.dataset.state = "ready";
    volumeViewerStatus.textContent = meta
      ? `Ready · level ${meta.level} · ${NAVIGATION_ONLY_LABEL}`
      : `Ready · ${NAVIGATION_ONLY_LABEL}`;
    volumeViewerStatus.classList.remove("is-error");
    volumeViewerFallback.hidden = true;
    volumeViewerCanvasWrap.hidden = false;
    volumeSeedPickMode = false;
    session.setSeedPickEnabled(false);
    updateVolumeSeedPickButton();
    syncVolumeSeedMarkerFromSelection();
    perf.tGpuReady = volumePerfNow();
    perf.firstPaintMs = perf.tGpuReady - perf.t0;
    perf.gpuMountMs = meta?.loadMs;
    perf.transferBytes = meta?.transferBytes;
    perf.level = meta?.level;
    perf.ok = true;
    publishVolumePerf(perf);
    if (meta) {
      updateVolumeMetaLine(meta);
      logAction(
        "Volume Viewer Ready",
        `cache_key=${cacheKey}, level=${meta.level}, bytes=${meta.transferBytes}, load_ms=${meta.loadMs.toFixed(0)}, first_paint_ms=${perf.firstPaintMs.toFixed(0)}, ${NAVIGATION_ONLY_LABEL}`
      );
    }
  } catch (error) {
    if (gen !== volumeLoadGen) return;
    if (volumeSession) {
      volumeSession.dispose();
      volumeSession = null;
    }
    volumeVtkRoot.replaceChildren();
    volumeViewerCanvasWrap.hidden = true;
    const reason: VolumeFallbackReason =
      error instanceof VolumeViewerError ? error.reason : "endpoint_error";
    const message =
      error instanceof VolumeViewerError
        ? error.message
        : fallbackMessage("endpoint_error", errorMessage(error));
    setVolumeViewerUiFallback(reason, message);
    perf.ok = false;
    perf.fallbackReason = reason;
    perf.tFallback = volumePerfNow();
    perf.firstPaintMs = perf.tFallback - perf.t0;
    publishVolumePerf(perf);
    logAction("Volume Viewer Fallback", `${reason}: ${message}`);
  }
}

function rememberUploadSession(stackId: string, file: File): void {
  sessionStackId = stackId;
  sessionFileKey = fileIdentity(file);
  sessionOpenPromise = null;
  updateSessionBanner();
}

function hasActiveUploadSession(file: File): boolean {
  return sessionStackId !== null && sessionFileKey === fileIdentity(file);
}

function updateSessionBanner(): void {
  const banner = document.getElementById("session-banner");
  const status = document.getElementById("session-status");
  if (!(banner instanceof HTMLElement) || !(status instanceof HTMLElement)) {
    return;
  }
  const path = stackPathOrNull();
  const file = selectedFile();
  const fileMode = !path && file !== null;
  banner.hidden = !fileMode;
  if (!fileMode) {
    status.hidden = true;
    status.textContent = "";
    return;
  }
  status.hidden = false;
  if (hasActiveUploadSession(file)) {
    status.className = "session-status ok";
    status.textContent = `Server session active for ${file.name} — Preview / Mesh / Analyze will not re-upload.`;
  } else {
    status.className = "session-status muted";
    status.textContent = "No server session yet — Inspect (or first Preview) loads the file once into memory.";
  }
}

/**
 * Ensure the chosen File is loaded once on the server; return stack_id for JSON APIs.
 * Concurrent callers share a single in-flight open.
 */
async function ensureUploadSession(
  file: File,
  options: {
    onProgress?: (percent: number) => void;
  } = {}
): Promise<string> {
  const key = fileIdentity(file);
  if (sessionStackId && sessionFileKey === key) {
    return sessionStackId;
  }
  if (sessionOpenPromise && sessionFileKey === key) {
    return sessionOpenPromise;
  }

  sessionFileKey = key;
  sessionStackId = null;
  updateSessionBanner();

  sessionOpenPromise = (async () => {
    const formData = new FormData();
    appendFileAndVoxel(formData, file);
    const payload = await apiUploadPost<SessionOpenResponse>(
      "/api/upload/session",
      formData,
      options.onProgress
    );
    sessionStackId = payload.stack_id;
    sessionFileKey = key;
    updateSessionBanner();
    return payload.stack_id;
  })();

  try {
    return await sessionOpenPromise;
  } catch (error) {
    if (sessionFileKey === key) {
      clearUploadSession();
    }
    throw error;
  } finally {
    if (sessionOpenPromise) {
      // Clear latch only if we still own this open (success keeps stack id).
      sessionOpenPromise = null;
    }
  }
}

async function apiUploadPost<T>(
  url: string,
  formData: FormData,
  onUploadProgress?: (percent: number) => void
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    // text + JSON.parse: clearer errors than responseType=json when proxy/API returns HTML/empty
    xhr.responseType = "text";
    xhr.timeout = 30 * 60 * 1000; // large CZI/LSM uploads
    xhr.upload.onprogress = (event) => {
      if (!onUploadProgress || !event.lengthComputable || event.total <= 0) {
        return;
      }
      onUploadProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const raw = typeof xhr.response === "string" ? xhr.response : "";
      let payload: unknown = null;
      if (raw.trim()) {
        try {
          payload = JSON.parse(raw);
        } catch {
          if (xhr.status >= 200 && xhr.status < 300) {
            reject(new Error("API returned a non-JSON response. Is the MorphoStack backend running?"));
            return;
          }
          reject(new Error(raw.slice(0, 240) || xhr.statusText || "Request failed"));
          return;
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as T);
        return;
      }
      reject(new Error(detailFromPayload(payload, xhr.statusText || `HTTP ${xhr.status}`)));
    };
    xhr.ontimeout = () =>
      reject(new Error("Upload timed out. Try a smaller stack, or use a local path with morphostack app/serve."));
    xhr.onerror = () =>
      reject(
        new Error(
          "Cannot reach MorphoStack API (network error). " +
            "Run `morphostack dev` (UI+API) or `morphostack app`, and keep that terminal open. " +
            "If you only opened the static UI, the backend is not attached."
        )
      );
    xhr.send(formData);
  });
}

function detailFromPayload(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            const loc = "loc" in item && Array.isArray(item.loc) ? item.loc.join(".") : "";
            return loc ? `${loc}: ${String((item as { msg: unknown }).msg)}` : String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join(", ");
    }
    if (detail !== undefined) {
      return JSON.stringify(detail);
    }
  }
  return fallback;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const raw = await response.text();
  let payload: unknown = null;
  if (raw.trim()) {
    try {
      payload = JSON.parse(raw);
    } catch {
      if (!response.ok) {
        // Starlette bare 500s often return plain text "Internal Server Error"
        throw new Error(raw.slice(0, 400).trim() || response.statusText || `HTTP ${response.status}`);
      }
      throw new Error("API returned a non-JSON response. Is the MorphoStack backend running?");
    }
  }
  if (!response.ok) {
    throw new Error(detailFromPayload(payload, response.statusText || `HTTP ${response.status}`));
  }
  return payload as T;
}

function selectedFile(): File | null {
  return mustElement<HTMLInputElement>("file-input").files?.[0] ?? null;
}

function selectedBatchFiles(): File[] {
  const files = Array.from(mustElement<HTMLInputElement>("batch-file-input").files ?? []);
  if (files.length === 0) {
    throw new Error("At least one batch stack file is required.");
  }
  return files;
}

function selectedRequiredFile(id: string, label: string): File {
  const file = mustElement<HTMLInputElement>(id).files?.[0] ?? null;
  if (!file) {
    throw new Error(`${label} is required.`);
  }
  return file;
}

function inspectUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  return formData;
}

function readEnableSkeleton(): boolean {
  return mustElement<HTMLInputElement>("skeleton-input").checked;
}

function readSkeletonPrunePix(): number {
  const raw = mustElement<HTMLInputElement>("skeleton-prune-input").value.trim();
  const value = raw === "" ? 1 : Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    return 1;
  }
  return value;
}

function updateSkeletonPruneVisibility(): void {
  const wrap = document.querySelector(".skeleton-prune-wrap");
  const pruneInput = document.getElementById("skeleton-prune-input");
  const enabled = readEnableSkeleton();
  if (wrap instanceof HTMLElement) {
    wrap.classList.toggle("is-disabled", !enabled);
  }
  if (pruneInput instanceof HTMLInputElement) {
    // Keep editable always so users can set prune before enabling skeleton.
    pruneInput.disabled = false;
    pruneInput.readOnly = false;
  }
}

function batchUploadForm(files: File[]): FormData {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });
  appendVoxelFields(formData);
  formData.set("threshold", String(readNumber("threshold-input")));
  formData.set("profile", readProfile());
  formData.set("include_mesh", String(mustElement<HTMLInputElement>("mesh-input").checked));
  formData.set("prefer_opencv", String(!mustElement<HTMLInputElement>("fallback-input").checked));
  appendRoiFields(formData);
  appendZRangeFields(formData);
  return formData;
}

function validationUploadForm(): FormData {
  const formData = new FormData();
  formData.set("expected_file", selectedRequiredFile("expected-csv-input", "Reference CSV"));
  formData.set("actual_file", selectedRequiredFile("actual-csv-input", "New CSV"));
  formData.set("tolerance", String(readNumber("validation-tolerance")));
  formData.set("key_column", mustElement<HTMLInputElement>("validation-key-column").value.trim() || "frame_index");
  formData.set("all_columns", String(mustElement<HTMLInputElement>("validation-all-columns").checked));
  const columns = mustElement<HTMLInputElement>("validation-columns").value.trim();
  if (columns) {
    formData.set("columns", columns);
  }
  return formData;
}

function appendFileAndVoxel(formData: FormData, file: File): void {
  formData.set("file", file);
  appendVoxelFields(formData);
}

function appendVoxelFields(formData: FormData): void {
  const voxel = readVoxel();
  if (voxel === null) {
    return;
  }
  formData.set("voxel_x_um", String(voxel.x_um));
  formData.set("voxel_y_um", String(voxel.y_um));
  formData.set("voxel_z_um", String(voxel.z_um));
}

function appendRoiFields(formData: FormData): void {
  const ids = ["roi-xmin", "roi-xmax", "roi-ymin", "roi-ymax"] as const;
  const names = ["roi_xmin", "roi_xmax", "roi_ymin", "roi_ymax"] as const;
  const values = ids.map((id) => mustElement<HTMLInputElement>(id).value.trim());
  if (values.every((value) => value === "")) {
    return;
  }
  if (values.some((value) => value === "")) {
    throw new Error("ROI requires xmin, xmax, ymin, and ymax.");
  }
  values.forEach((value, index) => {
    formData.set(names[index], value);
  });
}

function appendZRangeFields(formData: FormData): void {
  const zRange = readZRange();
  if (zRange === null) {
    return;
  }
  formData.set("z_min", String(zRange.zmin));
  formData.set("z_max", String(zRange.zmax));
}

/**
 * Real local path from Stack path input, or null if empty / still the placeholder example.
 * Placeholder text is never treated as a real path.
 */
function stackPathOrNull(): string | null {
  const value = mustElement<HTMLInputElement>("path-input").value.trim();
  if (!value) {
    return null;
  }
  // Normalize slashes so pasted placeholder variants are ignored.
  const normalized = value.replace(/\//g, "\\").toLowerCase();
  const placeholderNorm = PATH_PLACEHOLDER.replace(/\//g, "\\").toLowerCase();
  if (normalized === placeholderNorm) {
    return null;
  }
  return value;
}

/**
 * Prefer a non-empty real Stack path over Choose File upload.
 * Browsers cannot expose the disk path of a selected File; user must paste path for large stacks.
 */
function resolveStackSource(): { kind: "path"; path: string } | { kind: "file"; file: File } {
  const path = stackPathOrNull();
  if (path) {
    return { kind: "path", path };
  }
  const file = selectedFile();
  if (file) {
    return { kind: "file", file };
  }
  throw new Error("Choose a stack file or enter a local stack path.");
}

function readVoxel(): VoxelOverride | null {
  const mode = mustElement<HTMLSelectElement>("calibration-mode").value;
  if (mode === "auto") {
    return null;
  }
  return {
    x_um: readNumber("voxel-x"),
    y_um: readNumber("voxel-y"),
    z_um: readNumber("voxel-z")
  };
}

function readProfile(): AnalysisProfile {
  const value = mustElement<HTMLSelectElement>("profile-input").value;
  if (value !== "vesicle" && value !== "rbc" && value !== "active_surfaces") {
    throw new Error("Analysis profile must be vesicle, rbc, or active_surfaces.");
  }
  return value as AnalysisProfile;
}

function updateProfileHelp(): void {
  const profile = mustElement<HTMLSelectElement>("profile-input").value;
  const help = document.getElementById("profile-help");
  const warn = document.getElementById("profile-warning");
  if (help) {
    if (profile === "vesicle") {
      help.textContent =
        "Standard: select one object, set threshold, then Analyze or View 3D Mesh.";
    } else if (profile === "rbc") {
      help.textContent = "RBC: same pipeline with red-blood-cell oriented defaults.";
    } else {
      help.textContent =
        "Experimental 3D surface refinement. Slower; use only if Standard cannot lock the membrane. Requires Select Object.";
    }
  }
  if (warn instanceof HTMLElement) {
    warn.hidden = profile !== "active_surfaces";
  }
}

function readRoi(): RectRoi | null {
  const ids = ["roi-xmin", "roi-xmax", "roi-ymin", "roi-ymax"] as const;
  const values = ids.map((id) => mustElement<HTMLInputElement>(id).value.trim());
  if (values.every((value) => value === "")) {
    return null;
  }
  if (values.some((value) => value === "")) {
    throw new Error("ROI requires xmin, xmax, ymin, and ymax.");
  }
  return {
    xmin: Number(values[0]),
    xmax: Number(values[1]),
    ymin: Number(values[2]),
    ymax: Number(values[3])
  };
}

function readLocalPreviewFrameIndex(): number {
  return readInteger("frame-input");
}

function globalPreviewFrameIndex(localFrame: number): number {
  try {
    const zRange = readZRange();
    if (zRange) {
      return zRange.zmin + localFrame;
    }
  } catch {
    return localFrame;
  }
  return localFrame;
}

function readZRange(): null | { zmin: number; zmax: number } {
  const ids = ["z-min", "z-max"] as const;
  const values = ids.map((id) => mustElement<HTMLInputElement>(id).value.trim());
  if (values.every((value) => value === "")) {
    return null;
  }
  if (values.some((value) => value === "")) {
    throw new Error("Frame range requires start and stop.");
  }
  const zmin = Number(values[0]);
  const zmax = Number(values[1]);
  if (!Number.isInteger(zmin) || !Number.isInteger(zmax)) {
    throw new Error("Frame range values must be integers.");
  }
  if (zmin < 0 || zmax <= zmin) {
    throw new Error("Frame range stop must be greater than start, and start cannot be negative.");
  }
  return { zmin, zmax };
}

function readNumber(id: string): number {
  const value = Number(mustElement<HTMLInputElement>(id).value);
  if (!Number.isFinite(value)) {
    throw new Error(`${id} must be a number.`);
  }
  return value;
}

function readInteger(id: string): number {
  const value = readNumber(id);
  if (!Number.isInteger(value)) {
    throw new Error(`${id} must be an integer.`);
  }
  return value;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function mustElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing #${id}`);
  }
  return element as T;
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toPrecision(6) : "0";
}

function formatInputNumber(value: number): string {
  return Number.isFinite(value) ? String(Number(value.toPrecision(6))) : "0";
}

function formatUnknownNumber(value: unknown): string {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? formatNumber(numberValue) : "";
}

/**
 * Surface API/FastAPI detail text. For upload failures that look like size/memory
 * limits (or bare 500), add guidance to use Stack path instead of Choose File.
 */
function errorMessage(error: unknown, context: "upload" | "general" = "general"): string {
  const base = error instanceof Error ? error.message : "Unknown error";
  if (context !== "upload") {
    return base;
  }
  const lower = base.toLowerCase();
  const looksLikeSizeOrServer =
    lower === "internal server error" ||
    lower.includes("internal server error") ||
    lower.includes("memoryerror") ||
    lower.includes("out of memory") ||
    lower.includes("too large") ||
    lower.includes("request entity") ||
    lower.includes("payload too large") ||
    lower.includes("body exceeded") ||
    lower.includes("upload inspect failed");
  if (!looksLikeSizeOrServer) {
    return base;
  }
  const pathHint =
    "Put the full path in Stack path and Inspect without using Choose File.";
  if (lower === "internal server error" || /^http 500\b/i.test(base)) {
    return `Upload failed (file too large?). ${pathHint}`;
  }
  if (base.includes(pathHint) || base.toLowerCase().includes("stack path")) {
    return base;
  }
  return `${base} ${pathHint}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown, name: string): number {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    throw new Error(`${name} must be a number.`);
  }
  return numberValue;
}

function positiveNumber(value: unknown, name: string): number {
  const numberValue = finiteNumber(value, name);
  if (numberValue <= 0) {
    throw new Error(`${name} must be greater than zero.`);
  }
  return numberValue;
}

function booleanValue(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${name} must be true or false.`);
  }
  return value;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    };
    return entities[char];
  });
}
