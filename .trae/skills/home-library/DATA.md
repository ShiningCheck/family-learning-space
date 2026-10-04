# 本技能的数据在哪

本技能的数据不在本目录，而在**仓库外**的数据区：

    <data-root>/lib/data/     ← 书目、书架
    <data-root>/lib/images/   ← 藏书封面照片

`<data-root>` 由仓库根 `local.json` 的 `data_root` 指定（示例见 `local_example.json`），
路径解析统一走 `tools/data_paths.py`；仓库内**不得存在任何 `data/` 目录**。

完整约定见仓库根 `AGENTS.md` 第 7、8 条与 `.trae/rules/project_rules.md` 第 8 节。