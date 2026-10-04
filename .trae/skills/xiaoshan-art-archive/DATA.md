# 本技能的数据在哪

本技能的数据不在本目录，而在**仓库外**的数据区：

    <data-root>/art/data/       ← 画作索引、形象档案、成品清单
    <data-root>/art/images/     ← 画作图片
    <data-root>/art/audio/      ← 早期归档录音
    <data-root>/art/output/     ← 生成的画册/故事册/绘本

`<data-root>` 由仓库根 `local.json` 的 `data_root` 指定（示例见 `local_example.json`），
路径解析统一走 `tools/data_paths.py`；仓库内**不得存在任何 `data/` 目录**。

本技能**不提供**离线单文件版（`standalone.mode = "none"`）——画作图片与录音体量大，
不适合塞进浏览器存储。

完整约定见仓库根 `AGENTS.md` 第 7、8 条与 `.trae/rules/project_rules.md` 第 8 节。