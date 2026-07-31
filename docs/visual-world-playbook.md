# MorphoStack Visual World Playbook

### Full README image campaign — Grok Imagine production bible

**Codename:** *See it before you read it*  
**Goal:** Anyone who opens the GitHub repo understands MorphoStack’s power in **one scroll**, mostly from pictures.

This is the **complete, reproducible workflow** used to build the entire MorphoStack public image set for:

- root [`README.md`](../README.md) (hero, feature grid, brand board, logo lockup)
- [`docs/public/`](public/) (canonical art library)
- [`apps/web/public/`](../apps/web/public/) (favicon + header logo)

Not a vibe essay. A **shot list + prompt book + post-production pipeline** you can run again.

---

## Table of contents

1. [Mission & storyboard](#1-mission--storyboard)  
2. [Art direction system](#2-art-direction-system)  
3. [Tools & quality bar](#3-tools--quality-bar-grok-imagine)  
4. [The full shot list](#4-the-full-shot-list-readme-campaign)  
5. [Batch generation day](#5-batch-generation-day-exact-workflow)  
6. [Every production prompt](#6-every-production-prompt-copy-paste)  
7. [Rename & QA after the race](#7-rename--qa-after-the-race)  
8. [Assemble the README](#8-assemble-the-readme-layout-recipe)  
9. [Logo extraction & favicon](#9-logo-extraction--favicon-pipeline)  
10. [What we deliberately removed](#10-what-we-deliberately-removed)  
11. [Extend the campaign](#11-extend-the-campaign-new-shots)  
12. [Final asset inventory](#12-final-asset-inventory)  
13. [Commit checklist](#13-commit-checklist)

---

## 1. Mission & storyboard

### 1.1 Why so many images?

A text-only scientific README dies on GitHub. MorphoStack needed a **visual argument**:

| Scroll zone | Job of the pictures |
| --- | --- |
| **Title + logo** | “This is a real product.” |
| **Hero banner** | Emotion + category in 1 second (vesicle in a dark lab). |
| **Feature grid (6 cells)** | Product capabilities without reading paragraphs. |
| **Brand board** | Identity system: logo + terminal + science world. |
| **Body text** | Install, CLI, license — for people who stayed. |

Design rule borrowed from brand-kit thinking:

> Quiet → loud → technical → atmospheric → detailed.  
> Not six equally noisy squares.

### 1.2 README storyboard (wireframe)

```text
┌──────────────────────────────────────────────────────────┐
│  [logo]  MorphoStack                                     │
│  tagline · profiles · CLI/API/UI                         │
│  ████████████████  HERO BANNER  ████████████████         │
│  morphostack · mst · v1.0.0 · dual license               │
├──────────────────────────────────────────────────────────┤
│  SEE IT BEFORE YOU READ IT                               │
│  ┌─────────────────┐  ┌─────────────────┐                │
│  │ pipeline-concept│  │ mesh-3d         │                │
│  └─────────────────┘  └─────────────────┘                │
│  ┌─────────────────┐  ┌─────────────────┐                │
│  │ vesicle-glow    │  │ rbc-photoreal   │                │
│  └─────────────────┘  └─────────────────┘                │
│  ┌─────────────────┐  ┌─────────────────┐                │
│  │ crowded-seed    │  │ active-surfaces │                │
│  └─────────────────┘  └─────────────────┘                │
│  ████████████  brand-board  ████████████                 │
├──────────────────────────────────────────────────────────┤
│  What it does · tables · quick start · docs · license    │
└──────────────────────────────────────────────────────────┘
```

### 1.3 One-sentence creative thesis

> **Horizontal microscopy slices stack into a single measurable membrane body — geometry with honesty.**

Every generated frame must reinforce **Z-depth**, **measurement**, or **object selection** in a dark scientific void.

---

## 2. Art direction system

### 2.1 Palette law (non-negotiable)

| Role | Color family | Notes |
| --- | --- | --- |
| Void / UI chrome | Charcoal / navy `#0f172a` | Matches web topbar |
| Structure / membrane | Cyan / teal | Primary scientific accent |
| Energy / seed / RBC rim | Coral / warm red | Secondary; never rainbow |
| Neutrals | Soft white / slate | Wordmarks only on brand board |

**Banned:** generic purple AI gradients, green matrix rain, clipart DNA helices, stock “scientist + hologram.”

### 2.2 Style mix (intentional variety)

The README is not one style — it’s a **controlled portfolio**:

| Style | Used for | Why |
| --- | --- | --- |
| **Flat / vector brand mark** | Logo plates, brand board TL | Scales to favicon |
| **Cinematic product still** | Hero, mesh | “Ship-quality” emotion |
| **Editorial infographic** | Pipeline triptych | Explains process without paragraphs |
| **Photoreal microscopy aesthetic** | Vesicle ring, RBC | Scientific credibility |
| **Diagram sketch** | Active surfaces | Signals experimental method |
| **Narrative concept art** | Crowded seed field | Shows the hard product problem |

### 2.3 Metaphor dictionary

| Product idea | Visual translation |
| --- | --- |
| Z-stack | Layered plates, ghosted slices, card deck of planes |
| Threshold contour | Bright ring on dark field |
| Object seed | Amber point + tracking trail |
| Mesh export | Triangle wireframe membrane shell |
| Calibration honesty | Optional caliper / tick (never fake numbers) |
| Crowded field | Many cells, one highlighted |
| Active surfaces | Rough contour → smooth force-guided ring |

---

## 3. Tools & quality bar (Grok Imagine)

### 3.1 What we used

| Tool | Role |
| --- | --- |
| **Grok Imagine `image_gen`** | All concept / brand / photoreal stills |
| **Visual inspection** (open each file) | Rename after batch race |
| **Pillow + NumPy** | Logo crop, square pad, favicon ladder, ICO |
| **Markdown tables** | README layout (works on GitHub) |
| **Vite `public/`** | App favicon + header logo |

### 3.2 Imagine craft rules we enforced

1. **2–5 sentence prompts**, natural prose (not keyword spam).  
2. Order: **subject → state → setting → style → composition → light → key detail**.  
3. **Positive description** (what to include), not endless negatives.  
4. **One scene per image.**  
5. **Aspect ratio is load-bearing** (`1:1` marks, `16:9` heroes/grids, `4:3` sketches).  
6. **No long readable UI text** — models garble it; keep wordmarks minimal on brand boards only.  
7. **Parallelize independent shots**, then **serialize rename**.  
8. **Exact crops / favicons = code**, not more generation.

### 3.3 When NOT to use Imagine

| Need | Use instead |
| --- | --- |
| Real lab validation frames | Real pipeline outputs (private / `validation/`) — **not** public README |
| Exact metrics charts | Code / CSV / matplotlib |
| Clean multi-size favicon | Pillow resize from extracted logo |
| Precise brand grid extraction | Color-mask crop from brand board |

---

## 4. The full shot list (README campaign)

This is every **major** image created for the public face of MorphoStack.

### 4.1 Primary campaign set (generate these)

| # | Canonical file | Aspect | README role | Style |
| ---: | --- | --- | --- | --- |
| 1 | `logo-mark.jpg` | 1:1 | Alternate mark / concept | Vector sphere-of-slices |
| 2 | `hero-banner.jpg` | 16:9 | Full-width emotional open | Cinematic lab + vesicle |
| 3 | `pipeline-concept.jpg` | 16:9 | Grid cell: pipeline | Dark editorial infographic |
| 4 | `vesicle-glow.jpg` | 1:1 | Grid cell: vesicle profile | Photoreal confocal aesthetic |
| 5 | `rbc-photoreal.jpg` | 1:1 | Grid cell: RBC profile | Photoreal SEM/hybrid |
| 6 | `mesh-3d.jpg` | 1:1 | Grid cell: mesh export | 3D product still |
| 7 | `crowded-seed-concept.jpg` | 16:9 | Grid cell: crowded fields | Concept illustration |
| 8 | `active-surfaces-sketch.jpg` | 4:3 | Grid cell: active surfaces | Textbook diagram sketch |
| 9 | `brand-board.jpg` | 16:9 | Closing identity board | 2×2 brand kit |

### 4.2 Derived from brand board (do not re-Imagine first)

| # | File | Source | Role |
| ---: | --- | --- | --- |
| 10 | `logo-from-board.png` / `logo.png` | Crop TL stacked plates | Official logo |
| 11 | `logo-lockup-from-board.png` | Crop stack + wordmark | Optional lockup |
| 12 | `logo-icon-256.png` | Resize | Medium icon |
| 13 | `favicon-32.png` / `favicon-48.png` | Resize | Docs / debug |
| 14 | `apps/web/public/logo.png` | Copy/resize | Web header |
| 15 | `apps/web/public/favicon.ico` | Multi-size ICO | Browser tab |
| 16 | `apps/web/public/favicon.png` | 32 PNG | Fallback favicon |
| 17 | `apps/web/public/apple-touch-icon.png` | 180 PNG | Touch icon |

### 4.3 Explicitly NOT in the public campaign (anymore)

| Removed | Why |
| --- | --- |
| `preview-dopc-seed.png` | Real lab pipeline preview — confidential |
| `preview-crowded-czi.png` | Real crowded CZI — confidential |
| `preview-rbc-seed.png` | Real RBC field — confidential |

**Creative rule:** public README uses **art that explains**; lab truth lives under `validation/` for people who clone and run.

---

## 5. Batch generation day (exact workflow)

### 5.1 Session setup

```text
Working tree: MorphoStack repo
Output staging: session images/ folder (tool default)
Final home:     docs/public/
Web home:       apps/web/public/
```

### 5.2 Chronological steps (what we actually did)

```text
STEP 1  Write creative thesis + palette law (Section 2)
STEP 2  Write shot list mapped to README zones (Section 4)
STEP 3  Fire PARALLEL image_gen for shots 1–5 (logo, hero, pipeline, vesicle, RBC)
STEP 4  Fire PARALLEL image_gen for shots 6–9 (mesh, crowded, AS, brand board)
STEP 5  Download / receive 1.jpg … N.jpg from Imagine
STEP 6  OPEN EVERY FILE — tag content in a scratch list
STEP 7  Copy to docs/public/ with CANONICAL names (Section 7)
STEP 8  Build README feature grid + hero + brand board (Section 8)
STEP 9  Extract logo from brand-board (Section 9)
STEP 10 Wire logo into README title + web favicon/header
STEP 11 Strip confidential real previews from public docs
STEP 12 Visual pass on GitHub-style markdown preview
```

### 5.3 Parallelism rule

```text
OK in parallel:  any set of independent scenes (no shared character sheet)
NOT in parallel: rename/copy (must be serial after visual ID)
NOT first-line:  logo extraction (needs brand-board on disk)
```

### 5.4 Filename race warning (we got burned)

Imagine completion order **≠** prompt order.  
In this project, early copies were **wrong**:

| Wrong assumption | Actual content |
| --- | --- |
| “1.jpg is logo” | Sometimes vesicle / other |
| “logo-mark.jpg” after first copy pass | Temporarily held RBC until corrected |

**Fix:** always open → tag → rename. Never script blind `1→logo`.

---

## 6. Every production prompt (copy-paste)

Paste into Grok Imagine / `image_gen` with the listed aspect ratio.

---

### Shot 1 — `logo-mark.jpg` · 1:1 · sphere-of-slices concept

```text
Premium app logo mark for MorphoStack, a biophysics microscopy morphometry tool.
Minimal geometric icon: stacked translucent horizontal slices forming a soft 3D
vesicle sphere silhouette, with a thin cyan contour line and a small measurement
tick mark. Dark charcoal background, flat vector brand mark, high contrast,
no text, no letters, clean scalable icon suitable for GitHub avatar,
scientific software aesthetic, not cartoon.
```

**Creative intent:** Soft “measured sphere” — good illustration, weaker favicon.  
**README use:** optional; superseded as *official* mark by brand-board plates.

---

### Shot 2 — `hero-banner.jpg` · 16:9 · emotional open

```text
Wide cinematic hero banner for MorphoStack scientific software. Dark lab
atmosphere, glowing confocal Z-stack of a giant unilamellar vesicle floating
as translucent cyan membrane rings through space, volumetric light, subtle
grid of micrometers, abstract data sparks, premium biotech product marketing
still, no readable text, no UI chrome, photoreal mixed with scientific
illustration, deep navy and teal palette.
```

**Creative intent:** Instant category (“microscopy + 3D membrane”) + premium feel.  
**README use:** full-width under tagline.

---

### Shot 3 — `pipeline-concept.jpg` · 16:9 · explain the product

```text
Scientific concept illustration of a microscopy Z-stack pipeline: left side
shows grayscale confocal slices stacked like cards, middle shows a seeded
contour on a membrane ring, right shows a smooth 3D mesh reconstruction of
a vesicle. Clean dark editorial infographic style, cyan and white linework,
sparse labels only as abstract shapes not words, professional biophysics
software marketing graphic.
```

**Creative intent:** Three-beat story: **stack → contour → mesh**.  
**README caption:** *Pipeline — stack → seed/contour → mesh metrics*

---

### Shot 4 — `vesicle-glow.jpg` · 1:1 · vesicle / GUV profile

```text
Photoreal confocal fluorescence microscopy aesthetic of a soft giant
unilamellar vesicle (GUV) membrane in a dark field, thin bright cyan ring,
slight deflation asymmetry, high-end scientific photomicrograph look,
shallow depth of field glow, no text, no scale bar numbers, realistic
soft-matter biophysics imagery.
```

**Creative intent:** Paper-adjacent visual language for vesicle mode.  
**README caption:** *Vesicle / GUV profile*

---

### Shot 5 — `rbc-photoreal.jpg` · 1:1 · RBC profile

```text
Photoreal scanning electron and light microscopy hybrid aesthetic of a red
blood cell biconcave disc, deep red to magenta membrane, dark background,
scientific museum quality, soft rim lighting, highly detailed surface,
no text, premium medical biophysics still life.
```

**Creative intent:** Second profile without looking like a stock medical ad.  
**README caption:** *RBC profile (shared engine; lab metrics evolving)*

---

### Shot 6 — `mesh-3d.jpg` · 1:1 · mesh export feature

```text
Premium 3D scientific visualization of a translucent membrane mesh
reconstructed from Z-stack contours, triangular surface mesh with soft cyan
wireframe edges and pearl-white faces, floating in dark void, studio lighting,
biophysics morphometry software render style, no text, clean product hero
for mesh export feature.
```

**Creative intent:** Make OBJ/STL/PLY/GLB export feel tangible.  
**README caption:** *Mesh export — OBJ / STL / PLY / GLB*

---

### Shot 7 — `crowded-seed-concept.jpg` · 16:9 · crowded fields

```text
Dark scientific illustration of a crowded confocal field with multiple
circular membrane objects, one object highlighted with a bright amber seed
point and tracking trail through Z slices shown as ghosted layers, cyan
secondary objects dimmed, concept art for single-object selection in
multi-vesicle microscopy, no text, editorial biotech graphic.
```

**Creative intent:** The **differentiator** — one seed, many objects.  
**README caption:** *Crowded fields — seed one object, track in Z*

---

### Shot 8 — `active-surfaces-sketch.jpg` · 4:3 · experimental profile

```text
Abstract scientific sketch of active surfaces refinement: a rough pixelated
threshold contour transforming into a smooth surfel membrane ring around a
vesicle cross-section, dashed force vectors gently pointing to membrane edge,
cyan and soft white on deep navy, textbook biophysics diagram aesthetic
without letters or numbers.
```

**Creative intent:** “Experimental” should look **methodical**, not sci-fi.  
**README caption:** *Active surfaces — experimental refinement*

---

### Shot 9 — `brand-board.jpg` · 16:9 · identity system + logo source

```text
Premium dark brand-kit style board for MorphoStack biophysics software in a
clean 2×2 grid with gutters: top-left stacked-slice logo mark with optional
compact wordmark, top-right terminal-like monochrome command strip abstract
without readable real secrets, bottom-left confocal vesicle glow photo crop,
bottom-right red blood cell field. Charcoal canvas, cyan and coral accents,
sparse, cinematic, no fake paragraphs, scientific developer-tool identity.
```

**Creative intent:** Mini brand deck — logo, product surface, science world.  
**README use:** full-width closer under the feature grid.  
**Critical side effect:** top-left panel is the **official logo source** for extraction.

**Brand board panel map:**

```text
┌────────────────────┬────────────────────┐
│ TL: stacked plates │ TR: terminal / CLI │
│     + wordmark     │     atmosphere     │
├────────────────────┼────────────────────┤
│ BL: vesicle world  │ BR: RBC world      │
└────────────────────┴────────────────────┘
```

---

## 7. Rename & QA after the race

### 7.1 Tag sheet (fill while opening files)

```text
session file | content tag              | canonical name
-------------|--------------------------|---------------------------
1.jpg        | ???                      | 
2.jpg        | ???                      | 
...          |                          | 
```

### 7.2 Acceptance criteria per shot

| Shot | Pass if… |
| --- | --- |
| Hero | Readable at full README width; dark; one clear vesicle story |
| Pipeline | Three stages distinguishable without reading text |
| Vesicle | Dark field ring; not a cartoon bubble |
| RBC | Biconcave recognizable; not a red blob |
| Mesh | Triangles visible; feels exportable geometry |
| Crowded | Many objects + one highlight (seed story) |
| AS sketch | Before/after or force idea clear |
| Brand board | Four panels aligned; logo mark sharp in TL |
| Logo extract | Plates only; favicon still reads at 32×32 |

### 7.3 Copy command pattern (after tagging)

```powershell
$dst = "docs\public"
# ONLY after visual ID — example mapping, replace with your tags:
Copy-Item "session\images\A.jpg" "$dst\hero-banner.jpg" -Force
Copy-Item "session\images\B.jpg" "$dst\pipeline-concept.jpg" -Force
# ...
```

---

## 8. Assemble the README (layout recipe)

### 8.1 Title row — logo left of heading

```markdown
<table>
  <tr>
    <td width="72" valign="middle">
      <img src="docs/public/logo.png" alt="MorphoStack logo" width="64" height="64" />
    </td>
    <td valign="middle">
      <h1>MorphoStack</h1>
    </td>
  </tr>
</table>
```

### 8.2 Hero

```markdown
<p align="center">
  <img src="docs/public/hero-banner.jpg" alt="MorphoStack hero" width="100%" />
</p>
```

### 8.3 Feature grid — 3×2 table

```markdown
## See it before you read it

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/public/pipeline-concept.jpg" width="100%" /><br/>
      <sub><b>Pipeline</b> — stack → seed/contour → mesh metrics</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/public/mesh-3d.jpg" width="100%" /><br/>
      <sub><b>Mesh export</b> — OBJ / STL / PLY / GLB</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/public/vesicle-glow.jpg" width="100%" /><br/>
      <sub><b>Vesicle / GUV profile</b></sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/public/rbc-photoreal.jpg" width="100%" /><br/>
      <sub><b>RBC profile</b></sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/public/crowded-seed-concept.jpg" width="100%" /><br/>
      <sub><b>Crowded fields</b> — seed one object, track in Z</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/public/active-surfaces-sketch.jpg" width="100%" /><br/>
      <sub><b>Active surfaces</b> — experimental refinement</sub>
    </td>
  </tr>
</table>
```

### 8.4 Brand board closer

```markdown
<p align="center">
  <img src="docs/public/brand-board.jpg" alt="MorphoStack brand board" width="90%" />
</p>
```

### 8.5 Captions that sell features

Write captions as **capability + verb**, not “Image 3”:

| Bad | Good |
| --- | --- |
| Cool mesh | Mesh export — OBJ / STL / PLY / GLB |
| Cells | Crowded fields — seed one object, track in Z |
| Diagram | Active surfaces — experimental refinement |

### 8.6 Rhythm after images

Only after the visual block: **What it does**, install, CLI, architecture, docs map, citation, license.  
Pictures first; manuals second.

---

## 9. Logo extraction & favicon pipeline

### 9.1 Why extract instead of re-generate

The brand board already contains a **product-grade stacked-plate mark** with cyan/coral that survives 32×32.  
Re-prompting “same logo” drifts. **Crop is truth.**

### 9.2 Comparison we ran

| Asset | Design | Official? |
| --- | --- | --- |
| Brand-board TL stack → `logo.png` | 3 isometric plates cyan/coral | **Yes** (app + README) |
| `logo-mark.jpg` | Soft sphere of slices + caliper | Supporting art only |

Mean pixel difference on 128×128 resize was ~**36** — correctly **not** the same mark.

### 9.3 Extraction algorithm (tight)

1. Crop top-left panel of `brand-board.jpg` (~5.5%–49.5% of width/height).  
2. Mask **cyan + coral** pixels (plate colors).  
3. Ignore panel edges + tiny corner badge.  
4. Keep upper ~52% of mark (drop wordmark).  
5. Trim thin registration dashes via column pixel counts.  
6. Pad onto square charcoal canvas.  
7. Assert content fraction **> 0.12** (we hit ~0.39).  
8. Export 512 / 256 / 48 / 32 + ICO multi-size into `apps/web/public/`.

Reference implementation ideas live in the “Phase C” spirit — promote to `scripts/extract_brand_logo.py` if you re-run often.

### 9.4 Failure modes we hit

| Fail | Symptom | Fix |
| --- | --- | --- |
| Whole-board crop | Vesicles + terminal in “logo” | TL panel fractions only |
| Huge square padding | Favicon blank | Tight bbox + content assert |
| Wordmark in icon | Muddy 16px text | Cut lower mask band |
| Left coral dash | Noise on left | Column-count trim |

### 9.5 Web wiring

- `index.html` → favicon.ico / favicon.png / apple-touch-icon  
- Header → flex brand row: `/logo.png` + white title (light-on-dark topbar)

---

## 10. What we deliberately removed

During ship prep we also **killed** public use of real MorphoStack pipeline previews (DOPC / CZI / RBC seed frames).

| Reason | Action |
| --- | --- |
| Confidential lab imagery | Delete `docs/public/preview-*.png` |
| README was advertising private data | Remove “Real validation previews” table |
| Docs validation page embedded them | Strip image block from `docs/validation.md` |
| Prevent re-add | `docs/public/preview-*.png` in `.gitignore` |

**Philosophy:**  
Art sells the idea. Validation folders prove the science to people who should see lab data.

---

## 11. Extend the campaign (new shots)

When adding a feature visual:

1. Name the **product beat** (batch, doctor, manifests, sweep…).  
2. Translate to one metaphor from Section 2.3.  
3. Write one Imagine prompt with the skeleton below.  
4. Choose aspect for placement (grid cell `1:1` or banner `16:9`).  
5. Generate → visual rename → drop into README table.  
6. Keep palette law.

### Prompt skeleton

```text
[Subject: one MorphoStack capability as a physical object].
[State: stacked / meshed / seeded / measured / batched].
[Setting: dark field or dark lab void].
[Style: scientific product illustration OR photoreal microscopy aesthetic].
[Composition: centered, generous negative space, no UI chrome].
[Light: soft cyan volumetric glow, optional coral accent].
[Text: none].
[Palette: charcoal, cyan, coral only].
```

### Ideas not yet shot (optional future)

| Feature | Visual idea |
| --- | --- |
| `morphostack doctor` | Diagnostic crosshair over a healthy stack glyph |
| Batch mode | Deck of translucent slice cards fanning out |
| Manifest / SHA-256 | Sealed report tablet with subtle hash texture (no real hashes) |
| Threshold sweep | Series of rings brightening across a strip |
| Frame exclusion | One ghosted slice with a clean cut mark |

---

## 12. Final asset inventory

### 12.1 `docs/public/` (README library)

| File | Role |
| --- | --- |
| `brand-board.jpg` | Identity board + logo source |
| `hero-banner.jpg` | README hero |
| `pipeline-concept.jpg` | Grid: pipeline |
| `mesh-3d.jpg` | Grid: mesh |
| `vesicle-glow.jpg` | Grid: vesicle |
| `rbc-photoreal.jpg` | Grid: RBC |
| `crowded-seed-concept.jpg` | Grid: crowded seed |
| `active-surfaces-sketch.jpg` | Grid: active surfaces |
| `logo-mark.jpg` | Alternate sphere mark |
| `logo.png` / `logo-from-board.png` | Official stacked-plate logo |
| `logo-lockup-from-board.png` | Stack + wordmark |
| `logo-icon-256.png` | Medium icon |
| `favicon-32.png` / `favicon-48.png` | Small icons |
| `apple-touch-icon.png` | Touch size (docs copy) |

### 12.2 `apps/web/public/` (runtime chrome)

| File | Role |
| --- | --- |
| `logo.png` | Topbar brand |
| `favicon.ico` | Tab icon multi-size |
| `favicon.png` | PNG favicon |
| `apple-touch-icon.png` | iOS-style touch icon |

### 12.3 README image map (path → zone)

| Path | Zone |
| --- | --- |
| `docs/public/logo.png` | Title left of H1 |
| `docs/public/hero-banner.jpg` | Hero |
| `docs/public/pipeline-concept.jpg` | Grid (1,1) |
| `docs/public/mesh-3d.jpg` | Grid (1,2) |
| `docs/public/vesicle-glow.jpg` | Grid (2,1) |
| `docs/public/rbc-photoreal.jpg` | Grid (2,2) |
| `docs/public/crowded-seed-concept.jpg` | Grid (3,1) |
| `docs/public/active-surfaces-sketch.jpg` | Grid (3,2) |
| `docs/public/brand-board.jpg` | Closer |

---

## 13. Commit checklist

Before committing a visual refresh:

- [ ] All 9 primary shots exist under `docs/public/` with canonical names  
- [ ] Opened each file once after rename (no race leftovers)  
- [ ] Feature grid captions match product truth  
- [ ] Hero not cropped awkwardly at full width  
- [ ] Official logo = brand-board plates, not sphere mark  
- [ ] Favicon readable at 32×32  
- [ ] Web header logo + light title on dark topbar  
- [ ] Zero real-lab `preview-*.png` in public docs  
- [ ] Brand board retained for future re-extract  
- [ ] This playbook still matches filenames on disk  

---

## 14. One-page “do it again” card

```text
1. Re-read thesis: slices → measured membrane, cyan+coral on charcoal
2. Generate 9 shots (prompts in §6) with correct aspect ratios
3. Visually tag every output; rename into docs/public/
4. Wire README: logo | hero | 3×2 grid | UI shot | brand board
5. Extract logo:  python scripts/extract_brand_logo.py
6. UI + OG + compress:
     python scripts/prepare_public_images.py --ui path/to/ui-screenshot.png
7. Optional: image_edit one weak grid cell with logo.png as reference
8. Never put confidential lab previews in docs/public
9. QA checklist §13 → commit when ready
```

## 15. Maintenance scripts (shipping pack)

| Script | Purpose |
| --- | --- |
| `scripts/extract_brand_logo.py` | Crop stacked-plate logo from `brand-board.jpg` → docs + web favicons |
| `scripts/prepare_public_images.py` | Build `og-card.jpg` (1200×630), sanitize UI screenshot, compress public JPGs |

```powershell
.\.venv\Scripts\python scripts\extract_brand_logo.py
.\.venv\Scripts\python scripts\prepare_public_images.py --ui .\path\to\screenshot.png
```

README should include:

- concept feature grid  
- **one** real UI shot (`ui-app.jpg`) with redacted local paths  
- brand board  
- optional note that `og-card.jpg` is for link unfurls / social

---

## Provenance

This playbook records the MorphoStack **public README image campaign** run during GitHub ship prep:

- Parallel Grok Imagine batch for a full visual world  
- Visual rename after filename races  
- Brand-board logo extraction for product chrome  
- Feature-grid README designed to sell capabilities before install text  
- Removal of confidential real validation previews from public marketing surfaces  

**Maintainer mantra:**  
*Measure the stack. Trust the units. Ship the run — and let the pictures do the first minute of selling.*
