import { AppState, ApiClient } from "/static/state.js";
import { CanvasEditor } from "/static/canvas_editor.js";
import { LayerTree } from "/static/layer_tree.js";
import { InferenceControls } from "/static/inference_controls.js";
import { ExportDialog } from "/static/export_dialog.js";

const state = new AppState(new ApiClient());
const $ = selector => document.querySelector(selector);
let toastTimer;
const editor = new CanvasEditor($("#canvas-shell"), $("#canvas-stage"), $("#map-image"), $("#mask-canvas"));
state.editingLayerId = null;
const layerTree = new LayerTree($("#layer-tree"), {
  onSelect: (id, additive) => state.toggleLayerSelection(id, additive),
  onEdit: id => beginMaskEdit(id),
  onPatch: (id, changes) => action(async () => { await state.api.patch(`/api/maps/${state.currentMapId}/layers/${id}`, changes); state.setDirty(true); await state.loadLayers(); }),
  onMove: (id, targetId) => action(async () => { const index=state.layers.findIndex(layer=>layer.id===targetId); await state.api.patch(`/api/maps/${state.currentMapId}/layers/${id}`, {index}); state.setDirty(true); await state.loadLayers(); }),
  onDelete: id => action(async () => {
    const layer = state.layers.find(item => item.id === id);
    if (!layer || !confirm(`确定删除图层“${layer.name}”吗？可用 Ctrl+Z 撤销。`)) return;
    await state.api.delete(`/api/maps/${state.currentMapId}/layers/${id}`);
    state.selectedLayerIds.delete(id);
    editor.maskImages.delete(id); editor.maskOverlays.delete(id);
    state.setDirty(true); await state.loadLayers(); state.setStatus("图层已删除");
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
    </div>`).join("");
  if (editor.loadedMapId !== state.currentMapId) {
    editor.loadedMapId = state.currentMapId;
    editor.forgetLocalMasks();
  }
  editor.setLayers(state.layers.map(layer => ({...layer, map_id: state.currentMapId})));
  if (state.editingLayerId && !state.layers.some(layer => layer.id === state.editingLayerId)) {
    state.editingLayerId = null;
    editor.cancelLasso();
  }
  editor.setMaskEdit(state.editingLayerId);
  const editing = state.layers.find(layer => layer.id === state.editingLayerId);
  const selected = editing || state.layers.find(layer => state.selectedLayerIds.has(layer.id));
  editor.setLocked(Boolean(selected?.locked));
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
  const layers = state.orderedLayers();
  $("#layer-empty").hidden = layers.length > 0;
  layerTree.render(state.layers, state.folders, state.selectedLayerIds, state.editingLayerId);
}

function render() {
  renderMaps(); renderCanvas(); renderLayers();
  $("#save-state").textContent = state.dirty ? "未保存" : "已保存";
  $("#status").textContent = state.status; $("#status-dot").classList.toggle("busy", state.busy);
}

function escapeHtml(value) { const d=document.createElement("div"); d.textContent=value; return d.innerHTML; }
async function action(work) { try { await work(); } catch (error) { toast(error.message); state.setStatus("操作失败"); } }
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
$("#map-list").addEventListener("click", event => { const card=event.target.closest("[data-map-id]"); if(card) action(()=>state.selectMap(card.dataset.mapId)); });
$("#save").addEventListener("click",()=>action(()=>state.save()));
$("#new-project").addEventListener("click",()=>action(async()=>{const {path}=await state.api.get("/api/dialog/folder?title=选择项目保存文件夹");if(!path)return;const name=prompt("项目名称",path.split(/[\\/]/).pop()||"地图项目");if(!name)return;await state.api.post("/api/projects/new",{path,name});state.maps=[];state.currentMapId=null;state.layers=[];state.setDirty(true);state.emit();}));
$("#open-project").addEventListener("click",()=>action(async()=>{const {path}=await state.api.get("/api/dialog/folder?title=选择已有项目文件夹");if(!path)return;await state.api.post("/api/projects/open",{path});state.maps=[];state.currentMapId=null;await state.loadMaps();state.setDirty(false);state.setStatus("项目已打开");}));
$("#import-image").addEventListener("click",()=>action(async()=>{const {path}=await state.api.get("/api/dialog/image");if(!path)return;const map=await state.api.post("/api/import/image",{path});state.currentMapId=map.id;await state.loadMaps();state.setDirty(true);state.setStatus("地图已导入");}));
$("#import-folder").addEventListener("click",()=>action(async()=>{const {path}=await state.api.get("/api/dialog/folder?title=选择地图文件夹");if(!path)return;const maps=await state.api.post("/api/import/folder",{path});await state.loadMaps();if(maps.length)await state.selectMap(maps[0].id);state.setDirty(true);state.setStatus(`已导入 ${maps.length} 张地图`);}));
function activateTool(tool) {
  document.querySelectorAll("[data-tool]").forEach(item => item.classList.toggle("active", item.dataset.tool === tool));
  editor.setTool(tool);
}
function beginMaskEdit(id) {
  const layer = state.layers.find(item => item.id === id);
  if (!layer?.mask_path) { toast("底图不能这样改"); return; }
  if (layer.locked) { toast("这个图层已锁定，请先点最右边的锁解锁"); return; }
  if (state.editingLayerId !== id) editor.cancelLasso();
  state.editingLayerId = id;
  state.selectedLayerIds = new Set([id]);
  editor.setMaskEdit(id);
  activateTool("lasso-add");
  state.setStatus(`正在编辑「${layer.name}」。沿着边缘画一圈，画回到发亮的起点。围住的里面才会加进来或减掉。`);
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
editor.addEventListener("need-edit", () => toast("请先在右侧蒙版图层上点击「继续编辑」，再画套索或用画笔。"));
$("#zoom-in").addEventListener("click", () => editor.setZoom(editor.view.scale * 1.2));
$("#zoom-out").addEventListener("click", () => editor.setZoom(editor.view.scale / 1.2));
$("#add-folder").addEventListener("click", () => action(async () => { const name=prompt("文件夹名称","新文件夹"); if(!name)return; const folder=await state.api.post(`/api/maps/${state.currentMapId}/folders`,{name}); state.folders.push(folder); state.setDirty(true); state.emit(); }));
$("#add-layer").addEventListener("click", () => action(async () => {
  if (!state.currentMapId) throw new Error("请先导入地图");
  const name = prompt("图层名称", "新图层");
  if (!name || !name.trim()) return;
  const layer = await state.api.post(`/api/maps/${state.currentMapId}/layers`, {name: name.trim()});
  state.setDirty(true);
  await state.loadLayers();
  beginMaskEdit(layer.id);
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

new InferenceControls({state,editor,api:state.api,toast,elements:{
  detect:$("#detect"),prompt:$("#prompt"),threshold:$("#threshold"),manual:$("#manual-actions"),
  name:$("#manual-name"),generate:$("#generate-mask"),commit:$("#commit-mask"),cancel:$("#cancel-mask")
}});
const exportDialog = new ExportDialog($("#export-dialog"), state, state.api, toast);
$("#export-selected").addEventListener("click", () => exportDialog.open());

action(async()=>{state.setStatus("正在读取项目",true);await state.loadMaps();state.setStatus("准备就绪");});
