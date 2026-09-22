export class ApiClient {
  async request(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(detail.detail || "请求失败");
    }
    return response.json();
  }

  get(path) { return this.request(path); }
  post(path, data = {}) { return this.request(path, { method: "POST", body: JSON.stringify(data) }); }
  patch(path, data) { return this.request(path, { method: "PATCH", body: JSON.stringify(data) }); }
  delete(path) { return this.request(path, { method: "DELETE" }); }
}

export class AppState extends EventTarget {
  constructor(api = new ApiClient()) {
    super();
    this.api = api;
    this.maps = [];
    this.currentMapId = null;
    this.layers = [];
    this.folders = [];
    this.selectedLayerIds = new Set();
    this.dirty = false;
    this.busy = false;
    this.status = "准备就绪";
  }

  emit() { this.dispatchEvent(new CustomEvent("change")); }
  setDirty(value) { this.dirty = Boolean(value); this.emit(); }
  setStatus(message, busy = false) { this.status = message; this.busy = busy; this.emit(); }

  orderedLayers() {
    return [...this.layers].sort((a, b) => {
      if (a.kind === "original") return 1;
      if (b.kind === "original") return -1;
      return this.layers.indexOf(b) - this.layers.indexOf(a);
    });
  }

  async loadMaps() {
    this.maps = await this.api.get("/api/maps");
    if (!this.currentMapId && this.maps.length) this.currentMapId = this.maps[0].id;
    await this.loadLayers();
  }

  async loadLayers() {
    if (!this.currentMapId) { this.layers = []; this.emit(); return; }
    this.layers = await this.api.get(`/api/maps/${this.currentMapId}/layers`);
    const current = this.maps.find(item => item.id === this.currentMapId);
    this.folders = current?.folders || [];
    this.emit();
  }

  async selectMap(mapId) {
    this.currentMapId = mapId;
    this.selectedLayerIds.clear();
    await this.loadLayers();
  }

  toggleLayerSelection(layerId, additive = false) {
    if (!additive) this.selectedLayerIds.clear();
    if (additive && this.selectedLayerIds.has(layerId)) this.selectedLayerIds.delete(layerId);
    else this.selectedLayerIds.add(layerId);
    this.emit();
  }

  async save() {
    await this.api.post("/api/projects/save");
    this.dirty = false;
    this.status = "项目已保存";
    this.emit();
  }

  beforeUnload(event) {
    if (!this.dirty) return undefined;
    event.preventDefault();
    event.returnValue = "项目有未保存的修改";
    return event.returnValue;
  }
}

