# 家庭学习空间 · Claude Code 入口

Claude Code 不原生读 `AGENTS.md`，所以这里导入它；展开细节在 `.trae/rules/project_rules.md`。这里只做导入，**规则正文只在 `AGENTS.md`，本文不复制**：

@AGENTS.md
@.trae/rules/project_rules.md

两点定位：

- 技能在 `.trae/skills/<技能名>/SKILL.md`；当项目技能用时，本机建软链或联接：`ln -s ../.trae/skills .claude/skills`（Windows 用 `New-Item -ItemType Junction`）。
- 跨 app 复用约定见 `docs/agent-interop.md`。
