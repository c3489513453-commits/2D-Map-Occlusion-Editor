import { AppState, ApiClient } from "/static/state.js?v=character-delete4";
import { CanvasEditor } from "/static/canvas_editor.js?v=character-delete4";
import { LayerTree } from "/static/layer_tree.js?v=character-delete4";
import { InferenceControls } from "/static/inference_controls.js?v=character-delete4";
import { ExportDialog } from "/static/export_dialog.js";
import { opaqueFootpoint } from "/static/occlusion_preview.js";

const state = new AppState(new ApiClient());
const $ = selector => document.querySelector(selector);
let toastTimer;
const editor = new CanvasEditor($("#canvas-shell"), $("#canvas-stage"), $("#map-image"), $("#mask-canvas"));
state.editingLayerId = null;
let occlusionEditingLayerId = null;
let previewMode = false;
let toolBeforePreview = "select";
let layerPanelMode = "resources";
function activePanelLayers(){return layerPanelMode === "walkable" ? state.walkableLayers : state.layers;}
function activePanelFolders(){return layerPanelMode === "walkable" ? state.walkableFolders : state.folders;}
function layerBase(){return `/api/maps/${state.currentMapId}/${layerPanelMode === "walkable" ? "walkable/layers" : "layers"}`;}
const layerTree = new LayerTree($("#layer-tree"), {
  onSelect: (id, additive) => state.toggleLayerSelection(id, additive),
  onEdit: id => beginMaskEdit(id),
  onDrawOcclusion: id => beginOcclusionDrawing(id),
  onToggleOcclusionInfo: () => editor.setOcclusionInfoHidden(layerTree.hiddenOcclusion),
  onClearOcclusion: id => saveOcclusionLines(id, []),
  onPatch: (id, changes) => action(async () => { await state.api.patch(`${layerBase()}/${id}`, changes); state.setDirty(true); await state.loadLayers(); }),
  onMove: (id, target) => action(async () => {
    if (!target || id === target.layerId) return;
    const payload = {};
    if (target.layerId) {
      const index = activePanelLayers().findIndex(layer => layer.id === target.layerId);
      if (index >= 0) payload.index = index;
    }
    if ("folderId" in target) payload.folder_id = target.folderId;
    await state.api.patch(`${layerBase()}/${id}`, payload);
    state.setDirty(true);
    await state.loadLayers();
    const layer = activePanelLayers().find(item => item.id === id);
    const folder = activePanelFolders().find(item => item.id === layer?.folder_id);
    state.setStatus(folder ? `已把「${layer.name}」放进「${folder.name}」` : `已调整「${layer?.name || "图层"}」的位置`);
  }),
  onRename: (id, name) => action(async () => {
    await state.api.patch(`${layerBase()}/${id}`, {name});
    state.setDirty(true);
    await state.loadLayers();
    state.setStatus(`已把图层改名为「${name}」`);
  }),
  onDeleteFolder: id => action(async () => {
    const prefix = layerPanelMode === "walkable" ? "walkable/folders" : "folders";
    await state.api.delete(`/api/maps/${state.currentMapId}/${prefix}/${id}`);
    state.setDirty(true);
    await state.loadLayers();
    state.setStatus("文件夹已删除，里面的图层还在");
  }),
  onDelete: id => action(async () => {
    const layer = activePanelLayers().find(item => item.id === id);
    if (!layer || layer.kind === "original") return;
    await state.api.delete(`${layerBase()}/${id}`);
    state.selectedLayerIds.delete(id);
    if (state.editingLayerId === id) {
      state.editingLayerId = null;
      editor.setMaskEdit(null);
      editor.cancelLasso();
      activateTool("select");
    }
    editor.dropLocalMask(id);
    state.setDirty(true);
    await state.loadLayers();
    state.setStatus("图层已删除");
  }),
});

function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove("show"), 2600);
}

function renderMaps() {
  $("#map-count").textContent = state.maps.length;
  $("#map-empty").hidden = state.maps.length > 0;
  $("#map-list").innerHTML = state.maps.map(map => `
    <div class="map-card ${map.id === state.currentMapId ? "active" : ""}" data-map-id="${map.id}">
      <img src="/api/maps/${map.id}/image" alt=""><div><strong>${escapeHtml(map.source_path.split(/[\\/]/).pop())}</strong><small>${map.width} × ${map.height}</small></div>
      <button type="button" class="map-delete" data-action="delete-map" aria-label="删除地图">删除</button>
    </div>`).join("");
  if (editor.loadedMapId !== state.currentMapId) {
    editor.loadedMapId = state.currentMapId;
    editor.forgetLocalMasks();
  }
  const editorLayers = state.layers.map(layer => ({...layer, map_id: state.currentMapId}));
  editorLayers.push(...state.walkableLayers.map(layer => ({...layer,
    mask_url: `/api/maps/${state.currentMapId}/walkable/layers/${layer.id}/mask`,
    map_id: state.currentMapId, visible: layerPanelMode === "walkable" && layer.visible !== false,
  })));
  editor.setLayers(editorLayers);
  editor.setWalkableLayers(state.walkableLayers.map(layer => layer.id));
  editor.setOcclusionInfoHidden(layerTree.hiddenOcclusion);
  if (state.editingLayerId && ![...state.layers, ...state.walkableLayers].some(layer => layer.id === state.editingLayerId)) {
    state.editingLayerId = null;
    editor.cancelLasso();
  }
  editor.setMaskEdit(state.editingLayerId);
  const editing = [...state.layers, ...state.walkableLayers].find(layer => layer.id === state.editingLayerId);
  const selected = editing || state.layers.find(layer => state.selectedLayerIds.has(layer.id));
  editor.setLocked(false);
  const editBar = $("#edit-actions");
  editBar.hidden = !editing;
  if (editing) $("#edit-label").textContent = `正在编辑「${editing.name}」`;
}

function renderCanvas() {
  const active = Boolean(state.currentMapId);
  $("#canvas-empty").hidden = active; $("#canvas-stage").hidden = !active;
  if (active && $("#map-image").dataset.mapId !== state.currentMapId) {
    $("#map-image").src = `/api/maps/${state.currentMapId}/image`;
    $("#map-image").dataset.mapId = state.currentMapId;
  }
}

function renderLayers() {
  document.querySelectorAll("#layer-mode [data-mode]").forEach(button =>
    button.classList.toggle("active", button.dataset.mode === layerPanelMode));
  $("#resource-heading-actions").hidden = false;
  $(".layer-actions").hidden = layerPanelMode !== "resources";
  $("#walkable-brush").hidden = layerPanelMode !== "walkable";
  const layers = layerPanelMode === "walkable" ? state.walkableLayers : state.orderedLayers();
  $("#layer-empty").hidden = layers.length > 0;
  layerTree.render(layers, activePanelFolders(), state.selectedLayerIds, state.editingLayerId,
    layerPanelMode === "resources" ? occlusionEditingLayerId : null);
}

function render() {
  renderMaps(); renderCanvas(); renderLayers();
  $("#save-state").textContent = state.dirty ? "未保存" : "已保存";
  $("#status").textContent = state.status; $("#status-dot").classList.toggle("busy", state.busy);
}

function escapeHtml(value) { const d=document.createElement("div"); d.textContent=value; return d.innerHTML; }
async function action(work) { try { await work(); } catch (error) { toast(error.message); state.setStatus("操作失败"); } }
function resetSpatialEditing() {
  if (previewMode) $("#preview-mode").click();
  occlusionEditingLayerId = null;
  editor.setOcclusionEditing(null);
}

$("#layer-mode").addEventListener("click", event => {
  const button = event.target.closest("[data-mode]");
  if (!button || button.dataset.mode === layerPanelMode) return;
  if (state.editingLayerId) finishMaskEdit();
  layerPanelMode = button.dataset.mode;
  state.selectedLayerIds.clear();
  state.emit();
});
async function waitJob(jobId) {
  for (;;) {
    const job = await state.api.get(`/api/jobs/${jobId}`);
    if (job.state === "completed") return job.result;
    if (job.state === "failed") throw new Error(job.message);
    await new Promise(resolve => setTimeout(resolve, 350));
  }
}
async function submitSegment(payload) {
  if (!state.currentMapId) throw new Error("请先导入地图");
  state.setStatus("正在生成蒙版", true);
  const {job_id} = await state.api.post(`/api/maps/${state.currentMapId}/segment`, payload);
  await waitJob(job_id); state.setDirty(true); await state.loadLayers(); state.setStatus("蒙版已加入图层");
}

state.addEventListener("change", render);
window.addEventListener("beforeunload", event => state.beforeUnload(event));
$("#map-list").addEventListener("click", event => {
  const card = event.target.closest("[data-map-id]");
  if (!card) return;
  if (event.target.closest("[data-action='delete-map']")) {
    action(async () => {
      await inferenceControls.flushPendingEdits();
      resetSpatialEditing();
      const id = card.dataset.mapId;
      const wasCurrent = state.currentMapId === id;
      await state.api.delete(`/api/maps/${id}`);
      if (wasCurrent) {
        state.currentMapId = null;
        state.layers = [];
        state.folders = [];
        state.selectedLayerIds.clear();
        state.editingLayerId = null;
        editor.setMaskEdit(null);
        editor.cancelLasso();
        editor.forgetLocalMasks();
        editor.loadedMapId = null;
      }
      state.setDirty(true);
      await state.loadMaps();
      state.setStatus("已从列表中移除，原来的图片文件还在");
    });
    return;
  }
  action(async () => { await inferenceControls.flushPendingEdits(); resetSpatialEditing(); await state.selectMap(card.dataset.mapId); });
});
$("#save").addEventListener("click",()=>action(async()=>{await inferenceControls.flushPendingEdits();await state.save();}));
$("#new-project").addEventListener("click",()=>action(async()=>{await inferenceControls.flushPendingEdits();resetSpatialEditing();const {path}=await state.api.get("/api/dialog/folder?title=选择项目保存文件夹");if(!path)return;const name=prompt("项目名称",path.split(/[\\/]/).pop()||"地图项目");if(!name)return;await state.api.post("/api/projects/new",{path,name});state.maps=[];state.currentMapId=null;state.layers=[];state.walkableLayers=[];editor.character=null;editor.render();state.setDirty(true);state.emit();}));
$("#open-project").addEventListener("click",()=>action(async()=>{await inferenceControls.flushPendingEdits();resetSpatialEditing();const {path}=await state.api.get("/api/dialog/folder?title=选择已有项目文件夹");if(!path)return;await state.api.post("/api/projects/open",{path});state.maps=[];state.currentMapId=null;editor.character=null;await state.loadMaps();await restoreCharacter();state.setDirty(false);state.setStatus("项目已打开");}));
$("#import-image").addEventListener("click",()=>action(async()=>{await inferenceControls.flushPendingEdits();resetSpatialEditing();const {path}=await state.api.get("/api/dialog/image");if(!path)return;const map=await state.api.post("/api/import/image",{path});state.currentMapId=map.id;await state.loadMaps();state.setDirty(true);state.setStatus("地图已导入");}));
$("#import-folder").addEventListener("click",()=>action(async()=>{await inferenceControls.flushPendingEdits();resetSpatialEditing();const {path}=await state.api.get("/api/dialog/folder?title=选择地图文件夹");if(!path)return;const maps=await state.api.post("/api/import/folder",{path});await state.loadMaps();if(maps.length)await state.selectMap(maps[0].id);state.setDirty(true);state.setStatus(`已导入 ${maps.length} 张地图`);}));
function activateTool(tool) {
  if (previewMode && tool !== "select") return;
  if (tool === "occlusion" && !occlusionEditingLayerId) {
    toast("请先在右侧图层点击「编辑底线」");
    return;
  }
  document.querySelectorAll("[data-tool]").forEach(item => item.classList.toggle("active", item.dataset.tool === tool));
  editor.setTool(tool);
  if (state.editingLayerId && tool === "box") {
    const layer = [...state.layers, ...state.walkableLayers].find(item => item.id === state.editingLayerId);
    state.setStatus(`框选会识别方框里的物体，并把识别到的区域加进「${layer?.name || "当前蒙版"}」。`);
  }
}
async function saveOcclusionLines(layerId, lines) {
  if (!state.currentMapId) return;
  const updated = await state.api.put(`/api/maps/${state.currentMapId}/layers/${layerId}/occlusion-lines`, {lines});
  const index = state.layers.findIndex(layer => layer.id === layerId);
  if (index >= 0) state.layers[index] = updated;
  state.setDirty(true);
  editor.setLayers(state.layers.map(layer => ({...layer, map_id: state.currentMapId})));
  state.setStatus(lines.length ? "底线已保存" : "底线已清除");
}
function beginOcclusionDrawing(id) {
  if (previewMode) return;
  if (occlusionEditingLayerId === id) {
    occlusionEditingLayerId = null;
    editor.setOcclusionEditing(null);
    activateTool("select");
    state.setStatus("已退出底线编辑");
    state.emit();
    return;
  }
  const layer = state.layers.find(item => item.id === id);
  if (!layer?.mask_path) { toast("底图不能绘制遮挡"); return; }
  state.editingLayerId = null;
  editor.setMaskEdit(null);
  editor.cancelLasso();
  state.selectedLayerIds = new Set([id]);
  occlusionEditingLayerId = id;
  editor.setOcclusionEditing(id);
  activateTool("select");
  state.setStatus(`正在编辑「${layer.name}」底线：拖动节点调整，点击线段后可按 Delete 删除；新画请点击下方「画底线」。`);
  state.emit();
}
function beginMaskEdit(id, tool = "lasso-add") {
  const layer = activePanelLayers().find(item => item.id === id);
  if (!layer?.mask_path) { toast("底图不能这样改"); return; }
  if (state.editingLayerId !== id) editor.cancelLasso();
  occlusionEditingLayerId = null;
  editor.setOcclusionEditing(null);
  state.editingLayerId = id;
  state.selectedLayerIds = new Set([id]);
  editor.setMaskEdit(id);
  activateTool(layer.kind === "walkable" && tool === "lasso-add" ? "brush" : tool);
  state.setStatus(tool === "brush" || tool === "eraser"
    ? `正在编辑「${layer.name}」。图层可以是空的，直接用画笔涂，涂过的地方会留在这一层。`
    : `正在编辑「${layer.name}」。沿着边缘画一圈，画回到发亮的起点。围住的里面才会加进来或减掉。`);
  state.emit();
}
function finishMaskEdit() {
  state.editingLayerId = null;
  editor.setMaskEdit(null);
  editor.cancelLasso();
  activateTool("select");
  state.setStatus("已结束编辑");
}
function closeOpenLasso() {
  if (!editor.closeLasso()) toast("请把线画回到起点。只有围住的里面才会成为区域。");
}
document.querySelectorAll("[data-tool]").forEach(button => button.addEventListener("click", () => activateTool(button.dataset.tool)));
$("#close-lasso").addEventListener("click", closeOpenLasso);
$("#cancel-lasso").addEventListener("click", () => { editor.cancelLasso(); state.setStatus("这一笔已取消"); });
$("#finish-edit").addEventListener("click", finishMaskEdit);
editor.addEventListener("viewchange", event => $("#zoom-label").textContent = `${Math.round(event.detail.scale * 100)}%`);
editor.addEventListener("locked", () => toast("这个图层已锁定，请先点击右侧锁按钮解锁"));
editor.addEventListener("need-edit", () => toast("请先在右侧图层上点击「编辑」，再画套索或用画笔。"));
editor.addEventListener("occlusion-lines", event => action(async () => {
  await saveOcclusionLines(event.detail.layerId, event.detail.lines);
}));
editor.addEventListener("character-delete", () => action(async () => {
  await state.api.delete("/api/character");
  editor.clearCharacter();
  $("#delete-character").classList.remove("active");
  state.setDirty(true);
  state.setStatus("测试小人已删除，可随时重新导入");
}));
$("#zoom-in").addEventListener("click", () => editor.setZoom(editor.view.scale * 1.2));
$("#zoom-out").addEventListener("click", () => editor.setZoom(editor.view.scale / 1.2));
$("#add-folder").addEventListener("click", () => action(async () => {
  if (!state.currentMapId) throw new Error("请先导入地图");
  const name = prompt("文件夹名称", "新文件夹");
  if (!name) return;
  const prefix = layerPanelMode === "walkable" ? "walkable/folders" : "folders";
  const folder = await state.api.post(`/api/maps/${state.currentMapId}/${prefix}`, {name});
  state.setDirty(true);
  await state.loadLayers();
  state.setStatus(`已建立文件夹「${folder.name}」。把图层拖到它上面，就会放进这个文件夹。`);
}));
editor.addEventListener("pick", event => {
  const {id, additive} = event.detail || {};
  if (!id) {
    if (!additive) state.selectedLayerIds.clear();
    state.setStatus("这里没有蒙版");
    state.emit();
    return;
  }
  const layer = activePanelLayers().find(item => item.id === id);
  if (layer?.folder_id) layerTree.collapsed.delete(layer.folder_id);
  const removing = additive && state.selectedLayerIds.has(id);
  state.toggleLayerSelection(id, additive);
  state.setStatus(removing ? `已取消选中「${layer?.name || "图层"}」` : `已选中「${layer?.name || "图层"}」`);
  requestAnimationFrame(() => document.querySelector(`#layer-tree [data-layer-id="${CSS.escape(id)}"]`)?.scrollIntoView({block: "nearest"}));
});
$("#add-layer").addEventListener("click", () => action(async () => {
  if (!state.currentMapId) throw new Error("请先导入地图");
  const layer = await state.api.post(layerPanelMode === "walkable"
    ? `/api/maps/${state.currentMapId}/walkable/layers`
    : `/api/maps/${state.currentMapId}/layers`, {name: layerPanelMode === "walkable" ? "新行走图层" : "新图层"});
  state.setDirty(true);
  await state.loadLayers();
  beginMaskEdit(layer.id, "brush");
  await editor.loadMasks();
  let name = null;
  try { name = prompt("图层名称", layer.name || "新图层"); } catch { name = null; }
  const cleaned = (name || "").trim();
  if (!cleaned || cleaned === layer.name) return;
  await state.api.patch(`${layerBase()}/${layer.id}`, {name: cleaned});
  state.setDirty(true);
  await state.loadLayers();
  state.setStatus(`正在编辑「${cleaned}」。图层可以是空的，直接用画笔涂，涂过的地方会留在这一层。`);
}));
$("#merge").addEventListener("click", () => action(async () => { const ids=[...state.selectedLayerIds].filter(id=>state.layers.find(layer=>layer.id===id)?.kind!=="original"); if(ids.length<2)throw new Error("请先选择至少两个蒙版图层"); await state.api.post(`/api/maps/${state.currentMapId}/layers/merge`,{layer_ids:ids}); state.selectedLayerIds.clear(); state.setDirty(true); await state.loadLayers(); }));
$("#undo").addEventListener("click",()=>action(async()=>{editor.forgetLocalMasks();await state.api.post(`/api/maps/${state.currentMapId}/undo`);state.setDirty(true);await state.loadLayers();}));
$("#redo").addEventListener("click",()=>action(async()=>{editor.forgetLocalMasks();await state.api.post(`/api/maps/${state.currentMapId}/redo`);state.setDirty(true);await state.loadLayers();}));
document.addEventListener("keydown",event=>{if(!(event.ctrlKey||event.metaKey))return;const key=event.key.toLowerCase();if(key==="s"){event.preventDefault();action(()=>state.save());}else if(key==="z"&&!event.shiftKey){event.preventDefault();$("#undo").click();}else if(key==="y"||(key==="z"&&event.shiftKey)){event.preventDefault();$("#redo").click();}});
document.addEventListener("keydown", event => {
  if (event.target.closest("input, textarea, dialog")) return;
  if (event.key === "Escape") {
    if (editor.lasso?.points?.length) { editor.cancelLasso(); state.setStatus("这一笔已取消"); }
    else if (state.editingLayerId) finishMaskEdit();
  } else if (event.key === "Enter" && state.editingLayerId) {
    event.preventDefault();
    closeOpenLasso();
  }
});

const inferenceControls = new InferenceControls({state,editor,api:state.api,toast,elements:{
  detect:$("#detect"),prompt:$("#prompt"),threshold:$("#threshold"),manual:$("#manual-actions"),
  name:$("#manual-name"),generate:$("#generate-mask"),commit:$("#commit-mask"),cancel:$("#cancel-mask")
}});
const exportDialog = new ExportDialog($("#export-dialog"), state, state.api, toast);
$("#export-selected").addEventListener("click", () => exportDialog.open());

$("#auto-baselines").addEventListener("click", () => action(async () => {
  if (!state.currentMapId) throw new Error("请先导入地图");
  const result = await state.api.post(`/api/maps/${state.currentMapId}/occlusion-lines/auto`, {});
  await state.loadLayers();
  state.setDirty(true);
  state.setStatus(result.created
    ? `已为 ${result.created} 个图层生成底线，已有底线的图层没有被覆盖`
    : "没有需要生成的底线");
}));

$("#import-character").addEventListener("click", () => $("#character-file").click());
$("#delete-character").addEventListener("click", () => {
  if (!editor.character) { toast("当前没有可以删除的小人"); return; }
  const enabled = !editor.characterDeleteMode;
  editor.setCharacterDeleteMode(enabled);
  $("#delete-character").classList.toggle("active", enabled);
  state.setStatus(enabled ? "删除小人：点击黄色虚线框右上角的 ×" : "已退出删除小人状态");
});
async function setCharacterFromUrl(url) {
  const image = await new Promise((resolve, reject) => {
    const loaded = new Image(); loaded.onload = () => resolve(loaded);
    loaded.onerror = () => reject(new Error("小人图片读取失败")); loaded.src = url;
  });
  const buffer = document.createElement("canvas"); buffer.width = image.naturalWidth; buffer.height = image.naturalHeight;
  const context = buffer.getContext("2d", {willReadFrequently: true}); context.drawImage(image, 0, 0);
  editor.setCharacter(image, opaqueFootpoint(context.getImageData(0, 0, buffer.width, buffer.height).data, buffer.width, buffer.height));
}
async function restoreCharacter() {
  const info = await state.api.get("/api/character/info");
  if (!info.available) return;
  await setCharacterFromUrl(`/api/character?v=${Date.now()}`);
  $("#character-scale").value = Math.round(info.scale * 100);
  editor.setCharacterScale(info.scale);
}
$("#character-file").addEventListener("change", event => action(async () => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!state.currentMapId) throw new Error("请先导入地图");
  const url = URL.createObjectURL(file);
  try {
    await setCharacterFromUrl(url);
    editor.setCharacterDeleteMode(false);
    $("#delete-character").classList.remove("active");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = ""; for (const byte of bytes) binary += String.fromCharCode(byte);
    await state.api.put("/api/character", {png_base64: btoa(binary), scale: editor.characterScale});
    state.setDirty(true);
    activateTool("select");
    state.setStatus("小人已导入，可以用「选择与移动」拖动测试");
  } finally {
    URL.revokeObjectURL(url);
    event.target.value = "";
  }
}));
$("#character-scale").addEventListener("input", event => {
  const scale = Number(event.target.value) / 100; editor.setCharacterScale(scale);
  action(async()=>{if(editor.character){await state.api.patch("/api/character",{scale});state.setDirty(true);}});
});
$("#preview-mode").addEventListener("click", () => {
  if (!previewMode && !editor.character) { toast("请先导入测试人物"); return; }
  previewMode = !previewMode;
  const button = $("#preview-mode");
  if (previewMode) {
    toolBeforePreview = editor.tool;
    editor.setMaskEdit(null);
    editor.setPreviewMode(true);
    editor.setTool("select");
    document.body.classList.add("preview-mode");
    button.textContent = "退出预览";
    state.setStatus("预览中：拖动小人查看遮挡效果");
  } else {
    editor.setPreviewMode(false);
    editor.setMaskEdit(state.editingLayerId);
    editor.setTool(toolBeforePreview || "select");
    document.body.classList.remove("preview-mode");
    button.textContent = "预览";
    state.setStatus("已退出预览");
  }
  document.querySelectorAll("[data-tool]").forEach(item => item.classList.toggle("active", item.dataset.tool === editor.tool));
});

action(async()=>{state.setStatus("正在读取项目",true);await state.loadMaps();await restoreCharacter();state.setStatus("准备就绪");});
