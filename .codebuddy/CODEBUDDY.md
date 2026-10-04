# 家庭学习空间 · WorkBuddy（CodeBuddy Code）入口

规则正文在根目录 `AGENTS.md`，展开细节在 `.trae/rules/project_rules.md`，这里只做导入，**不要在本文里复制规则**：

@AGENTS.md
@.trae/rules/project_rules.md

两点定位（避免踩空）：

- **技能不在 `.codebuddy/skills/`**，而在 `.trae/skills/<技能名>/SKILL.md`。想当项目技能用，在本机建一个目录联接即可（联接不进 git）：
  `New-Item -ItemType Junction -Path .codebuddy\skills -Target .trae\skills`
- 跨 app 复用与各工具入口约定见 `docs/agent-interop.md`。
