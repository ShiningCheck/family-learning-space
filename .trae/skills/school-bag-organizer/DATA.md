# 本技能的数据在哪

本技能的数据不在本目录，而在**仓库外**的数据区：

    <data-root>/bag/data/    ← 课表、课程用具要求、班级通知、书包整理打卡
    <data-root>/bag/share/   ← 离线单文件分享包（含真实课表，勿外传）

`<data-root>` 由仓库根 `local.json` 的 `data_root` 指定（示例见 `local_example.json`），
路径解析统一走 `tools/data_paths.py`；仓库内**不得存在任何 `data/` 目录**。

本技能的离线单文件版按 `skill.json` 的 `standalone.mode = "localstorage"` 生成：
只嵌 `data-templates/` 的匿名示例，真实数据走浏览器 `localStorage`。

完整约定见仓库根 `AGENTS.md` 第 7、8 条与 `.trae/rules/project_rules.md` 第 8 节。