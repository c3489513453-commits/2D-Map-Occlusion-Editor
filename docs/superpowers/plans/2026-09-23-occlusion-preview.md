# 地图遮挡区域与人物预览实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有本地地图抠图工具中加入遮挡区域标注、测试人物拖动、纯净预览以及全尺寸 PNG + JSON 遮挡包导出。

**Architecture:** 在现有 `LayerState` 上保存地图像素坐标多边形，由后端校验并通过可撤销命令修改；画布新增独立的遮挡区域与测试人物状态，预览时用原图和蒙版合成前景遮挡。普通透明素材导出保持不变，勾选新选项时由导出器生成独立遮挡包。

**Tech Stack:** Python 3、FastAPI、Pillow、NumPy、原生 JavaScript、Canvas 2D、HTML/CSS、pytest、浏览器内测试页。

**Spec:** `docs/superpowers/specs/2026-09-23-occlusion-preview-design.md`

## Global Constraints

- 保留中文界面、双击启动、`127.0.0.1` 本地限制和无 npm 构建流程。
- 不训练或更换 Grounding DINO Tiny 与 SAM 2.1 Hiera Small。
- 蒙版 PNG 修改即时写入；`project.json` 继续只在用户按 `Ctrl+S` 时保存。
- 不覆盖当前工作区已有未提交修改，不提交或推送，除非用户另行明确要求。
- 遮挡区域使用原地图左上角为原点的像素坐标；遮挡包 PNG 强制与原图同尺寸。
- 第一版不做 Y 排序、桥梁/房屋特殊规则、节点拖动或人物脚底手动校正。

## Review Focus

- 旧项目缺少 `occlusion_regions` 时必须正常加载并保存为空数组；由任务 1 的兼容测试覆盖。
- 多边形包含 NaN、无穷、少于三个点或越界坐标时必须返回中文 400；由任务 2 的接口测试覆盖。
- 人物 PNG 底部透明、最低行有多个像素或整张透明时必须得到稳定脚底或明确错误；由任务 4 的浏览器单元测试覆盖。
- 快速切换地图或退出预览不能留下上一张地图的区域、人物遮挡缓存或工具状态；由任务 5 的状态测试覆盖。
- Windows 安全文件名发生重名改写时，`occlusion.json` 必须引用实际输出路径；由任务 3 的导出测试覆盖。

---

### Task 1: 图层遮挡数据兼容

**Files:**
- Modify: `map_cutout/domain.py`
- Modify: `map_cutout/project_store.py`
- Test: `tests/map_cutout/test_project_store.py`

**Interfaces:**
- Produces: `LayerState.occlusion_regions: list[list[list[float]]]`，旧 JSON 默认 `[]`。
- Consumes: 现有 `ProjectState.to_dict()` 与 `_layer_from_dict()`。

- [ ] **Step 1: 写失败测试**

新增测试分别加载不含字段的旧图层和含两个多边形的新图层，断言默认值为空、坐标往返不变，并断言 `ProjectStore.save()` 输出字段。

- [ ] **Step 2: 运行测试确认失败**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/map_cutout/test_project_store.py -q -p no:cacheprovider`

Expected: `LayerState` 不接受或不存在 `occlusion_regions`。

- [ ] **Step 3: 最小实现**

在 `LayerState` 末尾增加：

```python
occlusion_regions: list[list[list[float]]] = field(default_factory=list)
```

将 `_layer_from_dict()` 改为显式补默认值，避免旧项目失败：

```python
return LayerState(**{**data, "occlusion_regions": data.get("occlusion_regions", [])})
```

- [ ] **Step 4: 运行测试确认通过并检查差异**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/map_cutout/test_project_store.py -q -p no:cacheprovider`

Run: `git -c safe.directory="D:/06/剧本/地图抠图/Grounded-SAM-2" diff --check`

### Task 2: 遮挡区域校验、接口与撤销

**Files:**
- Modify: `map_cutout/commands.py`
- Modify: `map_cutout/web_app.py`
- Test: `tests/map_cutout/test_api.py`

**Interfaces:**
- Produces: `PUT /api/maps/{map_id}/layers/{layer_id}/occlusion-regions`，请求 `{"regions": [[[x, y], ...]]}`，响应更新后的图层。
- Produces: `SetOcclusionRegionsCommand(state, layer_id, regions)`，支持 execute/undo。
- Consumes: Task 1 的 `LayerState.occlusion_regions`。

- [ ] **Step 1: 写失败接口测试**

覆盖有效多区域写入、`Ctrl+Z` 等价的 undo 恢复、原始底图拒绝、未知图层、少于三个点、非数值、NaN/无穷和超出地图边界。有效请求示例：

```python
payload = {"regions": [[[10, 10], [80, 10], [80, 90], [10, 90]]]}
response = client.put(f"/api/maps/{map_id}/layers/{layer_id}/occlusion-regions", json=payload)
assert response.status_code == 200
assert response.json()["occlusion_regions"] == payload["regions"]
```

- [ ] **Step 2: 运行目标测试确认失败**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/map_cutout/test_api.py -k occlusion -q -p no:cacheprovider`

Expected: 404 或命令不存在。

- [ ] **Step 3: 实现校验和可撤销命令**

新增纯函数：

```python
def validated_regions(raw, width: int, height: int) -> list[list[list[float]]]: ...
```

只接受列表；每区至少三个 `[x, y]`；用 `math.isfinite()`；范围为 `0 <= x <= width`、`0 <= y <= height`。接口拒绝底图和无蒙版层，执行 `SetOcclusionRegionsCommand`，设置 `project.dirty = True`。

- [ ] **Step 4: 运行接口测试和既有命令测试**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/map_cutout/test_api.py tests/map_cutout/test_commands.py -q -p no:cacheprovider --basetemp "D:\06\剧本\地图抠图\项目输出\pytest-occlusion-api"`

Expected: PASS。

### Task 3: 遮挡包导出

**Files:**
- Modify: `map_cutout/exporter.py`
- Modify: `map_cutout/web_app.py`
- Modify: `map_cutout/static/export_dialog.js`
- Modify: `map_cutout/static/index.html`
- Test: `tests/map_cutout/test_exporter.py`
- Test: `tests/map_cutout/test_api.py`

**Interfaces:**
- Adds: `BatchExportRequest.include_occlusion: bool = False`。
- Produces: `BatchExportReport.occlusion_manifests: list[Path]`。
- Consumes: Task 1 的区域字段与现有 `export_layer(..., ExportMode.FULL_SIZE)`。

- [ ] **Step 1: 写失败导出测试**

建立含两个有效遮挡层、一个无区域层和重名图层的项目；断言只输出有效层到 `occluders/`，所有 PNG 尺寸等于地图，`occlusion.json` 使用 POSIX 相对路径并引用实际去重文件名。另测未勾选时没有 JSON 且原导出模式不变。

- [ ] **Step 2: 运行导出测试确认失败**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/map_cutout/test_exporter.py -k occlusion -q -p no:cacheprovider`

- [ ] **Step 3: 实现导出器**

为每张选中地图建立独立输出目录；遮挡包结构：

```text
<地图名>/occlusion.json
<地图名>/occluders/<安全图层名>.png
```

JSON 结构固定为：

```json
{"version":1,"map":{"width":1920,"height":1080,"coordinateOrigin":"top-left"},"occluders":[]}
```

每个条目写 `id`、`name`、`image`、`imageMode: "full_size"`、`regions`。使用 UTF-8、`ensure_ascii=False`、缩进 2。

- [ ] **Step 4: 接通 API 和导出对话框**

在表单加入默认未勾选的“导出遮挡关系配置”；勾选后 `export_dialog.js` 发送 `include_occlusion: true`。后端报告返回 manifest 路径，结果区显示遮挡配置数量。

- [ ] **Step 5: 运行导出与 API 测试**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/map_cutout/test_exporter.py tests/map_cutout/test_api.py -q -p no:cacheprovider --basetemp "D:\06\剧本\地图抠图\项目输出\pytest-occlusion-export"`

Expected: PASS。

### Task 4: 画布遮挡几何与测试人物

**Files:**
- Create: `map_cutout/static/occlusion_preview.js`
- Modify: `map_cutout/static/canvas_editor.js`
- Modify: `tests/web/canvas_editor.test.html`

**Interfaces:**
- Produces: `pointInPolygon(point, polygon): boolean`。
- Produces: `opaqueFootpoint(imageData, width, height): {x:number,y:number}`，全透明时抛出中文错误。
- Produces: `CanvasEditor.setCharacter(image, footpoint)`、`setCharacterScale(scale)`、`setOcclusionDrawing(layerId)`、`setPreviewMode(enabled)`。
- Consumes: Task 1 的 `layer.occlusion_regions`。

- [ ] **Step 1: 写失败浏览器单元测试**

在现有测试页加入：边界内外点、边线上点的稳定判断；底部透明人物；最低非透明行中心；全透明图片报错；缩放后脚底地图坐标不漂移。

- [ ] **Step 2: 运行浏览器测试确认失败**

启动测试服务并打开 `tests/web/canvas_editor.test.html`；Expected: 页面标题不是 `PASS`，缺少导出函数。

- [ ] **Step 3: 实现纯函数和人物状态**

`occlusion_preview.js` 只负责几何与 Alpha 分析，避免把算法继续塞入 `canvas_editor.js`。人物状态记录图片、原始脚底、地图脚底坐标和比例；拖动时保持鼠标与人物脚底的偏移。

- [ ] **Step 4: 实现区域绘制事件**

新增工具 `occlusion`：单击添加地图坐标节点，靠近起点时闭合并派发：

```javascript
new CustomEvent("occlusion-regions", {
  detail: {layerId, regions: [...existingRegions, committedPolygon]}
})
```

`Escape` 清除未闭合区域。橙色填充、边线和黄色节点只在非预览且图层辅助信息开启时绘制。

- [ ] **Step 5: 实现合成渲染顺序**

Canvas 顺序为：蓝色编辑蒙版（仅编辑态）、人物、命中区域对应的原色蒙版裁切像素、橙色辅助区域（仅编辑态）。原色遮挡缓存由原图和灰度蒙版生成，图层/地图变化时失效。

- [ ] **Step 6: 运行浏览器测试**

Expected: `canvas_editor.test.html` 标题为 `PASS`，既有套索和蒙版缓存测试仍通过。

### Task 5: 页面交互、图层行与纯净预览

**Files:**
- Modify: `map_cutout/static/index.html`
- Modify: `map_cutout/static/styles.css`
- Modify: `map_cutout/static/layer_tree.js`
- Modify: `map_cutout/static/app.js`
- Modify: `tests/web/layer_tree.test.html`
- Modify: `tests/web/canvas_editor.test.html`

**Interfaces:**
- Consumes: Task 2 的区域 PUT 接口和 Task 4 的 CanvasEditor 方法/事件。
- Produces: LayerTree callbacks `onDrawOcclusion(id)`、`onToggleOcclusionInfo(id)`。

- [ ] **Step 1: 写失败图层树测试**

断言蒙版行无“蒙版”文字，“继续编辑”变为“编辑”，每行有“绘制遮挡”，最右按钮是无文字小圆形图标，且分别触发正确回调；底图不显示这些控件。

- [ ] **Step 2: 修改图层行**

压缩按钮布局；用 `aria-label` 保留无障碍名称。辅助信息显隐只保存在前端 `Set` 中，不 PATCH `locked`，不改变实际遮挡。

- [ ] **Step 3: 增加顶部与底部控件**

顶部加入隐藏的 `accept="image/png"` 文件输入、“导入小人”、“预览/退出预览”和人物比例控件；底部把“选择”改为带指针/移动图标的“选择与移动”。

- [ ] **Step 4: 接通区域保存与删除**

收到 `occlusion-regions` 后 PUT 全量区域，更新 `state.layers`、dirty 状态与图层树。提供删除当前图层全部遮挡区域的紧凑按钮；操作前不弹确认，依靠 undo 恢复。

- [ ] **Step 5: 接通人物导入和预览状态机**

导入时读取本地 File 为 Image/Data URL，计算脚底并放在地图中心。进入预览前要求已有地图和人物，保存当前工具，隐藏辅助绘制并禁用编辑按钮；退出后恢复工具、选择与显隐状态，保留人物位置。

- [ ] **Step 6: 清理跨地图状态**

切换地图、新建/打开项目和删除当前地图时取消未完成区域、退出预览、清理原色遮挡缓存；人物图片可留在会话中，但在新地图上重新居中。

- [ ] **Step 7: 运行两个浏览器测试页**

Expected: `tests/web/canvas_editor.test.html` 和 `tests/web/layer_tree.test.html` 标题均为 `PASS`。

### Task 6: 回归验证与用户文档

**Files:**
- Modify: `docs/map-cutout-user-guide.md`

**Interfaces:**
- Consumes: Tasks 1–5 的最终用户流程。

- [ ] **Step 1: 更新中文用户指南**

写清“导入小人 → 每行绘制遮挡 → 预览 → 退出预览调整 → Ctrl+S → 导出遮挡配置”的操作；解释蓝色蒙版与橙色区域区别，以及 JSON 必须与 PNG 一起使用。

- [ ] **Step 2: 运行完整 Python 测试**

Run: `\.\.venv\Scripts\python.exe -m pytest tests\map_cutout tests\test_hf_demo_processor_api.py -q -p no:cacheprovider --basetemp "D:\06\剧本\地图抠图\项目输出\pytest-occlusion-final"`

Expected: 全部通过；仅允许文档中已知的 FastAPI/Starlette 弃用警告。

- [ ] **Step 3: 运行浏览器测试并人工走查**

使用测试服务验证两个测试页为 `PASS`；再用真实项目验证人物拖入树前/树后、隐藏辅助线、进入/退出纯净预览、保存重开、导出并读取 JSON。

- [ ] **Step 4: 最终差异检查**

Run: `git -c safe.directory="D:/06/剧本/地图抠图/Grounded-SAM-2" diff --check`

确认没有改动模型、虚拟环境、地图原图、项目输出目录或用户无关文件；不提交、不推送。
