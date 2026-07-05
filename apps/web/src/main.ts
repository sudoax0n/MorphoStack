import "./styles.css";

type VoxelOverride = {
  x_um: number;
  y_um: number;
  z_um: number;
};

type AnalysisProfile = "vesicle" | "rbc";

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
  roi?: {
    xmin: number;
    xmax: number;
    ymin: number;
    ymax: number;
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

  <main class="layout">
    <section class="panel">
      <div class="panel-title">
        <h2>Stack Input</h2>
        <button id="inspect-btn" type="button">Inspect</button>
      </div>
      <label>
        Stack file
        <input id="file-input" type="file" accept=".tif,.tiff,.czi,image/tiff" />
      </label>
      <label>
        Stack path (optional)
        <input id="path-input" type="text" placeholder="D:\\\\lab-data\\\\sample.tif" />
      </label>
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
        <h2>Analysis</h2>
        <div class="button-row">
          <button id="preview-btn" class="secondary" type="button">Preview</button>
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
        <label>
          Frame
          <input id="frame-input" type="number" min="0" step="1" value="0" />
        </label>
        <label>
          Threshold
          <input id="threshold-input" type="number" step="1" value="100" />
        </label>
        <label class="button-label">
          Threshold tool
          <button id="suggest-threshold-btn" class="secondary" type="button">Suggest</button>
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
        <legend>ROI</legend>
        <div class="grid four">
          <input id="roi-xmin" type="number" placeholder="xmin" />
          <input id="roi-xmax" type="number" placeholder="xmax" />
          <input id="roi-ymin" type="number" placeholder="ymin" />
          <input id="roi-ymax" type="number" placeholder="ymax" />
        </div>
      </fieldset>
      <div id="preview-output" class="preview-output muted">No preview rendered yet.</div>
      <div id="analysis-summary" class="output muted">No analysis run yet.</div>
    </section>
  </main>

  <section class="results">
    <div class="results-header">
      <h2>Batch Analysis</h2>
      <div class="button-row">
        <button id="batch-analyze-btn" type="button">Analyze Batch</button>
        <button id="download-batch-report-btn" class="secondary" type="button" disabled>Download Batch Report</button>
        <button id="download-batch-btn" class="secondary" type="button" disabled>Download Batch CSV</button>
      </div>
    </div>
    <label class="batch-file-label">
      Stack files
      <input id="batch-file-input" type="file" accept=".tif,.tiff,.czi,image/tiff" multiple />
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
      <h2>Threshold Sweep</h2>
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
      <h2>CSV Validation</h2>
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
      <h2>Frame Metrics</h2>
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
let latestAnalysis: AnalyzeResponse | null = null;
let latestBatch: BatchAnalyzeResponse | null = null;
let latestSweep: SweepResponse | null = null;

mustElement<HTMLButtonElement>("inspect-btn").addEventListener("click", () => {
  void inspectStack();
});

mustElement<HTMLButtonElement>("analyze-btn").addEventListener("click", () => {
  void analyzeStack();
});

mustElement<HTMLButtonElement>("preview-btn").addEventListener("click", () => {
  void previewStack();
});

mustElement<HTMLButtonElement>("suggest-threshold-btn").addEventListener("click", () => {
  void suggestThreshold();
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
  } catch (error) {
    inspectOutput.textContent = errorMessage(error);
  }
}

async function previewStack(): Promise<void> {
  previewOutput.textContent = "Rendering preview...";
  try {
    const file = selectedFile();
    const payload = file
      ? await apiUploadPost<PreviewResponse>("/api/upload/preview", previewUploadForm(file))
      : await apiPost<PreviewResponse>("/api/preview", {
          path: readPath(),
          threshold: readNumber("threshold-input"),
          frame_index: readInteger("frame-input"),
          voxel: readVoxel(),
          roi: readRoi(),
          prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked
        });
    renderPreview(payload);
  } catch (error) {
    previewOutput.textContent = errorMessage(error);
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
          roi: readRoi()
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
          include_mesh: mustElement<HTMLInputElement>("mesh-input").checked,
          prefer_opencv: !mustElement<HTMLInputElement>("fallback-input").checked
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

function renderPreview(payload: PreviewResponse): void {
  previewOutput.innerHTML = `
    <img
      src="data:image/png;base64,${payload.image_png_base64}"
      width="${payload.width}"
      height="${payload.height}"
      alt="Segmentation preview for frame ${payload.frame_index}"
    />
    <div>
      <strong>${escapeHtml(payload.source_path)}</strong><br />
      Frame ${payload.frame_index}, ${escapeHtml(payload.method)} contour<br />
      Area ${formatNumber(payload.area_px2)} px2,
      perimeter ${formatNumber(payload.perimeter_px)} px,
      circularity ${formatNumber(payload.circularity)}
    </div>
  `;
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
  return {
    version: 1,
    profile: readProfile(),
    threshold: readNumber("threshold-input"),
    voxel_size: readVoxel(),
    roi: roi ?? undefined,
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
  return formData;
}

function previewUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("threshold", String(readNumber("threshold-input")));
  formData.set("frame_index", String(readInteger("frame-input")));
  formData.set("prefer_opencv", String(!mustElement<HTMLInputElement>("fallback-input").checked));
  appendRoiFields(formData);
  return formData;
}

function thresholdUploadForm(file: File): FormData {
  const formData = new FormData();
  appendFileAndVoxel(formData, file);
  formData.set("method", "auto");
  appendRoiFields(formData);
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
  return formData;
}

function validationUploadForm(): FormData {
  const formData = new FormData();
  formData.set("expected_file", selectedRequiredFile("expected-csv-input", "Reference CSV"));
  formData.set("actual_file", selectedRequiredFile("actual-csv-input", "New CSV"));
  formData.set("tolerance", String(readNumber("validation-tolerance")));
  formData.set("key_column", mustElement<HTMLInputElement>("validation-key-column").value.trim() || "frame_index");
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

function readRoi(): null | { xmin: number; xmax: number; ymin: number; ymax: number } {
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
