import { AppState, ApiClient } from "/static/state.js";

const state = new AppState(new ApiClient());
const $ = selector => document.querySelector(selector);
let toastTimer;

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
  $("#layer-tree").innerHTML = layers.map(layer => `
    <div class="layer-row ${state.selectedLayerIds.has(layer.id) ? "selected" : ""}" data-layer-id="${layer.id}">
      <button class="toggle eye ${layer.visible ? "on" : ""}" data-action="visibility" aria-label="显示或隐藏">${layer.visible ? "◉" : "○"}</button>
      <span class="name">${escapeHtml(layer.name)}</span><span class="layer-kind">${layer.kind === "original" ? "底图" : "蒙版"}</span>
      <button class="toggle lock ${layer.locked ? "on" : ""}" data-action="lock" aria-label="锁定或解锁">${layer.locked ? "▣" : "□"}</button>
    </div>`).join("");
}

function render() {
  renderMaps(); renderCanvas(); renderLayers();
  $("#save-state").textContent = state.dirty ? "未保存" : "已保存";
  $("#status").textContent = state.status; $("#status-dot").classList.toggle("busy", state.busy);
}

function escapeHtml(value) { const d=document.createElement("div"); d.textContent=value; return d.innerHTML; }
async function action(work) { try { await work(); } catch (error) { toast(error.message); state.setStatus("操作失败"); } }

state.addEventListener("change", render);
window.addEventListener("beforeunload", event => state.beforeUnload(event));
$("#map-list").addEventListener("click", event => { const card=event.target.closest("[data-map-id]"); if(card) action(()=>state.selectMap(card.dataset.mapId)); });
$("#layer-tree").addEventListener("click", event => action(async () => {
  const row=event.target.closest("[data-layer-id]"); if(!row) return;
  const id=row.dataset.layerId, layer=state.layers.find(item=>item.id===id), actionName=event.target.dataset.action;
  if(actionName){ const key=actionName==="visibility"?"visible":"locked"; await state.api.patch(`/api/maps/${state.currentMapId}/layers/${id}`,{[key]:!layer[key]}); state.setDirty(true); await state.loadLayers(); }
  else state.toggleLayerSelection(id,event.ctrlKey||event.metaKey);
}));
$("#save").addEventListener("click",()=>action(()=>state.save()));
$("#undo").addEventListener("click",()=>action(async()=>{await state.api.post(`/api/maps/${state.currentMapId}/undo`);state.setDirty(true);await state.loadLayers();}));
$("#redo").addEventListener("click",()=>action(async()=>{await state.api.post(`/api/maps/${state.currentMapId}/redo`);state.setDirty(true);await state.loadLayers();}));
document.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();action(()=>state.save());}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="z"){event.preventDefault();$("#undo").click();}});

action(async()=>{state.setStatus("正在读取项目",true);await state.loadMaps();state.setStatus("准备就绪");});

