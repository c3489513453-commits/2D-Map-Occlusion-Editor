function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}

export class LayerTree {
  constructor(container, callbacks = {}) {
    this.container = container;
    this.callbacks = callbacks;
    this.collapsed = new Set();
    this.hiddenFolders = new Set();
    this.selected = new Set();
    this.editingId = null;
    this.bind();
  }

  bind() {
    this.container.addEventListener("click", event => this.click(event));
    this.container.addEventListener("dragstart", event => {
      const row = event.target.closest("[data-layer-id]");
      if (row) event.dataTransfer.setData("text/plain", row.dataset.layerId);
    });
    this.container.addEventListener("dragover", event => {
      const row = event.target.closest("[data-layer-id]");
      if (row) {
        event.preventDefault();
        row.classList.add("drop-target");
      }
    });
    this.container.addEventListener("dragleave", event => event.target.closest("[data-layer-id]")?.classList.remove("drop-target"));
    this.container.addEventListener("drop", event => {
      event.preventDefault();
      const target = event.target.closest("[data-layer-id]");
      if (!target) return;
      target.classList.remove("drop-target");
      this.callbacks.onMove?.(event.dataTransfer.getData("text/plain"), target.dataset.layerId);
    });
  }

  row(layer, {child = false, selected = false, editing = false, hidden = false} = {}) {
    const classes = ["layer-row"];
    if (child) classes.push("folder-child");
    if (selected) classes.push("selected");
    if (editing) classes.push("editing");
    if (layer.kind === "original") classes.push("original");
    const editButtons = layer.mask_path
      ? `<button type="button" class="toggle edit" data-action="edit" aria-label="继续编辑">继续编辑</button><button type="button" class="toggle delete" data-action="delete" aria-label="删除图层">删除</button>`
      : "";
    return `<div class="${classes.join(" ")}" data-layer-id="${layer.id}" draggable="${layer.kind !== "original"}"${hidden ? " hidden" : ""}><button type="button" class="toggle visibility ${layer.visible ? "on" : ""}" data-action="visibility" aria-label="显示或隐藏">${layer.visible ? "◉" : "○"}</button><span class="layer-name name">${escapeHtml(layer.name)}</span><span class="layer-kind">${layer.kind === "original" ? "底图" : "蒙版"}</span>${editButtons}<button type="button" class="toggle lock ${layer.locked ? "on" : ""}" data-action="lock" aria-label="锁定或解锁">${layer.locked ? "▣" : "□"}</button></div>`;
  }

  render(layers, folders, selected = this.selected, editingId = this.editingId) {
    this.layers = layers;
    this.folders = folders;
    this.selected = selected;
    this.editingId = editingId;
    const original = layers.find(layer => layer.kind === "original");
    const grouped = new Set();
    let html = "";
    for (const folder of folders) {
      const children = layers.filter(layer => layer.folder_id === folder.id && layer.kind !== "original");
      children.forEach(layer => grouped.add(layer.id));
      const collapsed = this.collapsed.has(folder.id);
      const hidden = this.hiddenFolders.has(folder.id);
      html += `<div class="folder-row" data-folder-id="${folder.id}"><button type="button" class="folder-caret" data-action="collapse">${collapsed ? "▸" : "▾"}</button><button type="button" class="toggle visibility ${hidden ? "" : "on"}" data-action="folder-visibility">${hidden ? "○" : "◉"}</button><span class="folder-name">${escapeHtml(folder.name)}</span><span class="count">${children.length}</span></div>`;
      for (const layer of children) {
        html += this.row(layer, {
          child: true,
          selected: selected.has(layer.id),
          editing: editingId === layer.id,
          hidden: collapsed || hidden,
        });
      }
    }
    for (const layer of layers.filter(item => item.kind !== "original" && !grouped.has(item.id))) {
      html += this.row(layer, {selected: selected.has(layer.id), editing: editingId === layer.id});
    }
    if (original) html += this.row(original, {selected: selected.has(original.id)});
    this.container.innerHTML = html;
  }

  click(event) {
    const folder = event.target.closest("[data-folder-id]");
    if (folder && !event.target.closest("[data-layer-id]")) {
      const id = folder.dataset.folderId;
      if (event.target.dataset.action === "collapse") {
        this.collapsed.has(id) ? this.collapsed.delete(id) : this.collapsed.add(id);
      } else if (event.target.dataset.action === "folder-visibility") {
        this.hiddenFolders.has(id) ? this.hiddenFolders.delete(id) : this.hiddenFolders.add(id);
      }
      this.render(this.layers, this.folders);
      return;
    }
    const row = event.target.closest("[data-layer-id]");
    if (!row) return;
    const id = row.dataset.layerId;
    const layer = this.layers.find(item => item.id === id);
    const action = event.target.dataset.action;
    if (action === "delete") this.callbacks.onDelete?.(id);
    else if (action === "edit") this.callbacks.onEdit?.(id);
    else if (action) this.callbacks.onPatch?.(id, {[action === "visibility" ? "visible" : "locked"]: !layer[action === "visibility" ? "visible" : "locked"]});
    else this.callbacks.onSelect?.(id, event.shiftKey || event.ctrlKey || event.metaKey);
  }
}
