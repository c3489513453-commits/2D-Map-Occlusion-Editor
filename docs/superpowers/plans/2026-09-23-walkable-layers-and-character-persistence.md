# Walkable Layers and Character Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add folder-capable walkable layers, green editing, project-persistent test characters, and merged walkable export.

**Architecture:** Store walkable layers and folders separately on each map while reusing layer/folder domain types and commands. Expose dedicated REST routes, adapt the existing canvas editor and layer tree by mode, and save the project-level test character as a PNG asset plus scale metadata.

**Tech Stack:** Python dataclasses, FastAPI, Pillow/NumPy, vanilla JavaScript canvas, pytest, browser HTML tests.

**Spec:** `docs/superpowers/specs/2026-09-23-walkable-layers-and-character-persistence-design.md`

## Global Constraints

- Existing projects and their resource masks must load unchanged.
- Legacy `walkable_mask_path` pixels migrate without loss.
- Resource and walkable masks remain independent and may overlap.
- No new runtime dependency.

## Review Focus

- Legacy projects with and without a previous single walkable mask.
- Hidden walkable layers excluded from movement and optional export.
- Pending paint operations before map/project changes.
- Invalid, transparent, or oversized character PNG data.
- Resource-layer bottom-line and editing behavior remains unchanged.

---

### Task 1: Walkable data model and migration

**Files:** Modify `map_cutout/domain.py`, `map_cutout/project_store.py`; test `tests/map_cutout/test_project_store.py`.

**Interfaces:** Produces `MapState.walkable_layers`, `MapState.walkable_folders`, and legacy migration; consumed by Tasks 2–4.

- [ ] Add failing save/load and legacy migration tests.
- [ ] Run focused tests and confirm missing fields/migration failures.
- [ ] Add fields, create no default layer for new maps, and migrate legacy path on load.
- [ ] Run focused and full project-store tests.

### Task 2: Walkable REST operations and merged export

**Files:** Modify `map_cutout/web_app.py`, `map_cutout/exporter.py`; test `tests/map_cutout/test_api.py`, `tests/map_cutout/test_batch_export.py`.

**Interfaces:** Produces dedicated walkable layer/folder CRUD, paint/mask routes, and union export; consumed by Task 3.

- [ ] Add failing tests for create, paint, patch, folder, delete, and merged export.
- [ ] Run focused tests and confirm 404/format failures.
- [ ] Implement routes and union export while excluding resource-only actions.
- [ ] Run API and export suites.

### Task 3: Mode-aware frontend and green editing

**Files:** Modify `map_cutout/static/app.js`, `canvas_editor.js`, `inference_controls.js`, `layer_tree.js`, `index.html`, `styles.css`; test `tests/web/canvas_editor.test.html`, `layer_tree.test.html`.

**Interfaces:** Consumes Task 2 routes; produces folder-capable walkable panel, green tools, union collision, and pending-save safety.

- [ ] Add failing browser tests for union movement, green preview, and walkable layer-tree actions.
- [ ] Confirm browser tests fail for missing behavior.
- [ ] Implement mode-specific lists/actions and editor colors/routes.
- [ ] Run all browser tests.

### Task 4: Character persistence and final integration

**Files:** Modify `map_cutout/domain.py`, `project_store.py`, `web_app.py`, `static/app.js`, `exporter.py`, user guide; test API/project/browser suites.

**Interfaces:** Produces project-level character save/load endpoints and automatic browser restoration.

- [ ] Add failing tests for character asset metadata, validation, and reload response.
- [ ] Confirm focused failures.
- [ ] Implement bounded base64 PNG persistence and scale restoration; update cache versions and documentation.
- [ ] Run full Python suite, JavaScript syntax checks, and all browser tests; restart port 7860 and verify current project.
