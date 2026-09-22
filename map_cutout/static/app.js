import { AppState, ApiClient } from "/static/state.js";
import { CanvasEditor } from "/static/canvas_editor.js";
import { LayerTree } from "/static/layer_tree.js";

const state = new AppState(new ApiClient());
const $ = selector => document.querySelector(selector);
let toastTimer;
const editor = new CanvasEditor($("#canvas-shell"), $("#canvas-stage"), $("#map-image"), $("#mask-canvas"));
const layerTree = new LayerTree($("#layer-tree"), {
  onSelect: (id, additive) => state.toggleLayerSelection(id, additive),
  onPatch: (id, changes) => action(async () => { await state.api.patch(`/api/maps/${state.currentMapId}/layers/${id}`, changes); state.setDirty(true); await state.loadLayers(); }),
  onMove: (id, targetId) => action(async () => { const index=state.layers.findIndex(layer=>layer.id===targetId); await state.api.patch(`/api/maps/${state.currentMapId}/layers/${id}`, {index}); state.setDirty(true); await state.loadLayers(); }),
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
  editor.setLayers(state.layers.map(layer => ({...layer, map_id: state.currentMapId})));
  const selected = state.layers.find(layer => state.selectedLayerIds.has(layer.id));
  editor.setLocked(Boolean(selected?.locked));
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
  layerTree.render(state.layers, state.folders, state.selectedLayerIds);
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
document.querySelectorAll("[data-tool]").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll("[data-tool]").forEach(item => item.classList.remove("active"));
  button.classList.add("active"); editor.setTool(button.dataset.tool);
}));
editor.addEventListener("viewchange", event => $("#zoom-label").textContent = `${Math.round(event.detail.scale * 100)}%`);
editor.addEventListener("locked", () => toast("这个图层已锁定，请先点击右侧锁按钮解锁"));
editor.addEventListener("box", event => action(() => submitSegment({box:event.detail,name:"object"})));
editor.addEventListener("points", event => state.setStatus(`已添加 ${event.detail.points.length} 个提示点`));
editor.addEventListener("stroke", () => state.setStatus("画笔修改待提交"));
$("#zoom-in").addEventListener("click", () => editor.setZoom(editor.view.scale * 1.2));
$("#zoom-out").addEventListener("click", () => editor.setZoom(editor.view.scale / 1.2));
$("#add-folder").addEventListener("click", () => action(async () => { const name=prompt("文件夹名称","新文件夹"); if(!name)return; const folder=await state.api.post(`/api/maps/${state.currentMapId}/folders`,{name}); state.folders.push(folder); state.setDirty(true); state.emit(); }));
$("#merge").addEventListener("click", () => action(async () => { const ids=[...state.selectedLayerIds].filter(id=>state.layers.find(layer=>layer.id===id)?.kind!=="original"); if(ids.length<2)throw new Error("请先选择至少两个蒙版图层"); await state.api.post(`/api/maps/${state.currentMapId}/layers/merge`,{layer_ids:ids}); state.selectedLayerIds.clear(); state.setDirty(true); await state.loadLayers(); }));
$("#undo").addEventListener("click",()=>action(async()=>{await state.api.post(`/api/maps/${state.currentMapId}/undo`);state.setDirty(true);await state.loadLayers();}));
$("#redo").addEventListener("click",()=>action(async()=>{await state.api.post(`/api/maps/${state.currentMapId}/redo`);state.setDirty(true);await state.loadLayers();}));
document.addEventListener("keydown",event=>{if(!(event.ctrlKey||event.metaKey))return;const key=event.key.toLowerCase();if(key==="s"){event.preventDefault();action(()=>state.save());}else if(key==="z"&&!event.shiftKey){event.preventDefault();$("#undo").click();}else if(key==="y"||(key==="z"&&event.shiftKey)){event.preventDefault();$("#redo").click();}});

action(async()=>{state.setStatus("正在读取项目",true);await state.loadMaps();state.setStatus("准备就绪");});
