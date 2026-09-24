# 地图抠图工具：Cursor 开发交接文档

## 1. 项目定位

这是一个运行在 Windows 本机的 2D 游戏地图素材识别、分割、人工修整和透明 PNG 导出工具。

用户的原始地图主要位于：

```text
D:\06\剧本\图像资源\地图ing
```

代码仓库位于：

```text
D:\06\剧本\地图抠图\Grounded-SAM-2
```

默认项目保存根目录位于：

```text
D:\06\剧本\地图抠图\项目输出
```

项目最初 fork 自 IDEA-Research/Grounded-SAM-2，当前自定义工具代码公开在：

```text
https://github.com/c3489513453-commits/2D-Map-Occlusion-Editor
```

本工具当前只负责生成和导出分离后的透明素材，不负责游戏中的人物遮挡逻辑。后续游戏侧会通过素材最低线等方式处理遮挡关系。

## 2. 最终目标

目标是让非技术用户可以批量导入 AI 生成的 2D 地图，并完成以下工作：

1. 使用英文提示词识别建筑、门、墙、桌椅等物体。
2. 使用 Grounding DINO 找到目标，使用 SAM 2 生成精细蒙版。
3. 每一个识别结果分别成为独立图层，例如 `chair1`、`chair2`。
4. 自动识别不理想时，可以用框选、正点、负点帮助 SAM 2 分割。
5. 已生成图层可以继续用画笔、橡皮、套索增加和套索减去进行人工修整。
6. 图层可以显示、隐藏、锁定、删除、排序、合并和放入自建文件夹。
7. 原始地图也必须作为底图图层保留，并能与其他图层一起导出。
8. 导出两种透明 PNG：
   - 紧凑裁剪：只输出素材实际占用范围。
   - 原图尺寸：画布大小与地图完全相同，素材以外区域透明，便于后续自动叠加。
9. 支持单图层、当前地图或整个项目批量导出。
10. 支持 `Ctrl+S` 保存、`Ctrl+Z` 撤销、`Ctrl+Y`/`Ctrl+Shift+Z` 重做。

## 3. 用户使用入口

普通用户不需要手动输入 PowerShell 命令。唯一推荐入口是双击：

```text
D:\06\剧本\地图抠图\Grounded-SAM-2\启动工具.bat
```

启动后会自动选择 `127.0.0.1:7860` 开始的可用端口，并在默认浏览器打开页面。终端窗口必须保持开启；关闭终端窗口会停止服务。

如果浏览器仍显示旧代码，先按 `Ctrl+F5` 强制刷新。前端使用原生 ES Module，浏览器可能缓存旧的 JavaScript 文件。

## 4. 当前功能状态

当前已经实现：

- 导入单张 PNG/JPG/JPEG。
- 导入文件夹中的多张图片。
- Grounding DINO 文本识别。
- SAM 2 自动分割。
- 框选分割、正点/负点分割。
- 自动识别结果分别建立图层。
- 画笔增加、橡皮擦减去蒙版。
- 套索增加、套索减去蒙版；鼠标松开时自动闭合区域。
- 图层显示、隐藏、锁定、删除、拖动排序、多选及合并。
- 图层文件夹。
- 原始地图底图。
- 撤销和重做，历史上限为 50 步。
- 项目保存和打开。
- 两种透明 PNG 尺寸模式及批量导出。
- CUDA 显存不足时转换为中文错误提示。
- 服务只允许绑定本机回环地址，避免把本地文件暴露到局域网。

截至交接时最新提交：

```text
3ce2df7 feat: add lasso mask editing
```

完整测试结果为 `35 passed`。

## 5. 技术结构

### 后端

- Python 3.10
- FastAPI + Uvicorn
- PyTorch/CUDA
- Hugging Face Transformers 中的 Grounding DINO Tiny
- SAM 2.1 Hiera Small
- Pillow + NumPy 处理蒙版和透明 PNG

核心文件：

| 文件 | 职责 |
| --- | --- |
| `map_cutout/config.py` | 默认路径、模型、主机和端口配置 |
| `map_cutout/launcher.py` | 选择可用端口、打开浏览器、启动 Uvicorn |
| `map_cutout/web_app.py` | FastAPI 路由、识别/分割任务、图层编辑 API |
| `map_cutout/inference.py` | Grounding DINO 与 SAM 2 推理封装 |
| `map_cutout/project_store.py` | 创建、加载、保存项目及导入地图 |
| `map_cutout/domain.py` | 项目、地图、图层、文件夹等数据结构 |
| `map_cutout/commands.py` | 可撤销的图层命令 |
| `map_cutout/history.py` | 撤销/重做历史 |
| `map_cutout/masks.py` | 蒙版合并、画笔、套索、边界计算 |
| `map_cutout/exporter.py` | 透明 PNG 与批量导出 |
| `map_cutout/jobs.py` | 后台识别任务状态管理 |

### 前端

前端没有 React/Vue，也没有 npm 构建步骤，是 FastAPI 直接提供的原生 HTML、CSS 和 JavaScript。

| 文件 | 职责 |
| --- | --- |
| `map_cutout/static/index.html` | 三栏主界面和操作入口 |
| `map_cutout/static/app.js` | 页面总装、事件绑定、保存/撤销/合并等操作 |
| `map_cutout/static/state.js` | 浏览器端状态和 API 客户端 |
| `map_cutout/static/canvas_editor.js` | 缩放、框选、点击、画笔、橡皮、套索及蒙版叠加显示 |
| `map_cutout/static/inference_controls.js` | 自动识别、手动分割预览、蒙版编辑 |
| `map_cutout/static/layer_tree.js` | 图层树、显隐、锁定、删除、排序、文件夹 |
| `map_cutout/static/export_dialog.js` | 导出窗口与请求 |
| `map_cutout/static/styles.css` | 界面样式 |

## 6. 模型和运行环境

本机环境不是 Git 仓库的一部分，不要删除或重新创建，除非确实需要修复：

```text
.python\                       项目自带的 Python 3.10 运行时
.venv\                         已安装依赖的虚拟环境
checkpoints\sam2.1_hiera_small.pt
```

SAM 2 权重约 184 MB，已被 `.gitignore` 忽略，不会上传 GitHub。Grounding DINO 模型由 Hugging Face 缓存提供。离线使用前必须确保模型已经缓存到本机；不要把大型权重、Hugging Face 缓存或 `.venv` 提交到 Git。

默认配置可以通过以下环境变量覆盖：

```text
MAP_CUTOUT_PROJECT_ROOT
MAP_CUTOUT_SAM_CHECKPOINT
MAP_CUTOUT_SAM_CONFIG
MAP_CUTOUT_GROUNDING_MODEL
MAP_CUTOUT_HOST
MAP_CUTOUT_PORT
```

默认 SAM 配置是 `configs/sam2.1/sam2.1_hiera_s.yaml`，默认权重是 `checkpoints/sam2.1_hiera_small.pt`，默认 Grounding DINO 模型是 `IDEA-Research/grounding-dino-tiny`。

## 7. 项目数据和输出位置

新建项目时，用户可以自己选择位置。若没有切换项目，默认会在下面创建“未命名项目”：

```text
D:\06\剧本\地图抠图\项目输出\未命名项目
```

每个项目目录结构如下：

```text
项目目录\
├─ project.json               项目清单、源图绝对路径、地图和图层信息
├─ masks\                     黑白蒙版 PNG
│  ├─ <map_id>\
│  │  ├─ <layer_id>.png
│  │  └─ ...
│  └─ preview-<id>.png        尚未确认的临时预览，确认或取消后删除
├─ thumbnails\               地图缩略图
└─ exports\                  默认导出位置
```

重要：`project.json` 保存的是原始地图的绝对路径，而不是复制源图。因此不要随意移动、改名或删除 `D:\06\剧本\图像资源\地图ing` 中已经导入的图片。`ProjectStore.relocate_source()` 已具备重新定位且校验尺寸的底层能力，但当前界面还没有暴露该功能。

导出时如果“输出文件夹”留空，文件写入当前项目的 `exports`。如果用户在界面中选择其他目录，则以用户选择为准。

## 8. 关键工作流

### 自动识别

1. 输入英文短语，并用句点分隔，例如：`chair. wooden door. stone wall.`
2. Grounding DINO 输出检测框和类别。
3. SAM 2 根据检测框生成蒙版。
4. 每个结果分别保存为蒙版文件，并建立独立图层。

短而具体的名词短语通常比长段落更有效。阈值默认 `0.40`；漏检时降低，误检时提高。

### 手动分割

框选或正负点只是给 SAM 2 提示。用户必须先“生成蒙版”，检查预览，再点击“建立图层”。尚未点击“建立图层”的内容只是临时预览，不是正式图层。

### 人工修整

画笔、橡皮、套索增加和套索减去都要求右侧恰好选中一个未锁定的正式蒙版图层。它们直接改写该图层的黑白蒙版，每一次连续操作都会进入撤销历史。

### 导出

导出使用原始地图 RGB 像素，并把蒙版写入 Alpha 通道。原始底图按普通 PNG 导出；蒙版图层导出为透明 PNG。Windows 非法文件名和重名会自动处理。

## 9. 测试和验证

在项目根目录运行完整测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/map_cutout tests/test_hf_demo_processor_api.py -q -p no:cacheprovider --basetemp "D:\06\剧本\地图抠图\项目输出\pytest-cursor"
```

如果上一次测试残留目录导致权限问题，换一个新的 `--basetemp` 目录名称即可。

浏览器端有两个轻量测试页面。先启动测试服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn map_cutout.web_app:create_test_app --factory --host 127.0.0.1 --port 7875
```

然后访问：

```text
http://127.0.0.1:7875/tests/web/canvas_editor.test.html
http://127.0.0.1:7875/tests/web/layer_tree.test.html
```

页面标题显示 `PASS` 才算通过。修改任何蒙版、图层、导出或项目保存逻辑后，都应重新跑完整 Python 测试和相关浏览器测试。

## 10. Git 和 GitHub 约定

当前分支是 `main`。远程仓库：

```text
origin     https://github.com/IDEA-Research/Grounded-SAM-2.git
user-fork  https://github.com/c3489513453-commits/2D-Map-Occlusion-Editor.git
```

- `origin` 是上游开源项目，主要用于参考或同步，不要把本项目改动推送到这里。
- 用户公开仓库是 `user-fork`，应推送到 `user-fork/main`。
- 推送命令：`git push user-fork main`。
- 提交前先运行测试、`git diff --check` 和 `git status --short`。
- 工作区可能包含用户自己的修改，不要使用 `git reset --hard`、`git checkout --` 等破坏性命令。
- `.gitignore` 中存在较宽的 `*test*` 规则。已有测试文件仍被 Git 跟踪，但新增测试文件可能被忽略；需要新增时使用 `git add -f <测试文件>`，或者谨慎收窄该忽略规则。

## 11. 开发时必须注意

1. 面向用户的文案应使用中文，用户是技术初学者。
2. 保留“双击 `启动工具.bat` 即可使用”的体验，不要要求用户日常输入复杂命令。
3. 保持纯本地运行，默认只允许 `127.0.0.1`，不要未经确认改为 `0.0.0.0`。
4. 不要把源地图、项目输出、模型权重、虚拟环境或用户隐私文件提交到 GitHub。
5. 原始地图图层不能删除或作为蒙版编辑；锁按钮始终位于图层行最右侧。
6. 正式蒙版图层无论来自自动识别、框选还是点选，都应拥有相同的删除和人工编辑能力。
7. 蒙版文件是灰度 PNG：黑色为透明区，白色为保留区。前端叠加显示时必须用亮度生成透明度，不能直接把黑色背景当作不透明区域。
8. 修改蒙版后必须同时清除 `CanvasEditor.maskImages` 和 `CanvasEditor.maskOverlays` 对应缓存，否则界面会继续显示旧蒙版。
9. 图层删除、合并、编辑等操作应继续接入撤销/重做体系。
10. 工具不会自动保存；不要悄悄改变这一行为，除非同步设计清晰的自动保存和异常恢复方案。
11. 推理是耗时任务，应继续通过 `JobManager` 后台执行，避免阻塞页面请求。
12. 注意 GPU 显存。当前使用 SAM 2.1 Small 和 Grounding DINO Tiny，就是为了在准确率和本机显存之间取得平衡。

## 12. 已知限制和后续可改进项

- 墙体、地面等大范围且语义不明确的结构，Grounding DINO 可能漏检；通常需要框选、点选或人工套索修正。
- 当前没有模型微调/训练界面。短期优先改善提示词、阈值、手动分割和修整体验，不建议直接训练模型。
- `project.json` 使用源图绝对路径；可以给 `relocate_source()` 增加界面入口。
- 前端资源可能被浏览器缓存；可考虑为静态资源增加版本号或开发环境禁用缓存。
- 当前前端是紧凑的原生 JavaScript，部分文件使用较长单行。新增复杂功能时可以逐步拆分模块，但不要一次性重写整个前端。
- 目前没有真正的安装包或桌面快捷方式，依赖本机 `.python`、`.venv` 和模型权重。
- 批量自动识别流程仍可以增强，例如给不同类别保存提示词模板、阈值预设和批处理队列。

## 13. 给 Cursor 的建议起始提示

可以在 Cursor 中打开：

```text
D:\06\剧本\地图抠图\Grounded-SAM-2
```

然后发送类似下面的提示：

> 请先完整阅读 `docs/CURSOR_HANDOFF.md`、README 顶部的本地工具说明，以及与本次任务相关的代码和测试。这个项目是 Windows 本地运行的 2D 地图识别、蒙版修整和透明 PNG 导出工具。请保留中文界面、双击 `启动工具.bat` 的入口、本地回环地址限制、现有项目数据格式和撤销体系。修改前先确认工作区状态；修改后运行交接文档中的完整测试及相关浏览器测试。不要提交模型权重、虚拟环境、地图素材或项目输出；需要推送时使用 `user-fork/main`，不要推送到上游 `origin`。

每次让 Cursor 开发新功能时，最好再补充：具体操作步骤、期望结果、当前错误截图，以及是否允许它提交并推送 GitHub。
