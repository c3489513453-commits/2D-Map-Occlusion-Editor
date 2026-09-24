# Resource Walkability Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add editable per-resource walkability boundaries and export one final collision mask combining manual roads with resource-above-boundary regions.

**Architecture:** Store boundary polylines on resource layers. A focused `walkability.py` module owns adaptive generation, line rasterization, obstacle-priority composition, and is shared by API and exporter. The existing canvas polyline editor is extended with an exclusive resource-walkability mode.

**Tech Stack:** Python, NumPy, Pillow, FastAPI, vanilla JavaScript canvas, pytest, browser HTML tests.

**Spec:** `docs/superpowers/specs/2026-09-24-resource-walkability-boundaries-design.md`

## Global Constraints

- Preserve all existing masks, `road1`, occlusion lines, character data, and paths.
- Old JSON without `walkable_boundary_lines` loads an empty list.
- Auto generation fills only missing boundaries.
- Obstacle height is `max(height * 0.10, min(height * 0.30, width * 0.50))`.
- Obstacles win when resources overlap.
- Runtime and export use identical composition semantics.

## Review Focus

- Empty and one-pixel masks do not produce invalid lines; Task 1 tests them.
- A short line leaves uncovered resource pixels blocked; Task 1 tests it.
- Overlapping passable/obstacle resources remain blocked; Tasks 1 and 5 test it.
- Hidden resources still participate in collision; Tasks 2 and 5 test it.
- Mask loading never temporarily allows unrestricted walking; Task 4 tests it.

---

### Task 1: Domain persistence and geometry

**Files:**
- Create: `map_cutout/walkability.py`
- Modify: `map_cutout/domain.py`
- Modify: `map_cutout/project_store.py`
- Create: `tests/map_cutout/test_walkability.py`
- Modify: `tests/map_cutout/test_project_store.py`

**Interfaces:**
- Produces `LayerState.walkable_boundary_lines`.
- Produces `adaptive_walkable_boundary(mask)`, `resource_walkable_and_obstacle(mask, lines)`, and `compose_final_walkable(manual_masks, resources)`.

- [ ] Write failing tests for square, tall-thin, empty and one-pixel masks; curved/short lines; obstacle-priority overlap; and old-project loading.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests\map_cutout\test_walkability.py tests\map_cutout\test_project_store.py -q`; expect failures for missing fields/functions.
- [ ] Implement the field and geometry functions. Interpolate covered X positions, treat uncovered resource pixels as obstacles, then compute `candidates & ~all_obstacles`.
- [ ] Re-run the same tests; expect PASS.
- [ ] Commit with `git commit -m "feat: model resource walkability boundaries"`.

### Task 2: Boundary APIs and server-side road clipping

**Files:**
- Modify: `map_cutout/web_app.py`
- Modify: `tests/map_cutout/test_api.py`

**Interfaces:**
- Consumes Task 1 geometry.
- Produces PUT `/layers/{layer_id}/walkable-boundary-lines`, POST `/walkable-boundary-lines/auto`, and resource-union clipping for every manual-road write path.

- [ ] Write failing tests proving PUT normalization/persistence, adaptive auto generation, skip-without-overwrite, idempotent second auto run, and clipping for brush, polygon, box-recognition and point-preview commits.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests\map_cutout\test_api.py -q -k "walkable_boundary or walkable_paint_excludes_resource"`; expect missing routes or overlapping pixels.
- [ ] Implement endpoints and a single resource-mask-union helper; apply `after &= ~resource_union` on all manual walkable mutations.
- [ ] Re-run the targeted tests; expect PASS.
- [ ] Commit with `git commit -m "feat: add resource walkability boundary APIs"`.

### Task 3: Resource-boundary editor and automatic action

**Files:**
- Modify: `map_cutout/static/layer_tree.js`
- Modify: `map_cutout/static/canvas_editor.js`
- Modify: `map_cutout/static/app.js`
- Modify: `map_cutout/static/index.html`
- Modify: `tests/web/layer_tree.test.html`
- Modify: `tests/web/canvas_editor.test.html`

**Interfaces:**
- Consumes Task 2 endpoints.
- Produces `onEditWalkableBoundary(id)`, “编辑可走/退出编辑”, `setWalkableBoundaryEditing(id)`, node dragging, segment selection/Delete, “画可走线”, right-click completion, and top-level “自动可走”.

- [ ] Add failing browser assertions for button toggling, mutually exclusive edit modes, node movement, segment deletion, right-click completion, and auto-action status.
- [ ] Start the test server on port 7875; expect `FAIL:` in `layer_tree.test.html` or `canvas_editor.test.html`.
- [ ] Extend the shared polyline interaction code with separate walkability draft/selection state and wire API callbacks.
- [ ] Reload both pages; expect title `PASS` and no console errors.
- [ ] Commit with `git commit -m "feat: edit resource walkability boundaries"`.

### Task 4: Purple manual-road UI and edit toggle

**Files:**
- Modify: `map_cutout/static/styles.css`
- Modify: `map_cutout/static/canvas_editor.js`
- Modify: `map_cutout/static/layer_tree.js`
- Modify: `map_cutout/static/app.js`
- Modify: `tests/web/canvas_editor.test.html`
- Modify: `tests/web/layer_tree.test.html`

**Interfaces:**
- Consumes Task 3 edit state.
- Produces purple road overlays/previews, “编辑/退出编辑” walkable-row toggle, and immediate local clipping against resource masks.

- [ ] Add failing assertions for purple RGBA, active edit-button exit, local brush/polygon clipping, and movement blocking while configured masks load.
- [ ] Reload browser tests; expect `FAIL:` for missing behavior.
- [ ] Implement purple rendering, row toggle, resource mask registration, and local clipping; retain server authority.
- [ ] Reload browser tests; expect `PASS` and no console errors.
- [ ] Commit with `git commit -m "feat: refine walkable layer editing"`.

### Task 5: Final-mask export, regression, and live verification

**Files:**
- Modify: `map_cutout/exporter.py`
- Modify: `tests/map_cutout/test_batch_export.py`
- Modify: `docs/map-cutout-user-guide.md`

**Interfaces:**
- Consumes Task 1 composition.
- Produces final `walkable.png`, JSON v3 `walkableBoundaryLines`, and `walkable.composition`.

- [ ] Write failing export tests for manual-outside-resource plus resource-above-line pixels, overlap obstacle priority, boundary-only resources in `occluders`, JSON v3, and no duplicate root assets.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests\map_cutout\test_batch_export.py -q`; expect failures because export still unions manual roads and emits v2.
- [ ] Call shared composition from exporter, include resources with either line type, emit v3 fields, and document the package.
- [ ] Run export tests, then `node --check` on edited JS, full `.venv\Scripts\python.exe -m pytest tests\map_cutout -q`, all three browser tests, and `git diff --check`; expect all green.
- [ ] Save the live project, record `road1` ID and nonzero pixel count, restart exactly one service on 7861, and verify both values are unchanged.
- [ ] Export the washerwoman map to a unique temporary directory; inspect JSON v3 and final pixels, then remove only that verified temporary directory.
- [ ] Commit with `git commit -m "feat: export resource-aware walkability"`.

