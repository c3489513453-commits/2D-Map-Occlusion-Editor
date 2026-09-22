# 本地地图素材抠图工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Grounded SAM 2 仓库内交付一个可双击启动的中文本地浏览器工具，支持文件夹导入、自动/手动分割、图层与文件夹管理、项目保存和两种透明 PNG 导出模式。

**Architecture:** Python/FastAPI 提供本地 API、项目持久化、推理和导出；无构建步骤的 HTML/CSS/JavaScript 页面提供三栏界面和 Canvas 交互。前后端只交换 JSON、图片 URL 与压缩后的蒙版，所有编辑最终映射回原图坐标。

**Tech Stack:** Python 3.10.21、PyTorch 2.3.1+cu118、Grounding DINO、SAM 2.1、FastAPI、Uvicorn、Pillow、NumPy、OpenCV、原生 HTML/CSS/JavaScript Canvas、pytest。

**Spec:** `docs/superpowers/specs/2026-09-22-map-cutout-tool-design.md`

## Global Constraints

- 只监听 `127.0.0.1`，地图和蒙版不得上传到外部服务。
- 支持 PNG、JPG、JPEG 输入；源图片永不覆盖。
- 默认项目根目录为 `D:\06\剧本\地图抠图\项目输出`，用户可另选位置。
- 不自动保存；`Ctrl+S` 保存，存在未保存修改时切图和退出必须提醒。
- 每张地图的原始地图图层固定在最底层，默认显示且锁定。
- 自动识别结果全部直接建立独立图层，类别编号连续且不得覆盖现有图层。
- 普通图层支持显隐、锁定、重命名、删除、复制、多选、排序、合并和文件夹归属。
- 图层文件夹只由用户创建，不按类别自动建立。
- 撤销栈按地图隔离，最多 50 步；重启后不恢复撤销历史。
- 透明素材统一导出 RGBA PNG，并提供紧凑裁剪和原图尺寸两种策略。
- Windows 中文路径必须作为正常用例，不允许依赖 OpenCV 的窄字符路径读写。
- 第一版不实现训练、遮挡最低线、碰撞、传送、Photoshop、云同步和视频处理。

## Review Focus

- 2048×2048 或更大的中文路径图片：应正常导入、预览、推理、保存和导出，不因路径编码失败。
- RTX 2060 显存不足：任务应失败为可读中文提示、释放 CUDA 缓存且不生成半成品图层；Task 6 集成测试固定此行为。
- 浏览器缩放与平移后的坐标：框、正负点和画笔必须准确映射到原图；Task 8 的前端单元测试固定转换公式。
- 项目保存中断或目录不可写：旧项目文件必须保持可打开；Task 2 的原子保存测试固定此行为。
- 同名类别、同名图层和 Windows 非法文件名：导出不得覆盖已有文件；Task 3 的命名测试固定此行为。

---

### Task 1: 应用骨架、依赖与领域模型

**Files:**
- Create: `map_cutout/__init__.py`
- Create: `map_cutout/config.py`
- Create: `map_cutout/domain.py`
- Create: `tests/map_cutout/test_domain.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: 无。
- Produces: `AppConfig`、`ProjectState`、`MapState`、`LayerState`、`FolderState`、`BoundingBox`、`ExportMode`，供所有后续任务使用。

- [ ] **Step 1: 写领域模型失败测试**

```python
from map_cutout.domain import LayerState, MapState


def test_map_assigns_next_class_name_without_overwriting():
    state = MapState.new("map-1", "D:/素材/庄园.png", 2048, 2048)
    state.layers.extend([
        LayerState.mask_layer("a", "chair1", "chair", "masks/a.png"),
        LayerState.mask_layer("b", "chair3", "chair", "masks/b.png"),
    ])

    assert state.next_layer_name("chair") == "chair4"


def test_original_layer_is_bottom_visible_and_locked():
    state = MapState.new("map-1", "D:/素材/庄园.png", 2048, 2048)

    original = state.layers[-1]
    assert original.kind == "original"
    assert original.visible is True
    assert original.locked is True
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_domain.py -v -p no:cacheprovider`

Expected: FAIL，包含 `ModuleNotFoundError: No module named 'map_cutout'`。

- [ ] **Step 3: 实现配置和模型**

```python
# map_cutout/domain.py
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ExportMode(str, Enum):
    TIGHT = "tight"
    FULL_SIZE = "full_size"


@dataclass(frozen=True)
class BoundingBox:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class LayerState:
    id: str
    name: str
    kind: str
    class_name: str | None = None
    mask_path: str | None = None
    visible: bool = True
    locked: bool = False
    folder_id: str | None = None

    @classmethod
    def mask_layer(cls, layer_id: str, name: str, class_name: str, mask_path: str):
        return cls(layer_id, name, "mask", class_name, mask_path)


@dataclass
class FolderState:
    id: str
    name: str
    visible: bool = True
    collapsed: bool = False


@dataclass
class MapState:
    id: str
    source_path: str
    width: int
    height: int
    layers: list[LayerState] = field(default_factory=list)
    folders: list[FolderState] = field(default_factory=list)
    prompt: str = ""
    threshold: float = 0.4

    @classmethod
    def new(cls, map_id: str, source_path: str, width: int, height: int):
        original = LayerState("original", "原始地图", "original", locked=True)
        return cls(map_id, source_path, width, height, layers=[original])

    def next_layer_name(self, class_name: str) -> str:
        prefix = class_name.strip().lower().replace(" ", "_") or "object"
        numbers = [int(layer.name[len(prefix):]) for layer in self.layers
                   if layer.name.startswith(prefix) and layer.name[len(prefix):].isdigit()]
        return f"{prefix}{max(numbers, default=0) + 1}"
```

`AppConfig` 从环境变量读取项目根目录、模型配置、权重路径、主机和端口；默认主机固定为 `127.0.0.1`。

- [ ] **Step 4: 在 `pyproject.toml` 添加 Web 依赖**

```toml
[project.optional-dependencies]
map-cutout-web = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "python-multipart>=0.0.12,<1",
]
```

Run: `uv pip install --python .venv\Scripts\python.exe -e ".[map-cutout-web]"`

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_domain.py -v -p no:cacheprovider`

Expected: 2 passed。

```bash
git add pyproject.toml map_cutout tests/map_cutout/test_domain.py
git commit -m "feat: add map cutout domain model"
```

### Task 2: 地图导入与项目原子保存

**Files:**
- Create: `map_cutout/project_store.py`
- Create: `tests/map_cutout/test_project_store.py`

**Interfaces:**
- Consumes: Task 1 的 `ProjectState`、`MapState`、`LayerState`。
- Produces: `ProjectStore.create()`、`import_image()`、`import_folder()`、`save()`、`load()`、`relocate_source()`。

- [ ] **Step 1: 写导入、中文路径和原子保存失败测试**

```python
def test_import_folder_sorts_supported_images_and_ignores_other_files(tmp_path):
    write_image(tmp_path / "地下祭坛.png")
    write_image(tmp_path / "布莱庄园.jpg")
    (tmp_path / "说明.txt").write_text("x", encoding="utf-8")
    project = ProjectStore.create(tmp_path / "项目")

    imported = project.import_folder(tmp_path)

    assert [Path(item.source_path).name for item in imported] == ["地下祭坛.png", "布莱庄园.jpg"]


def test_failed_save_keeps_previous_project_file(tmp_path, monkeypatch):
    store = ProjectStore.create(tmp_path / "项目")
    store.save()
    original = store.manifest_path.read_bytes()
    monkeypatch.setattr(Path, "replace", lambda *_: (_ for _ in ()).throw(PermissionError()))

    with pytest.raises(ProjectSaveError):
        store.save()

    assert store.manifest_path.read_bytes() == original
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_project_store.py -v -p no:cacheprovider`

Expected: FAIL，缺少 `ProjectStore`。

- [ ] **Step 3: 实现项目目录与序列化**

项目结构固定为：

```text
项目名/
├─ project.json
├─ masks/<map-id>/<layer-id>.png
├─ thumbnails/<map-id>.jpg
└─ exports/
```

使用 Pillow 打开图片获取尺寸和缩略图。`save()` 将 JSON 写入 `project.json.tmp`，刷新并关闭后用 `Path.replace()` 替换正式文件；异常时保留正式文件并把临时文件改名为 `project.recovery.json`。

- [ ] **Step 4: 实现源图重新定位**

```python
def relocate_source(self, map_id: str, new_path: Path) -> MapState:
    image = Image.open(new_path)
    state = self.state.map_by_id(map_id)
    if image.size != (state.width, state.height):
        raise SourceSizeMismatch(state.width, state.height, *image.size)
    state.source_path = str(new_path.resolve())
    self.dirty = True
    return state
```

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_project_store.py -v -p no:cacheprovider`

Expected: 全部通过。

```bash
git add map_cutout/project_store.py tests/map_cutout/test_project_store.py
git commit -m "feat: persist map cutout projects"
```

### Task 3: 蒙版运算、透明 PNG 与安全命名

**Files:**
- Create: `map_cutout/masks.py`
- Create: `map_cutout/exporter.py`
- Create: `tests/map_cutout/test_masks.py`
- Create: `tests/map_cutout/test_exporter.py`

**Interfaces:**
- Consumes: Task 1 的 `BoundingBox`、`ExportMode` 和图层模型。
- Produces: `union_masks()`、`paint_circle()`、`mask_bounds()`、`export_layer()`、`unique_windows_name()`。

- [ ] **Step 1: 写蒙版与两种导出模式失败测试**

```python
def test_paint_and_erase_are_clipped_to_image_bounds():
    mask = np.zeros((10, 10), dtype=np.uint8)
    painted = paint_circle(mask, x=0, y=0, radius=3, value=255)
    erased = paint_circle(painted, x=0, y=0, radius=1, value=0)
    assert painted.shape == (10, 10)
    assert painted[0, 0] == 255
    assert erased[0, 0] == 0


def test_tight_and_full_size_exports_have_expected_dimensions(tmp_path):
    image = rgba_image((10, 8))
    mask = rectangular_mask((10, 8), (2, 1, 7, 6))
    tight = export_layer(image, mask, tmp_path / "tight.png", ExportMode.TIGHT)
    full = export_layer(image, mask, tmp_path / "full.png", ExportMode.FULL_SIZE)
    assert Image.open(tight).size == (5, 5)
    assert Image.open(full).size == (10, 8)
    assert Image.open(full).getpixel((0, 0))[3] == 0


def test_illegal_and_duplicate_names_never_overwrite(tmp_path):
    first = unique_windows_name(tmp_path, "chair:1", ".png")
    first.touch()
    second = unique_windows_name(tmp_path, "chair:1", ".png")
    assert first.name == "chair_1.png"
    assert second.name == "chair_1_2.png"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_masks.py tests/map_cutout/test_exporter.py -v -p no:cacheprovider`

Expected: FAIL，导出函数不存在。

- [ ] **Step 3: 实现纯 NumPy 蒙版操作**

`union_masks` 使用 `np.maximum.reduce`；`paint_circle` 在局部切片上计算圆形布尔区域；`mask_bounds` 返回右边界和下边界为排他值的 `BoundingBox`，空蒙版抛出 `EmptyMaskError`。

- [ ] **Step 4: 实现 Pillow RGBA 导出**

```python
def export_layer(source: Image.Image, mask: np.ndarray, output: Path, mode: ExportMode) -> Path:
    rgba = source.convert("RGBA")
    alpha = Image.fromarray(mask.astype(np.uint8), mode="L")
    rgba.putalpha(alpha)
    if mode is ExportMode.TIGHT:
        box = mask_bounds(mask)
        rgba = rgba.crop((box.x1, box.y1, box.x2, box.y2))
    output.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(output, format="PNG")
    return output
```

文件名替换 `< > : " / \\ | ? *` 和控制字符，去掉末尾空格和句点，并保护 `CON`、`PRN`、`AUX`、`NUL`、`COM1` 至 `COM9`、`LPT1` 至 `LPT9`。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_masks.py tests/map_cutout/test_exporter.py -v -p no:cacheprovider`

Expected: 全部通过。

```bash
git add map_cutout/masks.py map_cutout/exporter.py tests/map_cutout/test_masks.py tests/map_cutout/test_exporter.py
git commit -m "feat: export transparent map layers"
```

### Task 4: 推理服务封装

**Files:**
- Create: `map_cutout/inference.py`
- Create: `tests/map_cutout/test_inference.py`
- Modify: `grounded_sam2_hf_model_demo.py`

**Interfaces:**
- Consumes: Task 1 的 `BoundingBox`，现有 SAM2 配置和权重。
- Produces: `InferenceService.detect(image, prompt, threshold)`、`segment_box(image, box)`、`segment_points(image, points, labels, box=None)`，返回 `DetectionResult`。

- [ ] **Step 1: 写提示词解析和结果规范化失败测试**

```python
def test_prompt_is_normalized_to_lowercase_period_terminated_phrases():
    assert normalize_prompt(" Chair, stone wall ; DOOR ") == "chair. stone wall. door."


def test_detection_masks_are_boolean_original_size():
    service = InferenceService(detector=fake_detector, segmenter=fake_segmenter)
    result = service.detect(test_image(64, 48), "chair.", 0.4)
    assert result[0].mask.dtype == np.bool_
    assert result[0].mask.shape == (48, 64)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_inference.py -v -p no:cacheprovider`

Expected: FAIL，`InferenceService` 不存在。

- [ ] **Step 3: 提取并实现延迟加载服务**

`InferenceService` 首次推理时加载模型并长期复用。Grounding DINO 使用 `box_threshold` 和 `text_threshold=0.3`；SAM2 Small 使用：

```text
checkpoints/sam2.1_hiera_small.pt
configs/sam2.1/sam2.1_hiera_s.yaml
```

`detect` 返回列表，每项包含类别、检测置信度、SAM 分数、边界框和布尔蒙版。无检测结果返回空列表而非异常。

- [ ] **Step 4: 将官方示例改为调用新服务**

保留示例命令兼容性，但把模型加载、提示词规范化和检测逻辑改为调用 `InferenceService`，避免 UI 与示例维护两套推理实现。

- [ ] **Step 5: 运行单元测试和真实模型冒烟测试**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_inference.py tests/test_hf_demo_processor_api.py -v -p no:cacheprovider`

Expected: 全部通过。

Run: `.venv\Scripts\python.exe -c "from PIL import Image; from map_cutout.inference import InferenceService; s=InferenceService.default(); print(len(s.detect(Image.open('notebooks/images/truck.jpg'), 'truck.', .4)))"`

Expected: 输出大于或等于 `1`。

- [ ] **Step 6: 提交**

```bash
git add map_cutout/inference.py grounded_sam2_hf_model_demo.py tests/map_cutout/test_inference.py tests/test_hf_demo_processor_api.py
git commit -m "refactor: expose reusable grounded sam inference"
```

### Task 5: 图层命令和撤销/重做

**Files:**
- Create: `map_cutout/commands.py`
- Create: `map_cutout/history.py`
- Create: `tests/map_cutout/test_history.py`
- Create: `tests/map_cutout/test_layer_commands.py`

**Interfaces:**
- Consumes: Task 1 领域模型和 Task 3 蒙版运算。
- Produces: `Command.execute()`、`Command.undo()`、`History.execute()`、`undo()`、`redo()`；图层创建、删除、重命名、显隐、锁定、移动、文件夹和合并命令。

- [ ] **Step 1: 写 50 步上限、地图隔离和合并行为失败测试**

```python
def test_history_keeps_only_latest_fifty_commands():
    history = History(limit=50)
    state = counter_state()
    for _ in range(55):
        history.execute(Increment(state))
    for _ in range(50):
        history.undo()
    assert state.value == 5


def test_histories_are_isolated_per_map():
    manager = HistoryManager(limit=50)
    manager.for_map("a").execute(Increment(counter_a))
    manager.for_map("b").execute(Increment(counter_b))
    manager.for_map("a").undo()
    assert counter_a.value == 0
    assert counter_b.value == 1


def test_merge_keeps_sources_and_hides_them(tmp_path):
    merged = MergeLayersCommand(map_state, ["a", "b"], mask_repo).execute()
    assert merged.visible is True
    assert map_state.layer("a").visible is False
    assert map_state.layer("b").visible is False
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_history.py tests/map_cutout/test_layer_commands.py -v -p no:cacheprovider`

Expected: FAIL，历史与命令类不存在。

- [ ] **Step 3: 实现命令协议和有限栈**

```python
class Command(Protocol):
    def execute(self) -> object: ...
    def undo(self) -> None: ...


class History:
    def execute(self, command: Command):
        result = command.execute()
        self._undo.append(command)
        self._undo = self._undo[-self.limit:]
        self._redo.clear()
        return result
```

每个命令记录精确的旧状态；删除和蒙版编辑在命令进入历史时保留恢复所需数据。蒙版快照使用压缩 PNG 字节，避免保存完整 Python 对象图。

- [ ] **Step 4: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_history.py tests/map_cutout/test_layer_commands.py -v -p no:cacheprovider`

Expected: 全部通过。

```bash
git add map_cutout/commands.py map_cutout/history.py tests/map_cutout/test_history.py tests/map_cutout/test_layer_commands.py
git commit -m "feat: add undoable layer editing"
```

### Task 6: FastAPI、本地任务与错误翻译

**Files:**
- Create: `map_cutout/web_app.py`
- Create: `map_cutout/jobs.py`
- Create: `map_cutout/errors.py`
- Create: `tests/map_cutout/test_api.py`
- Create: `tests/map_cutout/test_jobs.py`

**Interfaces:**
- Consumes: Tasks 1–5 的配置、存储、推理、命令和导出。
- Produces: `create_app(config, services)`；`JobManager.submit()`、`status()`、`cancel()`；`/api/*` REST 接口。

- [ ] **Step 1: 写 API 与 CUDA 内存错误失败测试**

```python
def test_app_rejects_non_loopback_host():
    with pytest.raises(ValueError, match="仅允许本机"):
        create_app(AppConfig(host="0.0.0.0"), fake_services())


def test_cuda_oom_becomes_chinese_failed_job_without_layers(client, monkeypatch):
    monkeypatch.setattr(fake_inference, "detect", raise_cuda_oom)
    before = client.get("/api/maps/map-1/layers").json()
    job_id = client.post("/api/maps/map-1/detect", json={"prompt": "wall.", "threshold": .4}).json()["job_id"]
    wait_for_job(client, job_id)
    job = client.get(f"/api/jobs/{job_id}").json()
    after = client.get("/api/maps/map-1/layers").json()
    assert job["state"] == "failed"
    assert "显存不足" in job["message"]
    assert after == before
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_api.py tests/map_cutout/test_jobs.py -v -p no:cacheprovider`

Expected: FAIL，应用工厂不存在。

- [ ] **Step 3: 实现 API 路由**

提供以下端点：

```text
POST /api/projects/new
POST /api/projects/open
POST /api/projects/save
POST /api/import/image
POST /api/import/folder
GET  /api/maps
GET  /api/maps/{map_id}/image
GET  /api/maps/{map_id}/layers
POST /api/maps/{map_id}/detect
POST /api/maps/{map_id}/segment
PATCH/DELETE /api/maps/{map_id}/layers/{layer_id}
POST /api/maps/{map_id}/layers/merge
POST /api/maps/{map_id}/folders
POST /api/maps/{map_id}/undo
POST /api/maps/{map_id}/redo
POST /api/export
GET  /api/jobs/{job_id}
DELETE /api/jobs/{job_id}
```

- [ ] **Step 4: 实现后台任务和错误映射**

推理任务在单工作线程执行，避免同时占满显存。捕获 `torch.cuda.OutOfMemoryError` 后执行 `torch.cuda.empty_cache()`，任务状态设为 `failed`，返回中文消息和降低处理尺寸建议。只有推理完整成功后才用一个命令批量加入图层。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_api.py tests/map_cutout/test_jobs.py -v -p no:cacheprovider`

Expected: 全部通过。

```bash
git add map_cutout/web_app.py map_cutout/jobs.py map_cutout/errors.py tests/map_cutout/test_api.py tests/map_cutout/test_jobs.py
git commit -m "feat: add local map cutout API"
```

### Task 7: 三栏中文界面和状态管理

**Files:**
- Create: `map_cutout/static/index.html`
- Create: `map_cutout/static/styles.css`
- Create: `map_cutout/static/app.js`
- Create: `map_cutout/static/state.js`
- Create: `tests/web/state.test.html`
- Modify: `map_cutout/web_app.py`

**Interfaces:**
- Consumes: Task 6 REST API。
- Produces: `AppState`、三栏布局、工具栏、地图列表、空画布和图层面板容器。

- [ ] **Step 1: 写浏览器状态失败测试页面**

`tests/web/state.test.html` 加载 `state.js`，验证：原始图层始终排在底部；设置 dirty 后 `beforeunload` 返回提示；保存成功后 dirty 清除。测试页面将结果写入 `document.title` 为 `PASS` 或错误信息，供 Playwright 或人工浏览器验证。

- [ ] **Step 2: 用静态测试服务器确认测试失败**

Run: `.venv\Scripts\python.exe -m uvicorn map_cutout.web_app:create_test_app --factory --host 127.0.0.1 --port 7861`

Expected: 打开 `http://127.0.0.1:7861/tests/web/state.test.html` 时标题不是 `PASS`，因为 `AppState` 尚不存在。

- [ ] **Step 3: 实现 AppState 和 API 客户端**

```javascript
export class AppState extends EventTarget {
  constructor(api) {
    super();
    this.api = api;
    this.maps = [];
    this.currentMapId = null;
    this.selectedLayerIds = new Set();
    this.dirty = false;
  }
  setDirty(value) {
    this.dirty = value;
    this.dispatchEvent(new CustomEvent("change"));
  }
}
```

所有页面数据改变通过 `AppState` 触发渲染，不在零散点击处理器中直接维护重复状态。

- [ ] **Step 4: 实现三栏 HTML/CSS**

顶部工具栏固定；左栏宽 220px，右栏宽 300px，中间画布填满剩余空间；底部工具条固定。小于 1100px 时左右栏允许折叠，但不改成移动端布局。

- [ ] **Step 5: 运行页面测试并提交**

Expected: 状态测试页面标题为 `PASS`；主页面三栏可见，中文标签无乱码。

```bash
git add map_cutout/static map_cutout/web_app.py tests/web/state.test.html
git commit -m "feat: add three-column Chinese web interface"
```

### Task 8: Canvas 坐标、缩放平移与蒙版编辑

**Files:**
- Create: `map_cutout/static/canvas_editor.js`
- Create: `tests/web/canvas_editor.test.html`
- Modify: `map_cutout/static/app.js`
- Modify: `map_cutout/static/styles.css`

**Interfaces:**
- Consumes: Task 7 `AppState`，Task 6 的图片、分割和图层 API。
- Produces: `CanvasEditor`、`screenToImage()`、`imageToScreen()`、框/点/画笔事件和蒙版叠加渲染。

- [ ] **Step 1: 写坐标变换失败测试**

```javascript
const view = { scale: 0.5, offsetX: 100, offsetY: 40 };
assertDeepEqual(screenToImage(150, 90, view), { x: 100, y: 100 });
assertDeepEqual(imageToScreen(100, 100, view), { x: 150, y: 90 });
const roundTrip = screenToImage(...Object.values(imageToScreen(733, 1201, view)), view);
assertNear(roundTrip.x, 733);
assertNear(roundTrip.y, 1201);
```

- [ ] **Step 2: 打开测试页并确认失败**

Expected: 标题不是 `PASS`，缺少坐标函数。

- [ ] **Step 3: 实现画布渲染和输入模式**

Canvas 内部尺寸使用设备像素比，逻辑坐标使用 CSS 像素。滚轮以鼠标所在图片点为中心缩放；空格加拖动平移。框选在鼠标抬起时提交原图坐标；正负点分别以绿色加号和红色减号显示。

- [ ] **Step 4: 实现画笔与橡皮擦采样**

指针移动点转换为原图坐标，按原图半径插值连线，形成一条 stroke 后一次提交后端命令。每个 stroke 只产生一个撤销步骤。锁定图层时编辑工具禁用并显示提示。

- [ ] **Step 5: 验证坐标和人工画布行为并提交**

Expected: 测试页标题为 `PASS`；在 25%、100%、300% 缩放下点击相同图片特征，提交的原图坐标误差不超过 1 像素。

```bash
git add map_cutout/static/canvas_editor.js map_cutout/static/app.js map_cutout/static/styles.css tests/web/canvas_editor.test.html
git commit -m "feat: add interactive mask canvas"
```

### Task 9: 图层树、文件夹和快捷键

**Files:**
- Create: `map_cutout/static/layer_tree.js`
- Create: `tests/web/layer_tree.test.html`
- Modify: `map_cutout/static/app.js`
- Modify: `map_cutout/static/styles.css`

**Interfaces:**
- Consumes: Task 7 `AppState` 和 Task 6 图层/文件夹/历史 API。
- Produces: `LayerTree`、多选、拖动排序、显隐、右侧锁定按钮、文件夹和合并 UI。

- [ ] **Step 1: 写图层顺序和交互失败测试**

测试构造 `chair1`、隐藏的 `door1`、一个家具文件夹和锁定的原始图层，断言：眼睛按钮在名称左侧；锁按钮在行最右侧；原始地图最后；Shift 点击多选；文件夹显隐影响子图层显示但不删除子图层自身状态。

- [ ] **Step 2: 打开测试页并确认失败**

Expected: 标题不是 `PASS`，缺少 `LayerTree`。

- [ ] **Step 3: 实现图层树和文件夹操作**

HTML 行结构固定为：

```html
<div class="layer-row" draggable="true">
  <button class="visibility"></button>
  <span class="layer-name"></span>
  <button class="lock"></button>
</div>
```

拖放完成才调用后端命令；拖动中仅显示目标位置。删除非空文件夹弹出两项选择，不提供含糊的默认确认。

- [ ] **Step 4: 连接快捷键**

`Ctrl+S` 阻止浏览器保存页面并调用项目保存；`Ctrl+Z` 调用当前地图撤销；`Ctrl+Y` 和 `Ctrl+Shift+Z` 调用重做。输入框聚焦时只拦截保存和撤销，不拦截普通文本编辑快捷键。

- [ ] **Step 5: 验证并提交**

Expected: 图层树测试页面标题为 `PASS`；锁按钮位于右侧；隐藏、文件夹、拖动和合并调用正确 API。

```bash
git add map_cutout/static/layer_tree.js map_cutout/static/app.js map_cutout/static/styles.css tests/web/layer_tree.test.html
git commit -m "feat: add layer and folder management"
```

### Task 10: 自动识别、手动分割与进度反馈

**Files:**
- Create: `map_cutout/static/inference_controls.js`
- Modify: `map_cutout/static/app.js`
- Modify: `map_cutout/static/index.html`
- Create: `tests/map_cutout/test_detection_workflow.py`

**Interfaces:**
- Consumes: Task 4 推理、Task 5 命令、Task 6 任务 API、Task 8 Canvas。
- Produces: 自动检测表单、任务进度、框/点确认流程和新图层自动命名。

- [ ] **Step 1: 写检测结果全部入层和连续命名失败测试**

```python
def test_all_detection_results_become_separate_layers_in_one_history_step(workflow):
    workflow.detect_result = [detection("chair"), detection("chair"), detection("door")]
    created = workflow.apply_detection("map-1", "chair. door.", 0.4)
    assert [layer.name for layer in created] == ["chair1", "chair2", "door1"]
    workflow.undo("map-1")
    assert workflow.mask_layers("map-1") == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_detection_workflow.py -v -p no:cacheprovider`

Expected: FAIL，工作流不存在。

- [ ] **Step 3: 实现自动识别控件**

提示词输入区显示短语示例；阈值范围 `0.05` 到 `0.90`、步长 `0.05`、默认 `0.40`。任务开始后显示“加载模型/检测/生成蒙版/建立图层”阶段。成功后刷新图层树并将新增图层高亮。

- [ ] **Step 4: 实现框和正负点工作流**

框选或添加点后，“生成蒙版”按钮调用 `/segment`；响应先作为临时预览，用户点击“建立图层”后才写入项目。取消只清除临时提示和预览。手动类别为空时使用 `object` 连续命名。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_detection_workflow.py -v -p no:cacheprovider`

Expected: 全部通过。

```bash
git add map_cutout/static/inference_controls.js map_cutout/static/app.js map_cutout/static/index.html tests/map_cutout/test_detection_workflow.py
git commit -m "feat: connect automatic and manual segmentation"
```

### Task 11: 导出对话框与批量导出

**Files:**
- Create: `map_cutout/static/export_dialog.js`
- Modify: `map_cutout/exporter.py`
- Modify: `map_cutout/static/app.js`
- Create: `tests/map_cutout/test_batch_export.py`

**Interfaces:**
- Consumes: Task 3 导出函数、Task 6 任务 API、Task 9 当前选择和文件夹树。
- Produces: `BatchExporter.export(request)` 和完整导出对话框。

- [ ] **Step 1: 写范围、隐藏图层和文件夹映射失败测试**

```python
def test_visible_scope_skips_hidden_but_all_scope_includes_it(export_fixture):
    visible = export_fixture.export(scope="visible", mode="full_size")
    all_layers = export_fixture.export(scope="all", mode="full_size")
    assert names(visible) == {"chair1.png", "原始地图.png"}
    assert names(all_layers) == {"chair1.png", "door1.png", "原始地图.png"}


def test_folder_structure_is_optional(export_fixture):
    nested = export_fixture.export(scope="map", preserve_folders=True)
    flat = export_fixture.export(scope="map", preserve_folders=False)
    assert any(path.parent.name == "家具" for path in nested)
    assert all(path.parent.name != "家具" for path in flat)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_batch_export.py -v -p no:cacheprovider`

Expected: FAIL，`BatchExporter` 不存在。

- [ ] **Step 3: 实现批量导出服务**

请求包含 `scope`、`map_ids`、`layer_ids`、`mode`、`include_hidden`、`preserve_folders` 和 `output_dir`。原始地图按源文件复制；若目标格式必须统一为 PNG，则用 Pillow 保存无损 PNG。每个失败图层记录原因，其他图层继续导出。

- [ ] **Step 4: 实现中文导出对话框**

对话框根据当前选择提供单图层、多选、当前文件夹、当前地图可见、当前地图全部、整个项目六种范围。尺寸提供“紧凑裁剪”和“保持原图尺寸”。提交后显示文件数量、输出目录、跳过项和失败项。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_exporter.py tests/map_cutout/test_batch_export.py -v -p no:cacheprovider`

Expected: 全部通过。

```bash
git add map_cutout/exporter.py map_cutout/static/export_dialog.js map_cutout/static/app.js tests/map_cutout/test_batch_export.py
git commit -m "feat: add batch transparent PNG export"
```

### Task 12: Windows 启动器、关闭保护与端到端验收

**Files:**
- Create: `map_cutout/launcher.py`
- Create: `启动工具.bat`
- Create: `tests/map_cutout/test_launcher.py`
- Create: `docs/map-cutout-user-guide.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 6 `create_app()` 和全部静态资源。
- Produces: 双击启动入口、浏览器自动打开、单实例保护和用户说明。

- [ ] **Step 1: 写端口选择和项目内 Python 路径失败测试**

```python
def test_launcher_uses_loopback_and_next_free_port(monkeypatch):
    monkeypatch.setattr(socket, "bind", fail_once_then_succeed)
    host, port = choose_address(7860, 10)
    assert host == "127.0.0.1"
    assert port == 7861


def test_batch_file_uses_project_local_python():
    text = Path("启动工具.bat").read_text(encoding="utf-8")
    assert r".venv\Scripts\python.exe" in text
    assert "%APPDATA%" not in text
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout/test_launcher.py -v -p no:cacheprovider`

Expected: FAIL，启动器不存在。

- [ ] **Step 3: 实现启动器**

`启动工具.bat` 切换到脚本所在目录，验证 `.venv\Scripts\python.exe`、SAM2 权重和项目内 `.python`，然后运行 `python -m map_cutout.launcher`。启动器选择 7860 起的第一个空闲端口，启动 Uvicorn 后调用 `webbrowser.open()`。所有启动失败以中文说明并保持窗口开启。

- [ ] **Step 4: 编写用户指南**

指南按实际界面说明：双击启动、创建项目、导入文件夹、提示词、阈值、框/点、画笔、图层文件夹、保存、撤销和两种导出模式。README 顶部增加“本地地图抠图工具”入口，保留上游项目说明。

- [ ] **Step 5: 运行完整自动化验证**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout tests/test_hf_demo_processor_api.py -v -p no:cacheprovider`

Expected: 0 failed。

Run: `.venv\Scripts\python.exe -m map_cutout.launcher --no-browser --port 7860`

Expected: 日志显示仅监听 `http://127.0.0.1:7860`；访问 `/api/health` 返回 `{"status":"ok","cuda":true}`。

- [ ] **Step 6: 使用真实地图人工验收**

使用“布莱庄园”和“地下祭坛”逐项验证规格的人工验收清单。至少完成一次文字识别、一次框加正负点、一次画笔修正、一次文件夹整理、一次撤销/重做、一次项目保存重开，以及两种尺寸的整套导出。

- [ ] **Step 7: 提交**

```bash
git add map_cutout/launcher.py "启动工具.bat" tests/map_cutout/test_launcher.py docs/map-cutout-user-guide.md README.md
git commit -m "feat: ship local map cutout tool"
```

### Task 13: 最终回归与交付检查

**Files:**
- Modify: 仅限回归发现的直接缺陷对应文件。
- Test: 全部 `tests/map_cutout/`、`tests/web/` 和现有兼容性测试。

**Interfaces:**
- Consumes: Tasks 1–12 的完整工具。
- Produces: 可交付的主分支状态和验证记录。

- [ ] **Step 1: 运行 Python 完整测试**

Run: `.venv\Scripts\python.exe -m pytest tests/map_cutout tests/test_hf_demo_processor_api.py -v -p no:cacheprovider`

Expected: 0 failed、0 errors。

- [ ] **Step 2: 运行 Web 静态测试**

启动本地服务并依次打开：

```text
/tests/web/state.test.html
/tests/web/canvas_editor.test.html
/tests/web/layer_tree.test.html
```

Expected: 三个页面标题均为 `PASS`。

- [ ] **Step 3: 检查 Git 差异与敏感/大文件**

Run: `git status --short && git diff --check && git ls-files | findstr /i ".pt .pth .venv .python outputs"`

Expected: 不跟踪模型权重、虚拟环境、本地 Python、用户项目或输出图片；`git diff --check` 无错误。

- [ ] **Step 4: 执行真实用户流程**

双击 `启动工具.bat`，在全新项目中导入 `D:\06\剧本\图像资源\地图ing`，完成一次检测、修正、保存、重开和批量导出。确认原始地图未修改，并在输出目录检查透明通道和尺寸。

- [ ] **Step 5: 提交直接回归修复并记录结果**

只有存在回归修复时才建立提交，提交信息使用：

```bash
git commit -m "fix: resolve map cutout acceptance issues"
```

在最终交付消息中报告测试数量、真实地图验收结果、启动文件位置、用户指南位置和任何仍存在的模型识别限制。
