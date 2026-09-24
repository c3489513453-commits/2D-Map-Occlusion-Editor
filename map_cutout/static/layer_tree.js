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
    this.hiddenOcclusion = new Set();
    this.bind();
  }

  bind() {
    this.container.addEventListener("click", event => this.click(event));
    this.container.addEventListener("dblclick", event => this.rename(event));
    this.container.addEventListener("dragstart", event => {
      const row = event.target.closest("[data-layer-id]");
      if (!row || row.classList.contains("original")) return;
      this.draggingId = row.dataset.layerId;
      event.dataTransfer.setData("text/plain", this.draggingId);
      event.dataTransfer.effectAllowed = "move";
    });
    this.container.addEventListener("dragover", event => {
      const row = event.target.closest("[data-layer-id], .folder-row");
      this.container.querySelectorAll(".drop-target").forEach(node => node.classList.remove("drop-target"));
      if (!row || row.dataset.layerId === this.draggingId) return;
      event.preventDefault();
      row.classList.add("drop-target");
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    });
    this.container.addEventListener("dragleave", event => event.target.closest?.("[data-layer-id], .folder-row")?.classList.remove("drop-target"));
    this.container.addEventListener("dragend", () => {
      this.draggingId = null;
      this.container.querySelectorAll(".drop-target").forEach(node => node.classList.remove("drop-target"));
    });
    this.container.addEventListener("drop", event => {
      event.preventDefault();
      this.container.querySelectorAll(".drop-target").forEach(node => node.classList.remove("drop-target"));
      const id = (event.dataTransfer && event.dataTransfer.getData("text/plain")) || this.draggingId;
      this.draggingId = null;
      if (!id) return;
      const layerRow = event.target.closest("[data-layer-id]");
      const folderRow = event.target.closest(".folder-row");
      if (layerRow && layerRow.dataset.layerId !== id) {
        const target = this.layers.find(layer => layer.id === layerRow.dataset.layerId);
        this.callbacks.onMove?.(id, {layerId: layerRow.dataset.layerId, folderId: target?.folder_id || null});
        return;
      }
      if (folderRow) {
        this.collapsed.delete(folderRow.dataset.folderId);
        this.callbacks.onMove?.(id, {folderId: folderRow.dataset.folderId});
      }
    });
  }

  row(layer, {child = false, selected = false, editing = false, hidden = false} = {}) {
    const classes = ["layer-row"];
    if (child) classes.push("folder-child");
    if (selected) classes.push("selected");
    if (editing) classes.push("editing");
    if (layer.kind === "original") classes.push("original");
    const occlusionEditing = this.occlusionEditingId === layer.id;
    const boundaryEditing = this.boundaryEditingId === layer.id;
    const maskEditing = this.editingId === layer.id;
    const editButtons = layer.mask_path
      ? layer.kind === "walkable"
        ? `<button type="button" class="toggle edit ${maskEditing ? "active" : ""}" data-action="edit" aria-label="编辑行走区域">${maskEditing ? "退出编辑" : "编辑"}</button><button type="button" class="toggle delete" data-action="delete" aria-label="删除图层">删除</button>`
        : `<button type="button" class="toggle edit" data-action="edit" aria-label="编辑蒙版">编辑</button><button type="button" class="toggle draw-occlusion ${occlusionEditing ? "active" : ""}" data-action="draw-occlusion" aria-label="${occlusionEditing ? "退出底线编辑" : "编辑底线"}">${occlusionEditing ? "退出编辑" : "编辑底线"}</button><button type="button" class="toggle draw-walkable-boundary ${boundaryEditing ? "active" : ""}" data-action="draw-walkable-boundary" aria-label="${boundaryEditing ? "退出可走边界编辑" : "编辑可走"}">${boundaryEditing ? "退出编辑" : "编辑可走"}</button>${layer.occlusion_lines?.length ? '<button type="button" class="toggle clear-occlusion" data-action="clear-occlusion" aria-label="清除底线">×</button>' : ''}<button type="button" class="toggle delete" data-action="delete" aria-label="删除图层">删除</button>`
      : "";
    const occlusionToggle = layer.mask_path && layer.kind !== "walkable"
      ? `<button type="button" class="toggle occlusion-info ${this.hiddenOcclusion.has(layer.id) ? "" : "on"}" data-action="occlusion-info" aria-label="显示或隐藏遮挡信息">${this.hiddenOcclusion.has(layer.id) ? "○" : "●"}</button>`
      : "";
    return `<div class="${classes.join(" ")}" data-layer-id="${layer.id}" draggable="${layer.kind !== "original"}"${hidden ? " hidden" : ""}><button type="button" class="toggle visibility ${layer.visible ? "on" : ""}" data-action="visibility" aria-label="显示或隐藏">${layer.visible ? "◉" : "○"}</button><span class="layer-name name">${escapeHtml(layer.name)}</span>${editButtons}${occlusionToggle}</div>`;
  }

  render(layers, folders, selected = this.selected, editingId = this.editingId, occlusionEditingId = this.occlusionEditingId, boundaryEditingId = this.boundaryEditingId) {
    this.layers = layers;
    this.folders = folders;
    this.selected = selected;
    this.editingId = editingId;
    this.occlusionEditingId = occlusionEditingId;
    this.boundaryEditingId = boundaryEditingId;
    const original = layers.find(layer => layer.kind === "original");
    const grouped = new Set();
    let html = "";
    for (const folder of folders) {
      const children = layers.filter(layer => layer.folder_id === folder.id && layer.kind !== "original");
      children.forEach(layer => grouped.add(layer.id));
      const collapsed = this.collapsed.has(folder.id);
      const hidden = this.hiddenFolders.has(folder.id);
      html += `<div class="folder-row" data-folder-id="${folder.id}"><button type="button" class="folder-caret" data-action="collapse">${collapsed ? "▸" : "▾"}</button><button type="button" class="toggle visibility ${hidden ? "" : "on"}" data-action="folder-visibility">${hidden ? "○" : "◉"}</button><span class="folder-name">${escapeHtml(folder.name)}</span><span class="count">${children.length}</span><button type="button" class="toggle delete" data-action="delete-folder" aria-label="删除文件夹">删除</button></div>`;
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

  rename(event) {
    const nameNode = event.target.closest(".layer-name");
    if (!nameNode || nameNode.querySelector("input")) return;
    const row = nameNode.closest("[data-layer-id]");
    const layer = this.layers.find(item => item.id === row?.dataset.layerId);
    if (!layer) return;
    event.preventDefault();
    event.stopPropagation();
    const input = document.createElement("input");
    input.className = "layer-rename";
    input.value = layer.name;
    input.setAttribute("aria-label", "图层名称");
    nameNode.replaceChildren(input);
    input.focus();
    input.select();
    let closed = false;
    const close = async commit => {
      if (closed) return;
      closed = true;
      const value = input.value.trim();
      input.remove();
      nameNode.textContent = layer.name;
      if (!commit || !value || value === layer.name) return;
      await this.callbacks.onRename?.(layer.id, value);
    };
    input.addEventListener("blur", () => close(true));
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        input.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        close(false);
      }
    });
  }

  click(event) {
    const folder = event.target.closest("[data-folder-id]");
    if (folder && !event.target.closest("[data-layer-id]")) {
      const id = folder.dataset.folderId;
      if (event.target.dataset.action === "delete-folder") {
        this.callbacks.onDeleteFolder?.(id);
        return;
      } else if (event.target.dataset.action === "collapse") {
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
    else if (action === "draw-occlusion") this.callbacks.onDrawOcclusion?.(id);
    else if (action === "draw-walkable-boundary") this.callbacks.onDrawWalkableBoundary?.(id);
    else if (action === "clear-occlusion") this.callbacks.onClearOcclusion?.(id);
    else if (action === "occlusion-info") {
      this.hiddenOcclusion.has(id) ? this.hiddenOcclusion.delete(id) : this.hiddenOcclusion.add(id);
      this.callbacks.onToggleOcclusionInfo?.(id, this.hiddenOcclusion.has(id));
      this.render(this.layers, this.folders);
    }
    else if (action === "visibility") this.callbacks.onPatch?.(id, {visible: !layer.visible});
    else this.callbacks.onSelect?.(id, event.shiftKey || event.ctrlKey || event.metaKey);
  }
}
