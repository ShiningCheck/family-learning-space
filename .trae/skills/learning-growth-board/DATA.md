# 本技能的数据在哪

本技能的数据不在本目录，而在**仓库外**的数据区：

    <data-root>/learn/data/              ← 学情报告归档、每日/每周数据
    <data-root>/learn/capability-lists/  ← 语文/数学能力清单（参考）

`<data-root>` 由仓库根 `local.json` 的 `data_root` 指定（示例见 `local_example.json`），
路径解析统一走 `tools/data_paths.py`；仓库内**不得存在任何 `data/` 目录**。

完整约定见仓库根 `AGENTS.md` 第 7、8 条与 `.trae/rules/project_rules.md` 第 8 节。