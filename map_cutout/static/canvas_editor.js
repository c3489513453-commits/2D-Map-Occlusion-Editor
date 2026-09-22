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

export function lassoCommitPoints(points, closingPoint, scale, threshold = 14) {
  if (!canCloseLasso(points, closingPoint, scale, threshold)) return null;
  return points.map(point => [point.x, point.y]);
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
    this.maskEditLayerId = null;
    image.addEventListener("load", () => this.resize());
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
    this.loadMasks();
  }

  setLocked(locked) { this.locked = locked; }

  setMaskEdit(layerId) { this.maskEditLayerId = layerId || null; }

  invalidateMask(id) {
    this.maskImages.delete(id);
    this.maskOverlays.delete(id);
    this.maskVersions.set(id, (this.maskVersions.get(id) || 0) + 1);
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

  async setPreview(url) {
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
    this.previewOverlay = this.previewImage ? this.createTintedMask(this.previewImage, [240, 184, 91], .55) : null;
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
    window.addEventListener("keydown", event => { if (event.code === "Space") this.space = true; });
    window.addEventListener("keyup", event => { if (event.code === "Space") this.space = false; });
    this.canvas.addEventListener("pointerdown", event => this.pointerDown(event));
    this.canvas.addEventListener("pointermove", event => this.pointerMove(event));
    this.canvas.addEventListener("pointerup", event => this.pointerUp(event));
    this.canvas.addEventListener("dblclick", event => {
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
    if (this.drag.type === "box") {
      const a = this.drag.start;
      const b = this.drag.current;
      this.dispatchEvent(new CustomEvent("box", {
        detail: [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)].map(Math.round),
      }));
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

  async loadMasks() {
    const visible = this.layers.filter(layer => layer.visible && layer.mask_path);
    await Promise.all(visible.map(layer => new Promise(resolve => {
      if (this.maskImages.has(layer.id)) return resolve();
      const img = new Image();
      img.onload = () => { this.maskImages.set(layer.id, img); resolve(); };
      img.onerror = resolve;
      const version = this.maskVersions.get(layer.id) || 0;
      img.src = `/api/maps/${layer.map_id}/layers/${layer.id}/mask?v=${version}`;
    })));
    this.render();
  }

  createTintedMask(image, color, opacity) {
    const w = this.image.naturalWidth;
    const h = this.image.naturalHeight;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(image, 0, 0, w, h);
    const data = context.getImageData(0, 0, w, h);
    maskPixelsToTintedRgba(data.data, color, opacity);
    context.putImageData(data, 0, 0);
    return canvas;
  }

  render() {
    if (!this.image.naturalWidth) return;
    const c = this.context;
    const w = this.image.naturalWidth;
    const h = this.image.naturalHeight;
    c.clearRect(0, 0, w, h);
    for (const layer of this.layers) {
      const mask = this.maskImages.get(layer.id);
      if (mask && layer.visible) {
        let overlay = this.maskOverlays.get(layer.id);
        if (!overlay) {
          overlay = this.createTintedMask(mask, [63, 210, 230], .42);
          this.maskOverlays.set(layer.id, overlay);
        }
        c.drawImage(overlay, 0, 0, w, h);
      }
    }
    if (this.previewOverlay) c.drawImage(this.previewOverlay, 0, 0, w, h);
    c.lineWidth = 2 / this.view.scale;
    c.strokeStyle = "#63d5e6";
    c.fillStyle = "#63d5e622";
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
      c.strokeStyle = this.tool === "brush" ? "#63d5e699" : "#ff7a8a99";
      c.stroke();
    } else if (this.lasso?.points.length) {
      this.drawOpenLasso(c);
    }
  }

  drawOpenLasso(c) {
    const pts = this.lasso.points;
    const adding = this.lasso.tool === "lasso-add";
    const color = adding ? "#63d5e6" : "#ff7a8a";
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
      c.fillStyle = adding ? "#63d5e655" : "#ff7a8a55";
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
