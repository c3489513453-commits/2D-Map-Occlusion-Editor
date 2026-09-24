import {footprintIsBehindLine, nearestLineIndex, nearestLineNode} from "/static/occlusion_preview.js?v=footprint-occlusion2";

export function screenToImage(x, y, view) {
  return {x: (x - view.offsetX) / view.scale, y: (y - view.offsetY) / view.scale};
}

export function imageToScreen(x, y, view) {
  return {x: x * view.scale + view.offsetX, y: y * view.scale + view.offsetY};
}

export function maskPixelsToTintedRgba(pixels, color, opacity = .42) {
  const maxAlpha = Math.round(255 * opacity);
  for (let i = 0; i < pixels.length; i += 4) {
    const luminance = Math.max(pixels[i], pixels[i + 1], pixels[i + 2]);
    pixels[i] = color[0];
    pixels[i + 1] = color[1];
    pixels[i + 2] = color[2];
    pixels[i + 3] = Math.round(luminance / 255 * maxAlpha);
  }
  return pixels;
}

export function lassoPayload(points, tool) {
  return {
    shape: "polygon",
    points: points.map(([x, y]) => [Math.round(x), Math.round(y)]),
    value: tool === "lasso-add" ? 255 : 0,
  };
}

export function canCloseLasso(points, point, scale, threshold = 14) {
  if (!points || points.length < 3 || !point) return false;
  const start = points[0];
  const dx = (point.x - start.x) * scale;
  const dy = (point.y - start.y) * scale;
  return Math.hypot(dx, dy) <= threshold;
}

export function topMaskId(layers, contains) {
  for (let index = layers.length - 1; index >= 0; index -= 1) {
    const layer = layers[index];
    if (!layer || layer.kind === "original" || layer.visible === false || !layer.mask_path) continue;
    if (contains(layer)) return layer.id;
  }
  return null;
}

export function lassoCommitPoints(points, closingPoint, scale, threshold = 14) {
  if (!canCloseLasso(points, closingPoint, scale, threshold)) return null;
  return points.map(point => [point.x, point.y]);
}

export function footprintIsWalkable(contains, position, footpoint, scale = 1) {
  if (!contains || !position || !footpoint) return true;
  const left = Number.isFinite(footpoint.left) ? footpoint.left : footpoint.x;
  const right = Number.isFinite(footpoint.right) ? footpoint.right : footpoint.x;
  const offsets = [left, (left + right) / 2, right]
    .map(value => (value - footpoint.x) * scale);
  return offsets.every(offset => contains(position.x + offset, position.y));
}

const LASSO_TOOLS = ["lasso-add", "lasso-subtract"];
const EDIT_TOOLS = ["brush", "eraser", ...LASSO_TOOLS];

export class CanvasEditor extends EventTarget {
  constructor(shell, stage, image, canvas) {
    super();
    this.shell = shell;
    this.stage = stage;
    this.image = image;
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.view = {scale: 1, offsetX: 0, offsetY: 0};
    this.tool = "select";
    this.points = [];
    this.drag = null;
    this.lasso = null;
    this.space = false;
    this.brushRadius = 14;
    this.layers = [];
    this.maskImages = new Map();
    this.maskOverlays = new Map();
    this.maskVersions = new Map();
    this.maskCanvases = new Map();
    this.maskLoading = new Map();
    this.maskLoadToken = new Map();
    this.maskGeneration = 0;
    this.maskEditLayerId = null;
    this.loadedMapId = null;
    this.character = null;
    this.characterDeleteMode = false;
    this.characterScale = 1;
    this.previewMode = false;
    this.occlusionLayerId = null;
    this.lineField = "occlusion_lines";
    this.lineEvent = "occlusion-lines";
    this.occlusionDraft = null;
    this.selectedOcclusionLine = null;
    this.hiddenOcclusionInfo = new Set();
    this.foregroundOverlays = new Map();
    this.resourceAlphaMasks = new Map();
    this.walkableLayerIds = new Set();
    this.resourceMaskIds = new Set();
    this.finalWalkableMask = null;
    this.finalWalkableMapId = null;
    this.walkableConfigured = false;
    image.addEventListener("load", () => {
      this.maskOverlays.clear();
      this.foregroundOverlays.clear();
      if (this.character) {
        this.character.position = {x: image.naturalWidth / 2, y: image.naturalHeight / 2};
      }
      if (this.previewImage) this.previewOverlay = this.createTintedMask(this.previewImage, [240, 184, 91], .55);
      this.resize();
    });
    this.bind();
  }

  setTool(tool) {
    const stayingInLasso = LASSO_TOOLS.includes(this.tool) && LASSO_TOOLS.includes(tool);
    if (stayingInLasso) {
      if (this.lasso) this.lasso.tool = tool;
    } else if (!LASSO_TOOLS.includes(tool)) {
      this.lasso = null;
    }
    this.tool = tool;
    this.points = [];
    this.render();
  }

  setLayers(layers) {
    this.layers = layers;
    this.foregroundOverlays.clear();
    this.loadMasks();
  }

  setLocked(locked) { this.locked = locked; }

  setMaskEdit(layerId) { this.maskEditLayerId = layerId || null; }

  setWalkableLayers(layerIds) {
    this.walkableLayerIds = new Set(layerIds || []);
    if (this.walkableLayerIds.size) this.walkableConfigured = true;
  }

  setResourceMasks(layerIds) { this.resourceMaskIds = new Set(layerIds || []); }

  setWalkableConfigured(configured) { this.walkableConfigured = Boolean(configured); }

  async loadFinalWalkable(mapId) {
    this.finalWalkableMapId = mapId || null;
    this.finalWalkableMask = null;
    if (!mapId) return;
    const image = new Image();
    await new Promise(resolve => {
      image.onload = resolve;
      image.onerror = resolve;
      image.src = `/api/maps/${mapId}/walkable/final-mask?v=${Date.now()}`;
    });
    if (this.finalWalkableMapId !== mapId || !image.naturalWidth) return;
    try { this.finalWalkableMask = await createImageBitmap(image); }
    catch { this.finalWalkableMask = image; }
  }

  setCharacter(image, footpoint) {
    this.character = {
      image,
      footpoint,
      position: {
        x: this.image.naturalWidth / 2,
        y: this.image.naturalHeight / 2,
      },
    };
    this.render();
  }

  clearCharacter() {
    this.character = null;
    this.characterDeleteMode = false;
    if (this.drag?.type === "character") this.drag = null;
    this.render();
  }

  setCharacterScale(scale) {
    this.characterScale = Math.max(.1, Math.min(5, Number(scale) || 1));
    this.render();
  }

  setCharacterDeleteMode(enabled) {
    this.characterDeleteMode = Boolean(enabled && this.character);
    this.render();
  }

  setPreviewMode(enabled) {
    this.previewMode = Boolean(enabled);
    this.occlusionDraft = null;
    if (this.previewMode) {
      this.lasso = null;
      this.points = [];
      this.drag = null;
    }
    this.render();
  }

  setOcclusionEditing(layerId) {
    this.lineField = "occlusion_lines";
    this.lineEvent = "occlusion-lines";
    this.occlusionLayerId = layerId || null;
    this.occlusionDraft = null;
    this.selectedOcclusionLine = null;
    this.drag = null;
    if (layerId) this.setTool("select");
    else this.render();
  }

  setWalkableBoundaryEditing(layerId) {
    this.lineField = "walkable_boundary_lines";
    this.lineEvent = "walkable-boundary-lines";
    this.occlusionLayerId = layerId || null;
    this.occlusionDraft = null;
    this.selectedOcclusionLine = null;
    this.drag = null;
    if (layerId) this.setTool("select");
    else this.render();
  }

  setOcclusionDrawing(layerId) { this.setOcclusionEditing(layerId); }

  setOcclusionInfoHidden(ids) {
    this.hiddenOcclusionInfo = new Set(ids || []);
    this.render();
  }

  cancelOcclusion() {
    this.occlusionDraft = null;
    this.selectedOcclusionLine = null;
    this.render();
  }

  commitOcclusionLine() {
    if (!this.occlusionLayerId || !this.occlusionDraft || this.occlusionDraft.length < 2) return false;
    const layer = this.layers.find(item => item.id === this.occlusionLayerId);
    const line = this.occlusionDraft.map(item => [Math.round(item.x), Math.round(item.y)]);
    const lines = [...(layer?.[this.lineField] || []), line];
    if (layer) layer[this.lineField] = lines;
    this.occlusionDraft = null;
    this.dispatchEvent(new CustomEvent(this.lineEvent, {
      detail: {layerId: this.occlusionLayerId, lines},
    }));
    return true;
  }

  deleteSelectedOcclusionLine() {
    if (!this.selectedOcclusionLine) return false;
    const {layerId, index} = this.selectedOcclusionLine;
    const layer = this.layers.find(item => item.id === layerId);
    if (!layer) return false;
    const field = this.selectedOcclusionLine.field || this.lineField;
    const lines = (layer[field] || []).filter((_, lineIndex) => lineIndex !== index);
    layer[field] = lines;
    this.selectedOcclusionLine = null;
    const eventName = field === "walkable_boundary_lines" ? "walkable-boundary-lines" : "occlusion-lines";
    this.dispatchEvent(new CustomEvent(eventName, {detail: {layerId, lines}}));
    return true;
  }

  occlusionLinesFor(layer) {
    if (this.drag?.type === "occlusion-node" && this.drag.layerId === layer.id
        && this.drag.field === this.lineField) return this.drag.lines;
    return layer[this.lineField] || [];
  }

  startOcclusionInteraction(point) {
    if (!this.occlusionLayerId || this.occlusionDraft) return false;
    const layer = this.layers.find(item => item.id === this.occlusionLayerId);
    if (!layer) return false;
    const lines = (layer[this.lineField] || []).map(line => line.map(node => [...node]));
    const threshold = 8 / this.displayedScale();
    const node = nearestLineNode(point, lines, threshold);
    if (node) {
      this.selectedOcclusionLine = {layerId: layer.id, index: node.lineIndex, field: this.lineField};
      this.drag = {
        type: "occlusion-node",
        layerId: layer.id,
        lineIndex: node.lineIndex,
        nodeIndex: node.nodeIndex,
        lines,
        field: this.lineField,
        eventName: this.lineEvent,
      };
      this.render();
      return true;
    }
    const index = nearestLineIndex(point, lines, threshold);
    if (index >= 0) {
      this.selectedOcclusionLine = {layerId: layer.id, index, field: this.lineField};
      this.render();
      return true;
    }
    return false;
  }

  updateOcclusionNode(point) {
    if (this.drag?.type !== "occlusion-node") return false;
    const node = this.drag.lines[this.drag.lineIndex][this.drag.nodeIndex];
    node[0] = Math.max(0, Math.min(this.image.naturalWidth, point.x));
    node[1] = Math.max(0, Math.min(this.image.naturalHeight, point.y));
    this.render();
    return true;
  }

  finishOcclusionNodeDrag() {
    if (this.drag?.type !== "occlusion-node") return false;
    const {layerId, lines, field, eventName} = this.drag;
    this.drag = null;
    const rounded = lines.map(line => line.map(point => point.map(value => Math.round(value))));
    const layer = this.layers.find(item => item.id === layerId);
    if (layer) layer[field] = rounded;
    this.dispatchEvent(new CustomEvent(eventName, {detail: {layerId, lines: rounded}}));
    this.render();
    return true;
  }

  finishOcclusionWithRightClick(event) {
    if (this.tool !== "occlusion" || !this.occlusionLayerId) return false;
    event?.preventDefault?.();
    return this.commitOcclusionLine();
  }

  activeOcclusionLayerIds() {
    if (!this.character) return [];
    const foot = this.character.position;
    return this.layers.filter(layer => layer.visible !== false && layer.mask_path
      && (layer.occlusion_lines || []).some(line => footprintIsBehindLine(
        foot, this.character.footpoint, this.characterScale, line)))
      .map(layer => layer.id);
  }

  invalidateMask(id) {
    this.maskImages.delete(id);
    this.maskOverlays.delete(id);
    this.foregroundOverlays.delete(id);
    this.resourceAlphaMasks.delete(id);
    this.maskCanvases.delete(id);
    this.maskLoadToken.set(id, (this.maskLoadToken.get(id) || 0) + 1);
    this.maskVersions.set(id, (this.maskVersions.get(id) || 0) + 1);
  }

  forgetLocalMasks() {
    this.maskGeneration += 1;
    for (const image of this.maskImages.values()) image.close?.();
    this.maskCanvases.clear();
    this.maskImages.clear();
    this.maskOverlays.clear();
    this.foregroundOverlays.clear();
    this.resourceAlphaMasks.clear();
    this.maskLoading.clear();
    this.maskLoadToken.clear();
  }

  dropLocalMask(layerId) {
    const image = this.maskImages.get(layerId);
    if (image && image !== this.maskCanvases.get(layerId)) image.close?.();
    this.maskCanvases.delete(layerId);
    this.maskImages.delete(layerId);
    this.maskOverlays.delete(layerId);
    this.foregroundOverlays.delete(layerId);
    this.resourceAlphaMasks.delete(layerId);
    this.maskLoading.delete(layerId);
    this.maskLoadToken.set(layerId, (this.maskLoadToken.get(layerId) || 0) + 1);
    this.maskVersions.set(layerId, (this.maskVersions.get(layerId) || 0) + 1);
  }

  editableMask(layerId) {
    const existing = this.maskCanvases.get(layerId);
    if (existing) return existing;
    const current = this.maskImages.get(layerId);
    const width = current?.naturalWidth || current?.width;
    const height = current?.naturalHeight || current?.height;
    if (!width || !height || !current) throw new Error("这张蒙版还没有显示出来，请等它出现后再修改");
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    context.imageSmoothingEnabled = false;
    context.drawImage(current, 0, 0);
    if (current.close) current.close();
    this.maskCanvases.set(layerId, canvas);
    this.maskImages.set(layerId, canvas);
    return canvas;
  }

  editMaskLocally(layerId, stroke) {
    const canvas = this.editableMask(layerId);
    this.maskLoadToken.set(layerId, (this.maskLoadToken.get(layerId) || 0) + 1);
    const context = canvas.getContext("2d");
    const color = stroke.value ? "#ffffff" : "#000000";
    context.save();
    context.fillStyle = color;
    context.strokeStyle = color;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.globalCompositeOperation = "source-over";
    const points = stroke.points || [];
    if (stroke.shape === "polygon" && points.length >= 3) {
      context.beginPath();
      context.moveTo(points[0][0], points[0][1]);
      for (let index = 1; index < points.length; index += 1) context.lineTo(points[index][0], points[index][1]);
      context.closePath();
      context.fill("nonzero");
    } else if (points.length) {
      const radius = Number(stroke.radius) || 10;
      context.lineWidth = radius * 2;
      context.beginPath();
      context.moveTo(points[0][0], points[0][1]);
      for (const point of points) context.lineTo(point[0], point[1]);
      context.stroke();
      if (points.length === 1) {
        context.beginPath();
        context.arc(points[0][0], points[0][1], radius, 0, Math.PI * 2);
        context.fill();
      }
    }
    context.restore();
    if (stroke.value && this.walkableLayerIds.has(layerId)) {
      context.save();
      context.globalCompositeOperation = "destination-out";
      for (const resourceId of this.resourceMaskIds) {
        const resource = this.maskImages.get(resourceId);
        if (!resource) continue;
        let alphaMask = this.resourceAlphaMasks.get(resourceId);
        if (!alphaMask) {
          alphaMask = this.createTintedMask(resource, [255, 255, 255], 1);
          if (alphaMask) this.resourceAlphaMasks.set(resourceId, alphaMask);
        }
        if (alphaMask) context.drawImage(alphaMask, 0, 0, canvas.width, canvas.height);
      }
      context.restore();
    }
    this.maskImages.set(layerId, canvas);
    this.maskOverlays.delete(layerId);
    this.render();
  }

  maskContains(image, x, y) {
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    const px = Math.floor(x);
    const py = Math.floor(y);
    if (!width || !height || px < 0 || py < 0 || px >= width || py >= height) return false;
    if (!this.hitCanvas) {
      this.hitCanvas = document.createElement("canvas");
      this.hitCanvas.width = 1;
      this.hitCanvas.height = 1;
      this.hitContext = this.hitCanvas.getContext("2d", {willReadFrequently: true});
    }
    this.hitContext.clearRect(0, 0, 1, 1);
    this.hitContext.drawImage(image, px, py, 1, 1, 0, 0, 1, 1);
    const pixel = this.hitContext.getImageData(0, 0, 1, 1).data;
    return Math.max(pixel[0], pixel[1], pixel[2]) > 16;
  }

  pickMask(x, y) {
    return topMaskId(this.layers, layer => {
      const image = this.maskImages.get(layer.id);
      return Boolean(image) && this.maskContains(image, x, y);
    });
  }

  cancelLasso() {
    this.lasso = null;
    this.render();
  }

  displayedScale() {
    const width = this.image.naturalWidth;
    const rect = this.canvas.getBoundingClientRect();
    if (!width || !rect.width) return this.view.scale || 1;
    return rect.width / width;
  }

  closeLasso(closingPoint) {
    if (!this.lasso || this.lasso.committing) return false;
    const last = this.lasso.points[this.lasso.points.length - 1];
    const scale = this.displayedScale();
    const committed = lassoCommitPoints(this.lasso.points, closingPoint || last, scale);
    if (!committed) return false;
    this.lasso.committing = true;
    this.lasso.drawing = false;
    this.dispatchEvent(new CustomEvent("stroke", {detail: lassoPayload(committed, this.lasso.tool)}));
    return true;
  }

  async setPreview(url, color = [240, 184, 91]) {
    if (!url) {
      this.previewImage = null;
      this.previewOverlay = null;
      this.render();
      return;
    }
    this.previewImage = await new Promise(resolve => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => resolve(null);
      image.src = url;
    });
    this.previewOverlay = this.previewImage ? this.createTintedMask(this.previewImage, color, .55) : null;
    this.render();
  }

  setZoom(scale, anchor = {x: this.shell.clientWidth / 2, y: this.shell.clientHeight / 2}) {
    const before = screenToImage(anchor.x, anchor.y, this.view);
    this.view.scale = Math.max(.1, Math.min(4, scale));
    this.view.offsetX = anchor.x - before.x * this.view.scale;
    this.view.offsetY = anchor.y - before.y * this.view.scale;
    this.applyView();
  }

  resize() {
    const dpr = devicePixelRatio || 1;
    const w = this.image.naturalWidth;
    const h = this.image.naturalHeight;
    if (!w || !h) return;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.context.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.stage.style.width = `${w}px`;
    this.stage.style.height = `${h}px`;
    this.image.style.width = `${w}px`;
    this.image.style.height = `${h}px`;
    this.fit();
    this.render();
  }

  fit() {
    const s = Math.min(
      (this.shell.clientWidth - 56) / this.image.naturalWidth,
      (this.shell.clientHeight - 56) / this.image.naturalHeight,
      1,
    );
    this.view.scale = Math.max(.1, s);
    this.view.offsetX = (this.shell.clientWidth - this.image.naturalWidth * this.view.scale) / 2;
    this.view.offsetY = (this.shell.clientHeight - this.image.naturalHeight * this.view.scale) / 2;
    this.applyView();
  }

  applyView() {
    this.stage.style.transformOrigin = "0 0";
    this.stage.style.transform = `translate(${this.view.offsetX}px, ${this.view.offsetY}px) scale(${this.view.scale})`;
    this.dispatchEvent(new CustomEvent("viewchange", {detail: {...this.view}}));
  }

  local(event) {
    const rect = this.canvas.getBoundingClientRect();
    const width = this.image.naturalWidth;
    const height = this.image.naturalHeight;
    if (!rect.width || !rect.height || !width || !height) return {x: 0, y: 0};
    return {
      x: (event.clientX - rect.left) / rect.width * width,
      y: (event.clientY - rect.top) / rect.height * height,
    };
  }

  bind() {
    this.shell.addEventListener("wheel", event => {
      event.preventDefault();
      const r = this.shell.getBoundingClientRect();
      this.setZoom(this.view.scale * (event.deltaY < 0 ? 1.12 : .89), {
        x: event.clientX - r.left,
        y: event.clientY - r.top,
      });
    }, {passive: false});
    window.addEventListener("keydown", event => {
      if (event.code === "Space") this.space = true;
      if (event.key === "Escape" && this.occlusionDraft) this.cancelOcclusion();
      if ((event.key === "Delete" || event.key === "Backspace") && this.deleteSelectedOcclusionLine()) {
        event.preventDefault();
      }
      if (event.key === "Enter" && this.tool === "occlusion" && this.commitOcclusionLine()) {
        event.preventDefault();
      }
    });
    window.addEventListener("keyup", event => { if (event.code === "Space") this.space = false; });
    this.canvas.addEventListener("pointerdown", event => this.pointerDown(event));
    this.canvas.addEventListener("pointermove", event => this.pointerMove(event));
    this.canvas.addEventListener("pointerup", event => this.pointerUp(event));
    this.canvas.addEventListener("contextmenu", event => this.finishOcclusionWithRightClick(event));
    this.canvas.addEventListener("dblclick", event => {
      if (this.tool === "occlusion" && this.occlusionDraft?.length >= 2) {
        event.preventDefault();
        this.commitOcclusionLine();
        return;
      }
      if (!LASSO_TOOLS.includes(this.tool) || !this.lasso || this.lasso.points.length < 3) return;
      event.preventDefault();
      this.closeLasso();
    });
  }

  appendLassoPoint(point) {
    const points = this.lasso.points;
    const last = points[points.length - 1];
    if (last && Math.hypot(point.x - last.x, point.y - last.y) < 1.5) return;
    points.push({x: point.x, y: point.y});
  }

  pointerDown(event) {
    if (this.space) {
      this.drag = {type: "pan", x: event.clientX, y: event.clientY, ox: this.view.offsetX, oy: this.view.offsetY};
      this.canvas.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== undefined && event.button !== 0) return;
    const point = this.local(event);
    if (this.characterDeleteMode && this.characterDeleteHit(point)) {
      this.dispatchEvent(new CustomEvent("character-delete"));
      return;
    }
    if (this.occlusionLayerId && !this.previewMode && !this.occlusionDraft
        && this.startOcclusionInteraction(point)) {
      if (this.drag?.type === "occlusion-node") this.canvas.setPointerCapture(event.pointerId);
      return;
    }
    if (this.tool === "select") {
      if (this.characterContains(point)) {
        this.drag = {
          type: "character",
          offsetX: point.x - this.character.position.x,
          offsetY: point.y - this.character.position.y,
        };
        this.canvas.setPointerCapture(event.pointerId);
        return;
      }
      this.dispatchEvent(new CustomEvent("pick", {
        detail: {
          id: this.pickMask(point.x, point.y),
          additive: event.shiftKey || event.ctrlKey || event.metaKey,
        },
      }));
      return;
    }
    if (this.tool === "occlusion") {
      if (!this.occlusionLayerId || this.previewMode) return;
      this.selectedOcclusionLine = null;
      if (!this.occlusionDraft) this.occlusionDraft = [];
      this.occlusionDraft.push(point);
      this.render();
      return;
    }
    if (EDIT_TOOLS.includes(this.tool) && !this.maskEditLayerId) {
      this.dispatchEvent(new CustomEvent("need-edit"));
      return;
    }
    if (this.locked) {
      this.dispatchEvent(new CustomEvent("locked"));
      return;
    }
    this.canvas.setPointerCapture(event.pointerId);
    if (this.tool === "box") {
      const point = this.local(event);
      this.drag = {type: "box", start: point, current: point};
    } else if (["positive", "negative"].includes(this.tool)) {
      const point = this.local(event);
      this.points.push({...point, label: this.tool === "positive" ? 1 : 0});
      this.dispatchEvent(new CustomEvent("points", {
        detail: {points: this.points.map(item => [item.x, item.y]), labels: this.points.map(item => item.label)},
      }));
      this.render();
    } else if (["brush", "eraser"].includes(this.tool)) {
      this.drag = {type: "stroke", points: [this.local(event)]};
      this.render();
    } else if (LASSO_TOOLS.includes(this.tool)) {
      const point = this.local(event);
      if (this.lasso?.committing) return;
      if (this.lasso && canCloseLasso(this.lasso.points, point, this.displayedScale())) {
        this.closeLasso(point);
        return;
      }
      if (!this.lasso) this.lasso = {tool: this.tool, points: [], drawing: false, cursor: point, committing: false};
      this.lasso.tool = this.tool;
      this.lasso.drawing = true;
      this.lasso.cursor = point;
      this.appendLassoPoint(point);
      this.render();
    }
  }

  pointerMove(event) {
    if (this.lasso && LASSO_TOOLS.includes(this.tool)) {
      this.lasso.cursor = this.local(event);
      if (this.lasso.drawing && !this.lasso.committing) this.appendLassoPoint(this.lasso.cursor);
      this.render();
    }
    if (!this.drag) return;
    if (this.drag.type === "pan") {
      this.view.offsetX = this.drag.ox + event.clientX - this.drag.x;
      this.view.offsetY = this.drag.oy + event.clientY - this.drag.y;
      this.applyView();
    } else if (this.drag.type === "box") {
      this.drag.current = this.local(event);
    } else if (this.drag.type === "stroke") {
      this.drag.points.push(this.local(event));
    } else if (this.drag.type === "character") {
      const point = this.local(event);
      const candidate = {
        x: Math.max(0, Math.min(this.image.naturalWidth, point.x - this.drag.offsetX)),
        y: Math.max(0, Math.min(this.image.naturalHeight, point.y - this.drag.offsetY)),
      };
      if (this.characterCanStand(candidate)) this.character.position = candidate;
    } else if (this.drag.type === "occlusion-node") {
      this.updateOcclusionNode(this.local(event));
      return;
    }
    this.render();
  }

  pointerUp(event) {
    if (this.lasso?.drawing) {
      this.lasso.drawing = false;
      const point = event ? this.local(event) : this.lasso.cursor;
      if (point && canCloseLasso(this.lasso.points, point, this.displayedScale())) this.closeLasso(point);
      else this.render();
      return;
    }
    if (!this.drag) return;
    if (this.drag.type === "occlusion-node") {
      this.finishOcclusionNodeDrag();
      return;
    }
    if (this.drag.type === "box") {
      const a = this.drag.start;
      const b = this.drag.current;
      const box = [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)];
      const rounded = box.map(value => Math.round(value));
      const [x1, y1, x2, y2] = rounded;
      if (x2 > x1 && y2 > y1) {
        const name = this.maskEditLayerId ? "box-add" : "box";
        this.dispatchEvent(new CustomEvent(name, {detail: rounded}));
      }
    } else if (this.drag.type === "stroke") {
      this.dispatchEvent(new CustomEvent("stroke", {
        detail: {
          points: this.drag.points.map(point => [point.x, point.y]),
          radius: this.brushRadius,
          value: this.tool === "brush" ? 255 : 0,
        },
      }));
    }
    this.drag = null;
    this.render();
  }

  characterCanStand(position) {
    if (!this.character) return true;
    if (!this.walkableConfigured) return true;
    const fallbackMasks = [...this.walkableLayerIds].map(id => this.maskImages.get(id)).filter(Boolean);
    const masks = this.finalWalkableMask ? [this.finalWalkableMask] : fallbackMasks;
    if (!masks.length) return false;
    const contains = (x, y) => masks.some(mask => this.maskContains(mask, x, y));
    const footprint = candidate => footprintIsWalkable(
      contains, candidate, this.character.footpoint, this.characterScale,
    );
    if (footprint(position)) return true;
    // A restored/imported character may initially sit outside the configured road.
    // Let it escape until it first reaches valid ground; normal restrictions then resume.
    return !footprint(this.character.position);
  }

  characterBounds() {
    if (!this.character) return null;
    const image = this.character.image;
    const scale = this.characterScale;
    return {
      x: this.character.position.x - this.character.footpoint.x * scale,
      y: this.character.position.y - this.character.footpoint.y * scale,
      width: (image.naturalWidth || image.width) * scale,
      height: (image.naturalHeight || image.height) * scale,
    };
  }

  characterDeleteControl() {
    const bounds = this.characterBounds();
    if (!bounds || !this.characterDeleteMode) return null;
    return {x: bounds.x + bounds.width, y: bounds.y};
  }

  characterDeleteHit(point) {
    const control = this.characterDeleteControl();
    if (!control || !point) return false;
    const radius = 13 / Math.max(this.displayedScale(), .1);
    return Math.hypot(point.x - control.x, point.y - control.y) <= radius;
  }

  characterContains(point) {
    const bounds = this.characterBounds();
    return Boolean(bounds && point.x >= bounds.x && point.x <= bounds.x + bounds.width
      && point.y >= bounds.y && point.y <= bounds.y + bounds.height);
  }

  async loadMasks() {
    const generation = this.maskGeneration;
    const mapId = this.loadedMapId;
    const visible = this.layers.filter(layer => layer.mask_path && layer.map_id === mapId);
    await Promise.all(visible.map(layer => this.loadOneMask(layer)));
    if (generation !== this.maskGeneration || mapId !== this.loadedMapId) return;
    this.maskOverlays.clear();
    this.render();
  }

  loadOneMask(layer) {
    if (this.maskCanvases.has(layer.id)) {
      this.maskImages.set(layer.id, this.maskCanvases.get(layer.id));
      return Promise.resolve();
    }
    if (this.maskImages.has(layer.id)) return Promise.resolve();
    const pending = this.maskLoading.get(layer.id);
    if (pending) return pending;
    const version = this.maskVersions.get(layer.id) || 0;
    const generation = this.maskGeneration;
    const token = this.maskLoadToken.get(layer.id) || 0;
    const promise = this.scheduleMask(() => new Promise(resolve => {
      const img = new Image();
      img.onload = async () => {
        let bitmap = img;
        try { bitmap = await createImageBitmap(img); } catch (error) { bitmap = img; }
        const currentToken = this.maskLoadToken.get(layer.id) || 0;
        const stale = generation !== this.maskGeneration || currentToken !== token
          || layer.map_id !== this.loadedMapId || this.maskCanvases.has(layer.id);
        if (stale) {
          bitmap.close?.();
          resolve();
          return;
        }
        this.maskImages.set(layer.id, bitmap);
        this.maskOverlays.delete(layer.id);
        resolve();
      };
      img.onerror = resolve;
      const maskUrl = layer.mask_url || `/api/maps/${layer.map_id}/layers/${layer.id}/mask`;
      img.src = `${maskUrl}?v=${version}-${generation}-${token}`;
    })).finally(() => {
      if (this.maskLoading.get(layer.id) === promise) this.maskLoading.delete(layer.id);
    });
    this.maskLoading.set(layer.id, promise);
    return promise;
  }

  scheduleMask(work) {
    if (!this.maskSlots) {
      this.maskSlots = [Promise.resolve(), Promise.resolve(), Promise.resolve()];
      this.maskSlotIndex = 0;
    }
    const index = this.maskSlotIndex++ % this.maskSlots.length;
    const slot = this.maskSlots[index].then(work, work);
    this.maskSlots[index] = slot.then(() => {}, () => {});
    return slot;
  }

  createTintedMask(image, color, opacity) {
    const w = image.naturalWidth || image.width;
    const h = image.naturalHeight || image.height;
    if (!w || !h) return null;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(image, 0, 0);
    const data = context.getImageData(0, 0, w, h);
    maskPixelsToTintedRgba(data.data, color, opacity);
    context.putImageData(data, 0, 0);
    return canvas;
  }

  createForegroundOverlay(mask) {
    const w = this.image.naturalWidth;
    const h = this.image.naturalHeight;
    if (!w || !h) return null;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const context = canvas.getContext("2d");
    context.drawImage(this.image, 0, 0, w, h);
    context.globalCompositeOperation = "destination-in";
    const alphaMask = this.createTintedMask(mask, [255, 255, 255], 1);
    if (alphaMask) context.drawImage(alphaMask, 0, 0, w, h);
    context.globalCompositeOperation = "source-over";
    return canvas;
  }

  render() {
    if (!this.image.naturalWidth) return;
    const c = this.context;
    const w = this.image.naturalWidth;
    const h = this.image.naturalHeight;
    c.clearRect(0, 0, w, h);
    if (!this.previewMode && this.previewOverlay) c.drawImage(this.previewOverlay, 0, 0);
    if (this.character) {
      const bounds = this.characterBounds();
      c.drawImage(this.character.image, bounds.x, bounds.y, bounds.width, bounds.height);
      for (const id of this.activeOcclusionLayerIds()) {
        const mask = this.maskImages.get(id);
        if (!mask) continue;
        let foreground = this.foregroundOverlays.get(id);
        if (!foreground) {
          foreground = this.createForegroundOverlay(mask);
          if (foreground) this.foregroundOverlays.set(id, foreground);
        }
        if (foreground) c.drawImage(foreground, 0, 0);
      }
      if (this.characterDeleteMode && !this.previewMode) {
        c.save();
        c.strokeStyle = "#fff176";
        c.lineWidth = 2 / this.view.scale;
        c.setLineDash([6 / this.view.scale, 4 / this.view.scale]);
        c.strokeRect(bounds.x, bounds.y, bounds.width, bounds.height);
        const control = this.characterDeleteControl();
        const radius = 11 / this.view.scale;
        c.setLineDash([]);
        c.beginPath();
        c.arc(control.x, control.y, radius, 0, Math.PI * 2);
        c.fillStyle = "#d94b5b";
        c.fill();
        c.strokeStyle = "#fff";
        c.lineWidth = 1.5 / this.view.scale;
        c.stroke();
        c.beginPath();
        const arm = 4 / this.view.scale;
        c.moveTo(control.x - arm, control.y - arm);
        c.lineTo(control.x + arm, control.y + arm);
        c.moveTo(control.x + arm, control.y - arm);
        c.lineTo(control.x - arm, control.y + arm);
        c.stroke();
        c.restore();
      }
    }
    if (!this.previewMode) for (const layer of this.layers) {
      const mask = this.maskImages.get(layer.id);
      if (mask && layer.visible) {
        let overlay = this.maskOverlays.get(layer.id);
        if (!overlay) {
          const walkable = layer.kind === "walkable";
          overlay = this.createTintedMask(mask, walkable ? [168, 85, 247] : [63, 210, 230], walkable ? .36 : .42);
          if (overlay) this.maskOverlays.set(layer.id, overlay);
        }
        if (overlay) c.drawImage(overlay, 0, 0);
      }
    }
    if (!this.previewMode) this.drawOcclusionLines(c);
    c.lineWidth = 2 / this.view.scale;
    const editingWalkable = this.walkableLayerIds.has(this.maskEditLayerId);
    c.strokeStyle = editingWalkable ? "#a855f7" : "#63d5e6";
    c.fillStyle = editingWalkable ? "#a855f722" : "#63d5e622";
    if (this.drag?.type === "box") {
      const a = this.drag.start;
      const b = this.drag.current;
      c.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
      c.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
    }
    for (const point of this.points) {
      c.beginPath();
      c.arc(point.x, point.y, 7 / this.view.scale, 0, Math.PI * 2);
      c.fillStyle = point.label ? "#43dc8b" : "#ff6577";
      c.fill();
      c.fillStyle = "#fff";
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.font = `${10 / this.view.scale}px sans-serif`;
      c.fillText(point.label ? "+" : "−", point.x, point.y);
    }
    if (this.drag?.type === "stroke") {
      const pts = this.drag.points;
      c.beginPath();
      c.moveTo(pts[0].x, pts[0].y);
      for (const point of pts) c.lineTo(point.x, point.y);
      c.lineWidth = this.brushRadius * 2;
      c.lineCap = "round";
      c.lineJoin = "round";
      const walkable = this.walkableLayerIds.has(this.maskEditLayerId);
      c.strokeStyle = this.tool === "brush" ? (walkable ? "#a855f799" : "#63d5e699") : "#ff7a8a99";
      c.stroke();
    } else if (this.lasso?.points.length) {
      this.drawOpenLasso(c);
    }
  }

  drawOcclusionLines(c) {
    for (const layer of this.layers) {
      if (this.hiddenOcclusionInfo.has(layer.id)) continue;
      for (const [field, color, nodeColor] of [
        ["occlusion_lines", "#ff9f43", "#ffd166"],
        ["walkable_boundary_lines", "#b56cff", "#e4c1ff"],
      ]) {
        const dragged = this.drag?.type === "occlusion-node" && this.drag.layerId === layer.id
          && this.drag.field === field ? this.drag.lines : null;
        const lines = dragged || layer[field] || [];
        for (let index = 0; index < lines.length; index += 1) {
          const selected = this.selectedOcclusionLine?.layerId === layer.id
            && this.selectedOcclusionLine?.field === field
            && this.selectedOcclusionLine?.index === index;
          this.drawOcclusionLine(c, lines[index], selected, color, nodeColor);
        }
      }
    }
    if (this.occlusionDraft?.length) {
      const boundary = this.lineField === "walkable_boundary_lines";
      this.drawOcclusionLine(c, this.occlusionDraft.map(point => [point.x, point.y]), false,
        boundary ? "#b56cff" : "#ff9f43", boundary ? "#e4c1ff" : "#ffd166");
    }
  }

  drawOcclusionLine(c, region, selected, color = "#ff9f43", nodeColor = "#ffd166") {
    if (!region.length) return;
    c.beginPath();
    c.moveTo(region[0][0], region[0][1]);
    for (let index = 1; index < region.length; index += 1) c.lineTo(region[index][0], region[index][1]);
    c.lineWidth = (selected ? 4 : 2) / this.view.scale;
    c.strokeStyle = selected ? "#fff176" : color;
    c.stroke();
    for (const point of region) {
      c.beginPath();
      c.arc(point[0], point[1], 4 / this.view.scale, 0, Math.PI * 2);
      c.fillStyle = nodeColor;
      c.fill();
    }
  }

  drawOpenLasso(c) {
    const pts = this.lasso.points;
    const adding = this.lasso.tool === "lasso-add";
    const walkable = this.walkableLayerIds.has(this.maskEditLayerId);
    const color = adding ? (walkable ? "#a855f7" : "#63d5e6") : "#ff7a8a";
    const scale = this.displayedScale();
    const near = Boolean(this.lasso.cursor && canCloseLasso(pts, this.lasso.cursor, scale));
    c.beginPath();
    c.moveTo(pts[0].x, pts[0].y);
    for (let index = 1; index < pts.length; index += 1) c.lineTo(pts[index].x, pts[index].y);
    if (!near && this.lasso.cursor) c.lineTo(this.lasso.cursor.x, this.lasso.cursor.y);
    if (near) c.closePath();
    c.lineWidth = 2 / this.view.scale;
    c.strokeStyle = color;
    if (near) {
      c.fillStyle = adding ? (walkable ? "#a855f755" : "#63d5e655") : "#ff7a8a55";
      c.fill();
    }
    c.stroke();
    const start = pts[0];
    c.beginPath();
    c.arc(start.x, start.y, (near ? 9 : 5) / this.view.scale, 0, Math.PI * 2);
    c.fillStyle = near ? color : "#ffffff";
    c.fill();
    if (near) {
      c.fillStyle = "#fff";
      c.font = `${14 / this.view.scale}px "Microsoft YaHei UI", sans-serif`;
      c.textAlign = "left";
      c.textBaseline = "bottom";
      c.fillText(adding ? "点击增加这块" : "点击减去这块", start.x + 12 / this.view.scale, start.y);
    }
  }
}
