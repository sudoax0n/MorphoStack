import "./styles.css";

type VoxelOverride = {
  x_um: number;
  y_um: number;
  z_um: number;
};

type AnalysisProfile = "vesicle" | "rbc";

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
};

type InspectResponse = {
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
};

type AnalyzeResponse = {
  source_path: string;
  profile: AnalysisProfile;
  frame_count: number;
  valid_frame_count: number;
  voxel_size: VoxelOverride;
  voxel_source: string;
  mesh: null | {
    surface_area_um2: number;
    volume_um3: number;
    equivalent_sphere_diameter_um: number;
    sphericity: number;
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

type PreviewResponse = {
  source_path: string;
  frame_index: number;
  width: number;
  height: number;
  threshold: number;
  method: string;
  area_px2: number;
  perimeter_px: number;
  circularity: number;
  image_png_base64: string;
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
};

type ThresholdResponse = {
  source_path: string;
  threshold: number;
  method: string;
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


const app = document.querySelector<HTMLDivElement>("#app");

if (!app) {
  throw new Error("Missing #app mount point");
}

app.innerHTML = `
  <header class="topbar">
    <div>
      <h1>MorphoStack</h1>
      <p>Local morphometry for microscopy Z-stacks</p>
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
  </nav>

  <main class="layout">
    <section class="panel">
      <div class="panel-title">
        <h2><span class="step-badge">1</span> Stack</h2>
        <button id="inspect-btn" type="button">Inspect</button>
      </div>
      <label>
        Stack file
        <input id="file-input" type="file" accept=".tif,.tiff,.lsm,.czi,image/tiff" />
      </label>
      <label>
        Stack path (optional)
        <input id="path-input" type="text" placeholder="D:\\\\lab-data\\\\sample.tif" />
      </label>
      <h3>Calibration</h3>
      <div class="grid">
        <label>
          Voxel X (um)
          <input id="voxel-x" type="number" min="0" step="0.0001" value="1" />
        </label>
        <label>
          Voxel Y (um)
          <input id="voxel-y" type="number" min="0" step="0.0001" value="1" />
        </label>
        <label>
          Voxel Z (um)
          <input id="voxel-z" type="number" min="0" step="0.0001" value="1" />
        </label>
      </div>
      <div id="inspect-output" class="output muted">No stack inspected yet.</div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2><span class="step-badge">2</span> Preview & Analyze</h2>
        <div class="button-row">
          <button id="preview-btn" class="secondary" type="button">Preview</button>
          <button id="mesh-preview-btn" class="secondary" type="button">View 3D Mesh</button>
          <button id="analyze-btn" type="button">Analyze</button>
        </div>
      </div>
      <div class="grid">
        <label>
          Profile
          <select id="profile-input">
            <option value="vesicle" selected>Vesicle</option>
            <option value="rbc">RBC</option>
          </select>
        </label>
        <label class="wide frame-control">
          Preview frame
          <div class="frame-control-row">
            <input id="frame-slider" type="range" min="0" max="0" step="1" value="0" />
            <input id="frame-input" type="number" min="0" step="1" value="0" />
          </div>
        </label>
        <label>
          Threshold
          <input id="threshold-input" type="number" step="1" value="100" />
        </label>
        <label class="button-label">
          Threshold
          <button id="suggest-threshold-btn" class="secondary" type="button">Suggest Threshold</button>
        </label>
        <label class="checkbox-row">
          <input id="mesh-input" type="checkbox" />
          Include 3D mesh
        </label>
        <label class="checkbox-row">
          <input id="fallback-input" type="checkbox" />
          Use fallback contours
        </label>
      </div>
      <fieldset>
        <legend>Object selection (optional)</legend>
        <div class="button-row fieldset-actions">
          <button id="select-object-btn" class="secondary" type="button">Select Object</button>
          <button id="clear-object-btn" class="secondary" type="button">Clear Object</button>
          <span id="object-seed-status" class="inline-status">No object selected</span>
        </div>
      </fieldset>
      <fieldset>
        <legend>XY ROI optional</legend>
        <div class="grid four">
          <input id="roi-xmin" type="number" placeholder="xmin" />
          <input id="roi-xmax" type="number" placeholder="xmax" />
          <input id="roi-ymin" type="number" placeholder="ymin" />
          <input id="roi-ymax" type="number" placeholder="ymax" />
        </div>
        <div class="button-row fieldset-actions">
          <button id="clear-roi-btn" class="secondary" type="button">Clear ROI</button>
          <span id="roi-status" class="inline-status">Full XY frame</span>
        </div>
      </fieldset>
      <fieldset>
        <legend>Frame range for analysis/3D</legend>
        <div class="range-pair">
          <label>
            Start frame
            <input id="z-start-slider" type="range" min="0" max="1" step="1" value="0" />
          </label>
          <label>
            Stop frame
            <input id="z-stop-slider" type="range" min="1" max="1" step="1" value="1" />
          </label>
        </div>
        <div class="grid two">
          <input id="z-min" type="number" min="0" step="1" placeholder="start" />
          <input id="z-max" type="number" min="0" step="1" placeholder="stop" />
        </div>
        <div class="button-row fieldset-actions">
          <button id="use-full-range-btn" class="secondary" type="button">Use Full Stack</button>
          <span id="z-range-status" class="inline-status">Full stack</span>
        </div>
      </fieldset>
      <div id="preview-output" class="preview-output muted">No preview rendered yet.</div>
      <div id="mesh-output" class="mesh-output muted">No 3D mesh rendered yet.</div>
      <div id="analysis-summary" class="output muted">No analysis run yet.</div>
    </section>
  </main>

  <section class="results">
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

  <section class="results">
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

  <section class="results">
    <div class="results-header">
      <h2><span class="step-badge">5</span> Frame Metrics</h2>
      <div class="button-row">
        <button id="download-report-btn" class="secondary" type="button" disabled>Download Report</button>
        <button id="download-manifest-btn" class="secondary" type="button" disabled>Download Manifest</button>
        <button id="download-csv-btn" class="secondary" type="button" disabled>Download CSV</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
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
          </tr>
        </thead>
        <tbody id="results-body">
          <tr><td colspan="11" class="muted">Run an analysis to populate metrics.</td></tr>
        </tbody>
      </table>
    </div>
  </section>
`;

const apiStatus = mustElement<HTMLDivElement>("api-status");
const projectStatus = mustElement<HTMLDivElement>("project-status");
const inspectOutput = mustElement<HTMLDivElement>("inspect-output");
const previewOutput = mustElement<HTMLDivElement>("preview-output");
const meshOutput = mustElement<HTMLDivElement>("mesh-output");
const analysisSummary = mustElement<HTMLDivElement>("analysis-summary");
const batchSummary = mustElement<HTMLDivElement>("batch-summary");
const sweepSummary = mustElement<HTMLDivElement>("sweep-summary");
const validationSummary = mustElement<HTMLDivElement>("validation-summary");
const resultsBody = mustElement<HTMLTableSectionElement>("results-body");
const batchResultsBody = mustElement<HTMLTableSectionElement>("batch-results-body");
const sweepResultsBody = mustElement<HTMLTableSectionElement>("sweep-results-body");
const validationResultsBody = mustElement<HTMLTableSectionElement>("validation-results-body");
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
let latestBatch: BatchAnalyzeResponse | null = null;
let latestSweep: SweepResponse | null = null;
let inspectedFrameCount: number | null = null;
let previewDebounce: number | null = null;
let selectedObjectSeed: ObjectSeed | null = null;
let selectObjectMode = false;

mustElement<HTMLButtonElement>("inspect-btn").addEventListener("click", () => {
  void inspectStack();
});

mustElement<HTMLButtonElement>("analyze-btn").addEventListener("click", () => {
  void analyzeStack();
});

mustElement<HTMLButtonElement>("preview-btn").addEventListener("click", () => {
  void previewStack();
});

mustElement<HTMLButtonElement>("mesh-preview-btn").addEventListener("click", () => {
  void previewMesh();
});

mustElement<HTMLButtonElement>("suggest-threshold-btn").addEventListener("click", () => {
  void suggestThreshold();
});

mustElement<HTMLButtonElement>("clear-roi-btn").addEventListener("click", () => {
  clearRoiFields();
});

mustElement<HTMLButtonElement>("select-object-btn").addEventListener("click", () => {
  selectObjectMode = !selectObjectMode;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = selectObjectMode ? "Cancel Selection" : "Select Object";
  btn.classList.toggle("active", selectObjectMode);
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
  schedulePreview();
});

frameInput.addEventListener("input", () => {
  syncFrameSliderToInput();
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

void refreshHealth();

async function refreshHealth(): Promise<void> {
  try {
    const payload = await apiGet<{ ok: boolean; version: string }>("/api/health");
    apiStatus.textContent = payload.ok ? `API ${payload.version}` : "API unavailable";
    apiStatus.className = payload.ok ? "status ok" : "status warn";
  } catch {
    apiStatus.textContent = "API offline";
    apiStatus.className = "status warn";
  }
}

async function loadProjectFromFile(): Promise<void> {
  try {
    const file = selectedRequiredFile("project-file-input", "Project JSON");
    const payload = JSON.parse(await file.text()) as unknown;
    const settings = validateProjectSettings(payload);
    applyProjectSettings(settings);
    projectStatus.textContent = file.name;
    projectStatus.className = "status ok";
  } catch (error) {
    projectStatus.textContent = errorMessage(error);
    projectStatus.className = "status warn";
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
  } catch (error) {
    projectStatus.textContent = errorMessage(error);
    projectStatus.className = "status warn";
  }
}

async function inspectStack(): Promise<void> {
  inspectOutput.textContent = "Inspecting...";
  try {
    const file = selectedFile();
    const payload = file
      ? await apiUploadPost<InspectResponse>("/api/upload/inspect", inspectUploadForm(file))
      : await apiPost<InspectResponse>("/api/inspect", {
          path: readPath(),
          voxel: readVoxel()
        });
    inspectOutput.innerHTML = `
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Grayscale: ${payload.grayscale_shape.join(" x ")}<br />
      Color: ${payload.color_shape.join(" x ")}<br />
      Voxel: x=${formatNumber(payload.voxel_size.x_um)} um,
      y=${formatNumber(payload.voxel_size.y_um)} um,
      z=${formatNumber(payload.voxel_size.z_um)} um<br />
      Voxel source: ${escapeHtml(payload.voxel_source)}
    `;
    inspectedFrameCount = payload.grayscale_shape[0] ?? null;
    syncZRangeControls({ initializeFullRange: true });
  } catch (error) {
    inspectOutput.textContent = errorMessage(error);
  }
}

async function previewStack(): Promise<void> {
  previewOutput.textContent = "Rendering preview...";
  try {
    const file = selectedFile();
    const roi = readRoi();
    const zRange = readZRange();
    const payload = file
      ? await apiUploadPost<PreviewResponse>("/api/upload/preview", previewUploadForm(file))
      : await apiPost<PreviewResponse>("/api/preview", {
          path: readPath(),
          threshold: readNumber("threshold-input"),
          frame_index: readInteger("frame-input"),
          voxel: readVoxel(),
          roi,
          z_range: zRange,
          prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
          object_seed: selectedObjectSeed
        });
    renderPreview(payload, roi);
  } catch (error) {
    previewOutput.textContent = errorMessage(error);
  }
}

function schedulePreview(): void {
  if (!hasStackInput()) {
    return;
  }
  if (previewDebounce !== null) {
    window.clearTimeout(previewDebounce);
  }
  previewDebounce = window.setTimeout(() => {
    previewDebounce = null;
    void previewStack();
  }, 220);
}

function hasStackInput(): boolean {
  return selectedFile() !== null || mustElement<HTMLInputElement>("path-input").value.trim() !== "";
}

async function previewMesh(): Promise<void> {
  meshOutput.textContent = "Rendering 3D mesh...";
  try {
    const file = selectedFile();
    const payload = file
      ? await apiUploadPost<MeshPreviewResponse>("/api/upload/mesh-preview", meshPreviewUploadForm(file))
      : await apiPost<MeshPreviewResponse>("/api/mesh-preview", {
          path: readPath(),
          threshold: readNumber("threshold-input"),
          profile: readProfile(),
          voxel: readVoxel(),
          roi: readRoi(),
          z_range: readZRange(),
          prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
          downsample: 2,
          max_faces: 12000,
          object_seed: selectedObjectSeed
        });
    renderMeshPreview(payload);
  } catch (error) {
    meshOutput.textContent = errorMessage(error);
  }
}

async function suggestThreshold(): Promise<void> {
  previewOutput.textContent = "Suggesting threshold...";
  try {
    const file = selectedFile();
    const payload = file
      ? await apiUploadPost<ThresholdResponse>("/api/upload/threshold", thresholdUploadForm(file))
      : await apiPost<ThresholdResponse>("/api/threshold", {
          path: readPath(),
          method: "auto",
          voxel: readVoxel(),
          roi: readRoi(),
          z_range: readZRange()
        });
    mustElement<HTMLInputElement>("threshold-input").value = formatInputNumber(payload.threshold);
    previewOutput.innerHTML = `
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Suggested threshold: ${formatNumber(payload.threshold)} (${escapeHtml(payload.method)})
    `;
  } catch (error) {
    previewOutput.textContent = errorMessage(error);
  }
}

async function analyzeStack(): Promise<void> {
  latestAnalysis = null;
  downloadCsvButton.disabled = true;
  downloadReportButton.disabled = true;
  downloadManifestButton.disabled = true;
  analysisSummary.textContent = "Analyzing...";
  resultsBody.innerHTML = `<tr><td colspan="11" class="muted">Running analysis...</td></tr>`;
  try {
    const file = selectedFile();
    const payload = file
      ? await apiUploadPost<AnalyzeResponse>("/api/upload/analyze", analyzeUploadForm(file))
      : await apiPost<AnalyzeResponse>("/api/analyze", {
          path: readPath(),
          threshold: readNumber("threshold-input"),
          profile: readProfile(),
          voxel: readVoxel(),
          roi: readRoi(),
          z_range: readZRange(),
          include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
          prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked,
          object_seed: selectedObjectSeed
        });
    renderAnalysis(payload);
  } catch (error) {
    analysisSummary.textContent = errorMessage(error);
    resultsBody.innerHTML = `<tr><td colspan="11" class="muted">Analysis failed.</td></tr>`;
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
    const payload = await apiUploadPost<BatchAnalyzeResponse>("/api/upload/batch", batchUploadForm(files));
    renderBatch(payload);
  } catch (error) {
    batchSummary.textContent = errorMessage(error);
    batchResultsBody.innerHTML = `<tr><td colspan="8" class="muted">Batch analysis failed.</td></tr>`;
  }
}

async function runSweep(): Promise<void> {
  latestSweep = null;
  downloadSweepButton.disabled = true;
  downloadSweepReportButton.disabled = true;
  sweepSummary.textContent = "Running threshold sweep...";
  sweepResultsBody.innerHTML = `<tr><td colspan="7" class="muted">Running sweep...</td></tr>`;
  try {
    const file = selectedFile();
    const payload = file
      ? await apiUploadPost<SweepResponse>("/api/upload/sweep", sweepUploadForm(file))
      : await apiPost<SweepResponse>("/api/sweep", {
          path: readPath(),
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
    renderSweep(payload);
  } catch (error) {
    sweepSummary.textContent = errorMessage(error);
    sweepResultsBody.innerHTML = `<tr><td colspan="7" class="muted">Sweep failed.</td></tr>`;
  }
}

async function validateCsv(): Promise<void> {
  validationSummary.textContent = "Validating...";
  validationResultsBody.innerHTML = `<tr><td colspan="5" class="muted">Running validation...</td></tr>`;
  try {
    const payload = await apiUploadPost<ValidationResponse>("/api/upload/validate", validationUploadForm());
    renderValidation(payload);
  } catch (error) {
    validationSummary.textContent = errorMessage(error);
    validationResultsBody.innerHTML = `<tr><td colspan="5" class="muted">Validation failed.</td></tr>`;
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

function renderPreview(payload: PreviewResponse, renderedRoi: RectRoi | null): void {
  previewOutput.innerHTML = `
    <div class="preview-canvas">
      <img
        id="preview-image"
        src="data:image/png;base64,${payload.image_png_base64}"
        width="${payload.width}"
        height="${payload.height}"
        alt="Segmentation preview for frame ${payload.frame_index}"
      />
      <div id="roi-selection" class="roi-selection" hidden></div>
    </div>
    <div>
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Frame ${payload.frame_index}, ${escapeHtml(payload.method)} contour<br />
      Area ${formatNumber(payload.area_px2)} px2,
      perimeter ${formatNumber(payload.perimeter_px)} px,
      circularity ${formatNumber(payload.circularity)}
      ${selectedObjectSeed ? `<br /><span style="color:#fde047">Object seed: (${selectedObjectSeed.x}, ${selectedObjectSeed.y}) frame ${selectedObjectSeed.frame_index}</span>` : ""}
    </div>
  `;
  attachPreviewRoiSelector(payload, renderedRoi);
}

function attachPreviewRoiSelector(payload: PreviewResponse, renderedRoi: RectRoi | null): void {
  const image = mustElement<HTMLImageElement>("preview-image");
  const selection = mustElement<HTMLDivElement>("roi-selection");
  let start: { x: number; y: number } | null = null;

  image.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    start = pointerToImagePoint(event, image);
    image.setPointerCapture(event.pointerId);
    if (!selectObjectMode) {
      drawSelection(selection, start.x, start.y, start.x, start.y);
    }
  });

  image.addEventListener("pointermove", (event) => {
    if (!start || selectObjectMode) {
      return;
    }
    const current = pointerToImagePoint(event, image);
    drawSelection(selection, start.x, start.y, current.x, current.y);
  });

  image.addEventListener("pointerup", (event) => {
    if (!start) {
      return;
    }
    const end = pointerToImagePoint(event, image);
    image.releasePointerCapture(event.pointerId);

    if (selectObjectMode) {
      // Single-click sets the object seed.
      applyObjectSeedClick(end, image, payload, renderedRoi);
      start = null;
      return;
    }

    applyDraggedRoi(start, end, image, payload, renderedRoi);
    start = null;
  });

  image.addEventListener("pointercancel", () => {
    start = null;
    selection.hidden = true;
  });
}

function pointerToImagePoint(event: PointerEvent, image: HTMLImageElement): { x: number; y: number } {
  const rect = image.getBoundingClientRect();
  return {
    x: clamp(event.clientX - rect.left, 0, rect.width),
    y: clamp(event.clientY - rect.top, 0, rect.height)
  };
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

function applyDraggedRoi(
  start: { x: number; y: number },
  end: { x: number; y: number },
  image: HTMLImageElement,
  payload: PreviewResponse,
  renderedRoi: RectRoi | null
): void {
  const rect = image.getBoundingClientRect();
  const dragWidth = Math.abs(end.x - start.x);
  const dragHeight = Math.abs(end.y - start.y);
  if (dragWidth < 4 || dragHeight < 4 || rect.width <= 0 || rect.height <= 0) {
    mustElement<HTMLDivElement>("roi-selection").hidden = true;
    return;
  }

  const baseX = renderedRoi?.xmin ?? 0;
  const baseY = renderedRoi?.ymin ?? 0;
  const scaleX = payload.width / rect.width;
  const scaleY = payload.height / rect.height;
  const xmin = baseX + Math.floor(Math.min(start.x, end.x) * scaleX);
  const xmax = baseX + Math.ceil(Math.max(start.x, end.x) * scaleX);
  const ymin = baseY + Math.floor(Math.min(start.y, end.y) * scaleY);
  const ymax = baseY + Math.ceil(Math.max(start.y, end.y) * scaleY);

  setRoiFields({
    xmin,
    xmax: Math.max(xmax, xmin + 1),
    ymin,
    ymax: Math.max(ymax, ymin + 1)
  });
}

function applyObjectSeedClick(
  point: { x: number; y: number },
  image: HTMLImageElement,
  payload: PreviewResponse,
  renderedRoi: RectRoi | null
): void {
  const rect = image.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  const baseX = renderedRoi?.xmin ?? 0;
  const baseY = renderedRoi?.ymin ?? 0;
  const scaleX = payload.width / rect.width;
  const scaleY = payload.height / rect.height;
  const imgX = baseX + Math.round(point.x * scaleX);
  const imgY = baseY + Math.round(point.y * scaleY);

  selectedObjectSeed = { x: imgX, y: imgY, frame_index: payload.frame_index };
  selectObjectMode = false;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = "Select Object";
  btn.classList.remove("active");
  updateObjectSeedStatus();
  void previewStack();
}

function clearObjectSeed(): void {
  selectedObjectSeed = null;
  selectObjectMode = false;
  const btn = mustElement<HTMLButtonElement>("select-object-btn");
  btn.textContent = "Select Object";
  btn.classList.remove("active");
  updateObjectSeedStatus();
}

function updateObjectSeedStatus(): void {
  const status = mustElement<HTMLSpanElement>("object-seed-status");
  if (selectObjectMode) {
    status.textContent = "Click on the target object in the preview";
    status.className = "inline-status warn";
  } else if (selectedObjectSeed) {
    status.textContent = `Seed: (${selectedObjectSeed.x}, ${selectedObjectSeed.y}) frame ${selectedObjectSeed.frame_index}`;
    status.className = "inline-status ok";
  } else {
    status.textContent = "No object selected";
    status.className = "inline-status";
  }
}

function updateFrameRange(): void {
  const maxFrame = effectivePreviewFrameCount() - 1;
  frameSlider.max = String(maxFrame);
  frameInput.max = String(maxFrame);
  const clamped = clamp(Math.trunc(Number(frameInput.value) || 0), 0, maxFrame);
  frameInput.value = String(clamped);
  frameSlider.value = String(clamped);
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
      zRangeStatus.textContent = `Using frames ${start} to ${stop - 1} (${stop - start} frames)`;
      zRangeStatus.className = "inline-status";
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
}

function updateRoiStatus(): void {
  try {
    const roi = readRoi();
    roiStatus.textContent = roi ? `ROI ${roi.xmin}:${roi.xmax}, ${roi.ymin}:${roi.ymax}` : "Full XY frame";
    roiStatus.className = "inline-status";
  } catch (error) {
    roiStatus.textContent = errorMessage(error);
    roiStatus.className = "inline-status warn";
  }
}

function renderMeshPreview(payload: MeshPreviewResponse): void {
  if (!payload.has_mesh || payload.vertices.length === 0 || payload.faces.length === 0) {
    meshOutput.textContent = "No 3D mesh could be created from the current threshold/ROI/Z range.";
    meshOutput.className = "mesh-output muted";
    return;
  }

  meshOutput.className = "mesh-output";
  meshOutput.innerHTML = `
    <div>
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Display mesh: ${payload.vertex_count} vertices, ${payload.face_count} faces, downsample x${payload.downsample}<br />
      View: aligned contour stack<br />
      Surface ${formatNumber(payload.surface_area_um2)} um2,
      volume ${formatNumber(payload.volume_um3)} um3,
      sphericity ${formatNumber(payload.sphericity)}
    </div>
    <iframe id="mesh-frame" title="3D mesh preview"></iframe>
  `;
  mustElement<HTMLIFrameElement>("mesh-frame").srcdoc = meshPreviewHtml(payload);
}

function meshPreviewHtml(payload: MeshPreviewResponse): string {
  const bounds = meshBounds(payload.vertices);
  const x = payload.vertices.map((vertex) => vertex[0] - bounds.xmin);
  const y = payload.vertices.map((vertex) => vertex[1] - bounds.ymin);
  const z = payload.vertices.map((vertex) => vertex[2] - bounds.zmin);
  const i = payload.faces.map((face) => face[0]);
  const j = payload.faces.map((face) => face[1]);
  const k = payload.faces.map((face) => face[2]);
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body, #plot { width: 100%; height: 100%; margin: 0; background: #0f172a; }
  </style>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>
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
    Plotly.newPlot("plot", [trace], layout, { responsive: true, displaylogo: false });
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

function renderAnalysis(payload: AnalyzeResponse): void {
  latestAnalysis = payload;
  downloadCsvButton.disabled = payload.rows.length === 0;
  downloadReportButton.disabled = false;
  downloadManifestButton.disabled = false;
  const meshText = payload.mesh
    ? `<br />3D surface: ${formatNumber(payload.mesh.surface_area_um2)} um2, volume: ${formatNumber(payload.mesh.volume_um3)} um3, sphericity: ${formatNumber(payload.mesh.sphericity)}`
    : "";
  const warningText =
    payload.warnings.length > 0
      ? `<div class="warning-list">${payload.warnings.map((warning) => `<div><strong>${escapeHtml(warning.severity)}</strong>: ${escapeHtml(warning.message)}</div>`).join("")}</div>`
      : "";
  const summaryText = renderSummaryMetrics(payload.summary);
  analysisSummary.innerHTML = `
    <strong>${escapeHtml(payload.source_path)}</strong><br />
    Profile: ${escapeHtml(payload.profile)}<br />
    Frames: ${payload.frame_count}, valid: ${payload.valid_frame_count}<br />
    Voxel source: ${escapeHtml(payload.voxel_source)}${summaryText}${meshText}
    ${warningText}
  `;

  if (payload.rows.length === 0) {
    resultsBody.innerHTML = `<tr><td colspan="11" class="muted">No rows returned.</td></tr>`;
    return;
  }

  resultsBody.innerHTML = payload.rows
    .map(
      (row) => `
        <tr>
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
  anchor.download = csvFilename(latestAnalysis.source_path);
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
  anchor.download = reportFilename(latestAnalysis.source_path);
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
  anchor.download = sweepFilename(latestSweep.source_path);
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
  anchor.download = sweepReportFilename(latestSweep.source_path);
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
  anchor.download = manifestFilename(latestAnalysis.source_path);
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
    lines.push(`## First ${rows.length} Frame Rows`, "");
    lines.push("| Frame | Contour | Area (um2) | Perimeter (um) | Circularity | Deformation index |");
    lines.push("| ---: | :---: | ---: | ---: | ---: | ---: |");
    rows.forEach((row) => {
      lines.push(
        `| ${row.frame_index} | ${row.has_contour ? "yes" : "no"} | ${formatNumber(row.area_um2)} | ${formatNumber(row.perimeter_um)} | ${formatNumber(row.circularity)} | ${formatNumber(row.deformation_index)} |`
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
    voxel_size: readVoxel(),
    roi: roi ?? undefined,
    z_range: zRange ?? undefined,
    include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
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
    if (payload.profile !== "vesicle" && payload.profile !== "rbc") {
      throw new Error("Project profile must be vesicle or rbc.");
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
    mustElement<HTMLInputElement>("voxel-x").value = formatInputNumber(settings.voxel_size.x_um);
    mustElement<HTMLInputElement>("voxel-y").value = formatInputNumber(settings.voxel_size.y_um);
    mustElement<HTMLInputElement>("voxel-z").value = formatInputNumber(settings.voxel_size.z_um);
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

function rowsToCsv(rows: AnalysisRow[]): string {
  const lines = [
    CSV_COLUMNS.join(","),
    ...rows.map((row) => CSV_COLUMNS.map((column) => csvCell(row[column])).join(","))
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

async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return parseResponse<T>(response);
}

async function apiUploadPost<T>(url: string, formData: FormData): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    body: formData
  });
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? response.statusText);
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

function analyzeUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("threshold", String(readNumber("threshold-input")));
  formData.set("profile", readProfile());
  formData.set("include_mesh", String(mustElement<HTMLInputElement>("mesh-input").checked));
  formData.set("prefer_opencv", String(!mustElement<HTMLInputElement>("fallback-input").checked));
  appendRoiFields(formData);
  appendZRangeFields(formData);
  return formData;
}

function previewUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("threshold", String(readNumber("threshold-input")));
  formData.set("frame_index", String(readInteger("frame-input")));
  formData.set("prefer_opencv", String(!mustElement<HTMLInputElement>("fallback-input").checked));
  appendRoiFields(formData);
  appendZRangeFields(formData);
  return formData;
}

function meshPreviewUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("threshold", String(readNumber("threshold-input")));
  formData.set("profile", readProfile());
  formData.set("prefer_opencv", String(!mustElement<HTMLInputElement>("fallback-input").checked));
  formData.set("downsample", "2");
  formData.set("max_faces", "12000");
  appendRoiFields(formData);
  appendZRangeFields(formData);
  return formData;
}

function thresholdUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("method", "auto");
  appendRoiFields(formData);
  appendZRangeFields(formData);
  return formData;
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

function sweepUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("start", String(readNumber("sweep-start")));
  formData.set("stop", String(readNumber("sweep-stop")));
  formData.set("step", String(readNumber("sweep-step")));
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

function readPath(): string {
  const value = mustElement<HTMLInputElement>("path-input").value.trim();
  if (!value) {
    throw new Error("Stack path is required.");
  }
  return value;
}

function readVoxel(): VoxelOverride {
  return {
    x_um: readNumber("voxel-x"),
    y_um: readNumber("voxel-y"),
    z_um: readNumber("voxel-z")
  };
}

function readProfile(): AnalysisProfile {
  const value = mustElement<HTMLSelectElement>("profile-input").value;
  if (value !== "vesicle" && value !== "rbc") {
    throw new Error("Analysis profile must be vesicle or rbc.");
  }
  return value;
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
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
