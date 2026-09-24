# Fusion2BambuStudio

面向 Autodesk Fusion 的 **MF3D打印摆盘助手**，当前开发预览版本为 **0.1.14**。

## 功能

- 读取 Fusion 实体、外观颜色和装配位置，不修改原设计几何。
- 彩色三维预览、不可拆打印组、点选贴板面。
- 可为所选件、当前盘或所有盘调用本机 Bambu 引擎推荐朝向，双视图预览后确认；手动方向可锁定。
- 按颜色自动分盘，优先从打印板中央向周围布局。
- 可选当前盘或所有盘，调用 Bambu 引擎建议盘内位置；预览、确认后应用，可撤销。
- 手动拖动换盘、跨颜色确认、局部解除整体及撤销/重做。
- 独立选盘导航，切换预览与树列表展开/收起分离。
- 读取本机 Bambu 预设，导出单个多盘 3MF，并进行原生读写保真核验。

默认配置：P2S、0.4 mm 喷嘴、PETG、Cool Plate SuperTack（低温增稳板）。

## 安装与使用

在 Fusion 的“脚本和附加模块”中添加本仓库内的 **`BambuPlateStudio` 子文件夹**，而不是仓库根目录，然后运行加载项。请保留子文件夹名称，它需要与 Python 入口和 manifest 名称一致。

运行后从“实用程序 → 附加模块 → MF3D打印摆盘助手”打开窗口。本机需安装 Bambu Studio；加载项运行不依赖 MCP，也不会发送打印任务。

- [详细使用说明](BambuPlateStudio/GUIDE_CN.md)
- [开发说明](BambuPlateStudio/README.md)
- [已验证范围与待验收项目](BambuPlateStudio/ACCEPTANCE_STATUS.md)

当前为开发预览版，完整 Fusion 桌面鼠标流程和跨版本兼容性尚未全部验收。

## 测试

在仓库根目录执行（需要可用的 Python 和 Node.js）：

```text
python -m unittest discover -s BambuPlateStudio/tests
node BambuPlateStudio/tests/test_viewer_math.js
node BambuPlateStudio/tests/test_transfer_confirmation.js
node BambuPlateStudio/tests/test_tree_drop.js
node BambuPlateStudio/tests/test_plate_navigation.js
node BambuPlateStudio/tests/test_orientation_preview.js
node BambuPlateStudio/tests/test_arrangement_preview.js
```

部分预设测试依赖本机 Bambu Studio，未安装时会跳过相应测试。Fusion 集成脚本依赖专用测试文档，包含开发环境路径；请先阅读脚本中的隔离文档检查，再调整为自己的测试环境，不要直接在生产文档中运行。

仓库仅包含代码、说明和测试脚本，不包含用户模型、打印项目、切片产物、Bambu 私有预设或个人编辑器配置。文档中引用的本地测试产物不随仓库提交。
