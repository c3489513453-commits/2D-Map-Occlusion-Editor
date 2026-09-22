export class InferenceControls{
 constructor({state,editor,api,toast,elements}){this.state=state;this.editor=editor;this.api=api;this.toast=toast;this.el=elements;this.pending=null;this.previewId=null;this.paintChain=Promise.resolve();this.editSerial=0;this.bind()}
 bind(){this.el.detect.addEventListener("click",()=>this.run(()=>this.detect()));this.el.generate.addEventListener("click",()=>this.run(()=>this.generate()));this.el.commit.addEventListener("click",()=>this.run(()=>this.commit()));this.el.cancel.addEventListener("click",()=>this.run(()=>this.cancel()));this.editor.addEventListener("box",e=>this.prepare({box:e.detail}));this.editor.addEventListener("points",e=>this.prepare({points:e.detail.points,labels:e.detail.labels}));this.editor.addEventListener("stroke",e=>this.run(()=>this.paint(e.detail)))}
 async run(work){try{await work()}catch(error){this.state.setStatus("操作失败");this.toast(error.message)}}
 async wait(jobId){const phases=["加载模型","检测目标","生成蒙版","建立图层"];let tick=0;for(;;){this.state.setStatus(phases[Math.min(Math.floor(tick++/2),3)],true);const job=await this.api.get(`/api/jobs/${jobId}`);if(job.state==="completed")return job.result;if(job.state==="failed")throw Error(job.message);await new Promise(r=>setTimeout(r,350))}}
 async detect(){if(!this.state.currentMapId)throw Error("请先导入地图");const prompt=this.el.prompt.value.trim();if(!prompt)throw Error("请输入要识别的物体");const {job_id}=await this.api.post(`/api/maps/${this.state.currentMapId}/detect`,{prompt,threshold:Number(this.el.threshold.value)});const created=await this.wait(job_id);this.state.selectedLayerIds=new Set(created.map(layer=>layer.id));this.state.setDirty(true);await this.state.loadLayers();this.state.setStatus(`识别完成，已建立 ${created.length} 个图层`)}
 prepare(data){this.pending=data;this.el.manual.hidden=false;this.el.commit.hidden=true;this.el.generate.hidden=false;this.state.setStatus("提示已标记，请生成蒙版")}
 async generate(){if(!this.pending)throw Error("请先框选或添加提示点");const name=this.el.name.value.trim()||"object";const {job_id}=await this.api.post(`/api/maps/${this.state.currentMapId}/segment`,{...this.pending,name});const preview=await this.wait(job_id);this.previewId=preview.preview_id;await this.editor.setPreview(preview.mask_url);this.el.generate.hidden=true;this.el.commit.hidden=false;this.state.setStatus("蒙版预览已生成，请确认建立图层")}
 async commit(){if(!this.previewId)return;const layer=await this.api.post(`/api/maps/${this.state.currentMapId}/segment/commit`,{preview_id:this.previewId,name:this.el.name.value.trim()||"object"});this.state.selectedLayerIds=new Set([layer.id]);this.state.setDirty(true);await this.state.loadLayers();this.clear();this.state.setStatus("新图层已建立")}
 async cancel(){if(this.previewId)await this.api.delete(`/api/previews/${this.previewId}`);this.clear();this.state.setStatus("已取消手动分割")}
 clear(){this.pending=null;this.previewId=null;this.el.manual.hidden=true;this.editor.setPreview(null);this.editor.points=[];this.editor.render()}
 async paint(stroke){
  const id=this.state.editingLayerId;
  if(!id)throw Error("请先在右侧蒙版图层上点击「继续编辑」");
  const layer=this.state.layers.find(item=>item.id===id);
  if(!layer||!layer.mask_path)throw Error("请先选择一张已有蒙版");
  if(layer.locked)throw Error("这个图层已锁定，请先点最右边的锁解锁");
  if(!this.editor.maskImages.get(id))await this.editor.loadMasks();
  const serial=++this.editSerial;
  this.editor.editMaskLocally(id,stroke);
  this.editor.cancelLasso();
  const task=this.paintChain.then(()=>this.api.post(`/api/maps/${this.state.currentMapId}/layers/${id}/paint`,stroke));
  this.paintChain=task.catch(()=>{});
  try{
    await task;
    this.state.setDirty(true);
    const added=Boolean(stroke.value);
    this.state.setStatus(stroke.shape==="polygon"
      ?(added?`已把这块区域加到「${layer.name}」`:`已从「${layer.name}」减去这块区域`)
      :(added?`已在「${layer.name}」上继续画上`:`已在「${layer.name}」上擦掉这一笔`));
  }catch(error){
    if(this.editSerial===serial){
      this.editor.dropLocalMask(id);
      await this.editor.loadMasks();
    }
    if(this.editor.lasso)this.editor.lasso.committing=false;
    throw error;
  }
 }
}
