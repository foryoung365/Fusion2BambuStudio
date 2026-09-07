# 验收状态：未完成

本文件用于区分“代码已实现”“自动化测试通过”和“实机操作已验证”，不能代替完整验收。

| 要求 | 当前证据 | 状态 |
| --- | --- | --- |
| 默认 P2S / 0.4 / SuperTack / PETG | 本机预设测试；Fusion 原生控件读数 | 已验证默认配置 |
| 原设计几何不修改 | 正式实例导出前后重新读取实际 Fusion 几何并比较指纹 | 本轮正式实例已验证 |
| 读取实体、实例位置与直接 RGB | 纸巾盒 27 实体实测；回归测试 | 已验证该模型，更多嵌套实例待测 |
| 六件整体保持相对关系，右胸顶面朝下 | 实际导出、Bambu 原生往返保真报告 | 已验证该模型 |
| 自动分色分盘、人工输入边界 | 54 项 Python 自动化测试；中央优先、禁区避让、间距与旧规则保护；Fusion 实际八盘均居中 | 算法及输入逻辑通过 |
| GUI 中修改打印组、选面、移动/换盘 | 本地浏览器交互测试；新版已在 Fusion 热重载，27 个实体各抽查一个三角面均成功匹配真实 BRep 平面 | Fusion 完整鼠标交互仍待完成 |
| 三维排盘预览 | 正式加载项通过正常 HTML 桥返回三种真实 WebGL 画布；图像已检查 | 模型画布已验证，完整窗口鼠标操作待验收 |
| 规则保存及更新后安全恢复 | 加载项重启恢复；实际导出 F3D、在新文档载入并恢复 27 实体 / 22 单元 / 8 盘；所选 BRep 面引用与方向另行验证通过 | 本机文档持久化及平面引用恢复通过 |
| 单个完整 Bambu 3MF | 正式加载项实例导出，27 实体 / 22 对象 / 8 盘，原生 Bambu 往返通过 | 正式实例回归通过 |
| Bambu Studio 全盘切片 | 本轮两个新导出项目均八盘 Success，G-code 齐全；正式实例输出另经保真和中文名称核验 | 已验证正式实例导出项目 |
| 安装与发布 | 本机 Scripts.addExisting 注册成功，Script.run/stop 重启成功，启动项保持关闭；预览包生成脚本及说明已提供 | 加载项管理已验证；仅作为开发预览发布 |

2026-09-07 更新：旧测试对话框阻塞已解除（活动命令为 SelectCommand）。已完整热重载，并打开 1460 × 920 新版浮动窗口；bootstrap / viewport_data / view_ready 均收到成功结果。未修改原设计几何。

当前视觉验收限制：电脑操作技能的 Fusion 窗口截图返回 `SetIsBorderRequired failed: 不支持此接口 (0x80004002)`。本轮通过插件自身 HTML 桥取得实际 WebGL 画布，已检查三种视图，但这不能代替完整窗口截图或所有鼠标操作。

本轮证据目录：`test_artifacts/fusion_visual_integration_02_managed/`。`integration.json` 明确标记 `managedAddin=true`、`mouseGuiTest=false`；`slice/slice_test.json` 记录八盘成功；`slice/fidelity.json` 记录切片后保真。`fusion_group.png`、`fusion_layout.png`、`fusion_face.png` 来自 Fusion 实际画布，而非离线浏览器。

最近两轮均有代码/测试进展，没有将该障碍标为目标完成，也未把目标缩减为仅切片成功。

0.1.1 持久化证据：`test_artifacts/document_roundtrip_02/roundtrip.json` 与 `document_roundtrip_03_face/face_persistence.json`。原文档始终保持打开，测试仅关闭自行创建的临时导入副本。`document_roundtrip_01` 保留修复前的失败和诊断记录，不能误当通过报告。
