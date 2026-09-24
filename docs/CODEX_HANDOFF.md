# 地图抠图工具：交给 Codex 的交接文档

写于 2026-09-22。读者是接手这份代码的 Codex。

上一份基线文档是 `docs/CURSOR_HANDOFF.md`，对应提交 `e96e629`，当时最新功能提交是 `3ce2df7`（套索编辑）。那份文档里的项目定位、目录、模型、导出和 Git 约定仍然有效。本文说明那之后到现在实际发生的事，以及当前工作区里还没提交的行为。若两份文档冲突，以本文和当前代码为准。

## 1. 现在代码在哪

仓库：

```text
D:\06\剧本\地图抠图\Grounded-SAM-2
```

分支：`main`。

远程：

```text
origin     https://github.com/IDEA-Research/Grounded-SAM-2.git
user-fork  https://github.com/c3489513453-commits/2D-Map-Occlusion-Editor.git
```

`origin` 是上游开源项目，不要推送。用户的仓库是 `user-fork`。需要推送时只用 `git push user-fork HEAD:main`，并且先得到用户明确同意。上一次准备推送 `7e953c1` 时，用户跳过了批准，所以那个提交目前只在本机。

当前 Git 状态（写本文时）：

```text
user-fork/main  = eaad6d5
本地 main       = 7e953c1   （比 user-fork 超前 1 个提交，尚未推送）
工作区          = 在 7e953c1 之上还有大量未提交修改
```

未提交文件：

```text
map_cutout/history.py
map_cutout/masks.py
map_cutout/web_app.py
map_cutout/static/app.js
map_cutout/static/canvas_editor.js
map_cutout/static/index.html
map_cutout/static/inference_controls.js
map_cutout/static/layer_tree.js
map_cutout/static/styles.css
tests/map_cutout/test_api.py
tests/map_cutout/test_detection_workflow.py
tests/map_cutout/test_masks.py
tests/web/canvas_editor.test.html
tests/web/layer_tree.test.html
```

不要 `git reset`、`git checkout --` 或其它会丢掉工作区的命令。用户没有要求把这批改动提交或推送。另有一个旧工作树 `.worktrees/map-cutout-tool`，停在 `fc90144`，不要动它。

用户入口仍然是双击 `启动工具.bat`。后端改动后必须重新打开这个 bat；只改了前端时，用 `Ctrl+F5` 强制刷新。界面文案用中文。不要自动保存。不要训练模型。模型保持 SAM 2.1 Hiera Small 和 Grounding DINO Tiny。

## 2. 从项目开始到上一份交接，已经有什么

这些内容在 `docs/CURSOR_HANDOFF.md` 里写得更细，这里只保留继续开发必须知道的结果。

这是 Windows 本机的 2D 地图抠图工具，从 IDEA-Research/Grounded-SAM-2 fork 出来。用户导入地图后，用英文提示词做自动识别，或用框选、正点、负点让 SAM 2 分割，再把每个结果做成独立蒙版图层。图层可以显示、隐藏、锁定、删除、排序、合并、放进文件夹。底图图层不能删除，也不能当蒙版改。导出透明 PNG，有紧凑裁剪和原图尺寸两种。撤销和重做最多 50 步。服务只绑定 `127.0.0.1`。

蒙版文件是灰度 PNG：黑是不要的地方，白是留下的地方。保存时任何大于 0 的像素都写成 255，避免 `1 * 255` 溢出后变成几乎看不见。前端叠加时用亮度做透明度，不能把黑底当成不透明。

默认项目在 `D:\06\剧本\地图抠图\项目输出\未命名项目`。`project.json` 记的是源图绝对路径，不复制原图。用户的地图多在 `D:\06\剧本\图像资源\地图ing`。删地图时不能删源文件。

## 3. 上一份交接之后，已经提交的修复

这些提交在本地 `main` 上。除最后一条外，已经在 `user-fork/main`。

### 套索可以接着改已有蒙版

`08c29ca`、`dd34eb5`、`eaad6d5`。

用户要的是：先有一张蒙版，点「继续编辑」，再用套索增加、套索减去或画笔继续改同一张，而不是每次都新建图层。

正确行为：

- 套索从第一笔开始是开口的线。只有回到起点附近（屏幕上大约 14 像素）才闭合，并且只把围住的内部算进蒙版。
- 连续几次套索增加、套索减去、画笔，都堆在同一张蒙版上。
- 画面上先画到一块离屏 canvas，再按顺序把这一笔 POST 到服务器。成功之后不要再用重新下载的图替换这块 canvas。以前的 bug 就是旧图把刚画上的区域盖掉，看起来像没加上，或者把之前的区域减掉了。
- 只有最新一笔保存失败时，才丢掉本地 canvas 并重新读取文件。
- 切换地图、撤销、重做时要调用 `forgetLocalMasks()`，否则会把上一张地图的编辑留在画面上。

### 图层面板可以用滚轮

`5689960`。右侧图层面板是 flex 列，列表自己 `overflow-y: auto`，`min-height: 0`。没有这个，内容会被撑开但滚轮不起作用。

### 删除不用再问；可以先建空图层再画

`7e953c1`。已提交，还没推到 GitHub。

- 点删除图层立刻删除，没有确认框。`Ctrl+Z` 仍能撤销。底图仍然不能删。
- 「＋ 图层」立刻建一个全黑的空蒙版，名字先叫「新图层」，插到列表最前，并进入画笔编辑。名字输入框在图层已经存在之后才出现；取消或留空就保持「新图层」。重名会变成「新图层2」这种形式。
- 以前新建被 `prompt()` 挡住，取消就什么都不创建，所以用户觉得按钮坏了。

## 4. 还没提交、但已经写进工作区的功能

下面这些都在第 1 节列出的未提交文件里。用户已经在用这套行为，不要回退。

### 文件夹、点选对应图层

- 文件夹行有删除按钮。删除文件夹只是解散，里面的图层还在，`folder_id` 变回空。不弹确认。撤销能恢复文件夹。
- 可以把图层拖到文件夹标题上，或拖到已经在该文件夹里的图层上，从而放进文件夹。拖回根上的图层则会离开文件夹并调整顺序。底图不能拖。
- 选择工具下，点画面上的蒙版，右侧对应图层高亮。从上往下找最上面一张可见蒙版，采样 1 个像素，亮度大于 16 算点中。隐藏图层和底图跳过。点中后如果图层在折叠的文件夹里，会展开并滚到那一行。点空白处取消选择。
- 新建文件夹后，必须把文件夹写进 `state.maps[].folders`，再刷新图层。只写 `state.folders` 会被下一次 `loadLayers()` 盖掉。

### 地图列表

- 每张地图有删除按钮，不弹确认。只从项目里移除，并删除该地图的蒙版目录和缩略图。源图片文件保留。如果删的是当前地图，清空画面和本地蒙版缓存，再回到剩余的第一张。
- 左侧地图列表可以滚轮滚动，写法和图层面板一样。
- 右侧图层名字双击后就地改名。回车或移开输入框会保存，Esc 取消。底图也可以改名。文件夹名字还不能改。

相关接口：

```text
DELETE /api/maps/{map_id}
DELETE /api/maps/{map_id}/folders/{folder_id}
PATCH  /api/maps/{map_id}/layers/{layer_id}    已支持 name、visible、locked、folder_id、index
```

删地图时调用 `HistoryManager.forget(map_id)`，把这张地图的撤销栈丢掉。

### 一个地方只能有一张蒙版

自动生成的蒙版遵守这个规则。最先生成的蒙版留下重叠像素，后来的自动结果必须挖掉这些像素。

- `masks.take_unoccupied(mask, occupied)` 只保留还没被占住的像素。
- `web_app.occupied_mask()` 把当前地图上已有蒙版合成一张占用图。`skip_layer_id` 用来在「加进某一层」时不要把这一层自己算成障碍。
- `POST /api/maps/{id}/detect`：先占用已有蒙版，再按本次识别结果的顺序逐个挖掉。挖完是空的就不建图层。同一次识别里，先返回的结果优先。整批仍是一步撤销。
- `POST /api/maps/{id}/segment`：框选或点选生成预览之前就挖掉已有蒙版。如果什么都不剩，返回 `{"preview_id": null, "empty": true}`，不建预览文件。确认建立图层时再挖一次，防止预览之后又有新蒙版占住同一块；若变成空的，返回 409「这块地方已经有蒙版了」。
- 画笔、橡皮、套索增加、套索减去不受这条规则限制。它们改的是用户正在编辑的那一层，可以继续往上堆。

识别完成后的状态文案：有新图层时说明重叠处留给了更早的蒙版；一个都没有时说明这些地方已经有蒙版了。

### 框选有两种逻辑

这是最新的框选规则，不要改回「编辑时把方框几何填满」。

没有在编辑图层时：

1. 拉框只是给 SAM 的提示。
2. 用户再点「生成蒙版」。
3. 预览已经去掉别人的蒙版。
4. 用户点「建立图层」才产生新图层。

正在「继续编辑」某一层时：

1. 松手后立刻识别这个框，不经过「生成蒙版 / 建立图层」。
2. 接口是 `POST /api/maps/{map_id}/layers/{layer_id}/segment-add`，后台任务。
3. 识别结果先去掉其他图层已经占住的像素，再并进当前这一层。不新建图层。
4. 这一笔会先等画笔和套索的保存队列结束，避免盖掉还没写完的修改。
5. 成功后丢掉这一层的本地缓存并重新读取文件。状态栏写「已把识别到的区域加进「图层名」」。
6. 整块都被别的蒙版占住、这里没识别到、或当前层已经有这块，都会给出对应中文说明，并且不改文件。

前端事件：编辑中松手发出 `box-add`；没在编辑时发出 `box`。没有面积的框两个都不发。

### 切换地图后蒙版缺一块

两件独立的事叠在一起，用户会觉得「保存后再换一张地图，回来就少了」。

显示：

- 蒙版上色必须按蒙版自己的像素尺寸，不能按当时还显示着的上一张地图的尺寸去缩放。缩放后再缓存，切回来就会裁掉一块。
- 地图图片真正加载完成时清掉上色缓存再画。
- 读取蒙版时用 `createImageBitmap`，并且最多 3 张同时解码。过期的加载（换了地图、换了版本）必须丢掉。
- `loadMasks()` 只加载 `map_id` 等于 `loadedMapId` 的图层。`renderMaps()` 里要先设置 `loadedMapId` 并 `forgetLocalMasks()`，再 `setLayers()`。

保存：

- 套索在画面上用 canvas 的 nonzero 规则填充，线条交叉的中间也算进去。
- 原来服务器用 Pillow 的 polygon，交叉的中间是空的。画面上看着有，写进文件却没有。一切地图就从文件重读，中间就没了。
- 现在 `paint_polygon()` 用自己的 nonzero 扫描线填充，和画面一致。已经按旧规则存过的蒙版不会自动长回来，缺的部分要用户再套一次。
- 画笔请求在发起那一刻记下 `mapId`。不能等队列轮到时再读 `currentMapId`，否则用户已经切到下一张地图，这一笔会写错地方或丢失。

## 5. 改蒙版时不要再犯的错

1. 成功保存后，不要用 GET 到的蒙版替换正在编辑的本地 canvas。
2. 失败时只丢弃这一层，并只在仍停留在同一张地图时重载。
3. 蒙版缓存的键要能区分地图。切换地图必须增加 `maskGeneration` 并清空 `maskImages`、`maskCanvases`、`maskOverlays`。
4. 灰度 PNG 保存继续走 `to_mask_image()`，不要把 bool 蒙版直接乘 255。
5. 自动识别和「生成蒙版」要避开已有区域。手动画笔和套索不要避开。
6. 编辑中的框选走 `segment-add`。没在编辑时的框选仍走预览和「建立图层」。
7. 底图不能删，不能当蒙版画。锁按钮留在图层行最右边。
8. 删除图层、删除文件夹、删除地图都不要再加确认框。
9. 不要自动保存项目。蒙版 PNG 在每次涂改时已经写入；`project.json` 仍要用户按保存。

## 6. 测试

在仓库根目录：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/map_cutout tests/test_hf_demo_processor_api.py -q -p no:cacheprovider --basetemp "D:\06\剧本\地图抠图\项目输出\pytest-cursor-<新名字>"
```

`--basetemp` 每次换一个新目录，避免上次残留锁住文件。PowerShell 不支持 `&&`，用 `;`。本机沙箱经常不可用，命令需要在真实环境里跑。

浏览器测试：

```powershell
.\.venv\Scripts\python.exe -m uvicorn map_cutout.web_app:create_test_app --factory --host 127.0.0.1 --port 7875
```

打开这两个页面，标题必须是 `PASS`：

```text
http://127.0.0.1:7875/tests/web/canvas_editor.test.html
http://127.0.0.1:7875/tests/web/layer_tree.test.html
```

写本文时，最近一次完整相关测试是 `tests/map_cutout/test_api.py` 的 12 项通过，以及画布测试页标题 `PASS`。蒙版填充那一轮是 `test_masks.py` 加 `test_api.py` 共 18 项通过。还没有在全部未提交改动之上再跑一遍文档第 6 节的完整集合。接手后先跑完整测试。

`.gitignore` 里有很宽的 `*test*`。已经跟踪的测试文件可以正常提交；全新的测试文件可能要 `git add -f`。

不要随便结束用户正在用的 `启动工具.bat` 或已经开着的测试服务。

## 7. 给 Codex 的约束

- 用户是初学者。说明用中文，说清楚他要点哪个按钮。
- 不要重写整个前端，不要引入 npm 构建。
- 不要把权重、`.venv`、`.python`、地图原图、`项目输出` 提交到 Git。
- 不要改 `git config`。不要强推。不要在用户没要求时提交或推送。
- 推送目标只能是 `user-fork`，不能是 `origin`。
- 新产生的临时导出、分析文件放到 `D:\CursorM\Workspace`。这个仓库本身留在 `D:\06\剧本\地图抠图\Grounded-SAM-2`，不要搬走。
- 推理继续放在 `JobManager` 里。显存不足要保持中文错误。
- 图层编辑继续走撤销命令。`segment-add` 使用现有的 `_EditMask`，一步撤销能回到识别之前。

## 8. 建议的下一步

先读本文和当前未提交 diff，再跑第 6 节的测试。不要先提交。

如果用户要求提交，把 `7e953c1` 和现在的工作区分开说明：前者已经是一个本地提交，后者还在工作区。提交信息按「为什么」写，例如蒙版互斥、编辑时框选识别后并入当前层、套索交叉区域要能存下来。推送前再次问用户，因为上次推 `main` 被跳过了。
