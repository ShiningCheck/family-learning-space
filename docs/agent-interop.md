# 跨 app 复用：规则与技能怎么共用（调研 + 本仓库做法）

给人和给 AI 都看的一页：**为什么规则要放这几处、别的工具从哪读、以后加新工具入口该怎么做**。
结论：规则用 `AGENTS.md`、技能用 `SKILL.md` + `.agents/skills/` 两个中立格式，跨 app 靠"薄入口 + 联接"对齐，
**内容永远只写一份**。本文件第 5 节是本仓库的具体落法，第 6 节是维护规则（写进 `AGENTS.md` 第 9 条）。

## 1. 标准层：两个中立格式

| 标准 | 管什么 | 谁治理 | 要点 |
|---|---|---|---|
| [`AGENTS.md`](https://agents.md/) | 项目规则 / 指令 | Agentic AI Foundation（Linux Foundation 项目，与 MCP、goose 同属一个基金会） | 纯 Markdown、**零必需字段**；60k+ 开源项目在用；源自 OpenAI Codex、Amp、Google Jules、Cursor、Factory 的共识；**就近原则**（离被改文件最近的那份优先） |
| [Agent Skills](https://agentskills.io/home)（`SKILL.md` + 技能目录） | 能力包（指令 + 脚本 + 素材） | 由 Anthropic 开发、作为开放标准发布，`agentskills/agentskills` 开放共建 | 一个技能 = 一个目录 + `SKILL.md`（`name` / `description` 必填）；可选 `scripts/` `references/` `assets/`；按需渐进加载 |

基金会的官方说明见 [Linux Foundation 公告](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation?categoryid=2849211)；
Anthropic 把技能作为开放标准发布的说明见 [Claude 官方博客](https://claude.com/blog/building-agents-with-skills-equipping-agents-for-specialized-work)。

两条设计上的共同点值得记住：**故意保持极简**（AGENTS.md 连必需字段都没有，结构化配置留给各工具自己），
**因此没人能独占文件名或目录名**——这正是它们能被广泛接受的原因。

## 2. 各工具从哪读

| 工具 | 规则入口 | 技能目录 |
|---|---|---|
| TraeWork / Trae | `.trae/rules/*.md`，以及项目根 `AGENTS.md` | `.trae/skills/` |
| WorkBuddy（CodeBuddy Code） | `.codebuddy/CODEBUDDY.md`（或根目录 `CODEBUDDY.md`）、`.codebuddy/rules/**/*.md`（所有 `.md` 递归自动加载） | `.codebuddy/skills/` |
| Cursor | `AGENTS.md`（官方定位为 `.cursor/rules` 的简易替代）；`.cursor/rules/` 支持 metadata 与 `alwaysApply` / `globs` | `.agents/skills/`、`.cursor/skills/`、`~/.agents/skills/`、`~/.cursor/skills/`；**为兼容还读** `.claude/skills/`、`.codex/skills/` |
| Codex | `AGENTS.md`（支持就近覆盖） | `$REPO_ROOT/.agents/skills/`、`$HOME/.agents/skills/` |
| Claude Code | `CLAUDE.md`（**不原生读** `AGENTS.md`，可用 `@path` 导入） | `.claude/skills/`、`~/.claude/skills/`；插件市场＝带 `.claude-plugin/marketplace.json` 的仓库（官方称其为"目录，不是托管商店"） |
| Gemini CLI / Aider | 可**配置**成读 `AGENTS.md`（`context.fileName` / `read: AGENTS.md`） | 各自目录 |

`.agents/skills/` 是关键信号：Cursor 官方把它列为项目级首选位置，Codex 直接用它，
而 `.claude/skills`、`.codex/skills` 属于"兼容回退"而非主路径。**新增技能目录时优先对齐 `.agents/skills/`。**

## 3. 行业解决复用的四种做法

| 做法 | 代表 | 怎么工作 | 代价 |
|---|---|---|---|
| 单一真源 + 生成器 | [Ruler](https://www.npmjs.com/package/@intellectronica/ruler)（`.ruler/` → 20+ agent 格式）、[RuleSync](https://www.rulesync.dev/)（`npx rulesync generate --targets "*" --features rules,skills,mcp`）、[agent-rules-sync](https://pypi.org/project/agent-rules-sync/1.4.3/)（`agent-sync sync rules skills settings`） | 内容写一处，CLI 生成/更新各工具文件 | 要跑同步命令；生成物可能被手改后漂移 |
| 兼容读取 + 官方回退 | Cursor 读 `.claude/skills`；Gemini/Aider 配置读 `AGENTS.md` | 工具侧做兼容，用户零操作 | 只有被"点名"的路径才有效 |
| 软链 / 薄壳文件 | 官方给的迁移姿势：改名 + `ln -s AGENTS.md AGENT.md`；`CLAUDE.md` 里 `@AGENTS.md` | 一个真文件，多处入口指向它 | Windows 建符号链接要权限（目录联接 `mklink /J` 免权限）；个别工具不跟随软链；**联接不适合进 git** |
| 包 / 注册表分发 | [`npx skills add owner/repo`](https://www.npmjs.com/package/skills)（可 `--skill`/`-a`/`--all`，带 `skills-lock.json` 锁版本）；marketplace.json 目录 | 用户一条命令装到多个 agent | 依赖 npm/GitHub；国内网络与私有内容受限 |

## 4. 还没解决的部分（别当它已经统一了）

- **Claude Code 仍不原生支持 `AGENTS.md`**，只认 `CLAUDE.md`，生态里为此有过公开争执。
- **frontmatter 不统一**：开放标准只定义可移植子集（`name`/`description`/`license`/`compatibility`/`metadata`/`allowed-tools`），
  Claude Code 有扩展字段，Cursor 又有 `paths`、`disable-model-invocation`、`icon`、`color` 等私有字段。
  **所以技能 frontmatter 只写可移植字段，工具私有字段要用时单独说明**。
- **`.agents/skills/` 尚未被所有 IDE 采纳**：Trae、WorkBuddy 目前仍是自家目录（`.trae/skills/`、`.codebuddy/skills/`），
  它们是否兼容中立目录没有官方声明，**需要跨工具时按第 5 节用联接或薄壳对齐**。
- **Windows 上软链有权限门槛**：本机多工具复用用目录联接（`mklink /J`，免管理员），
  但联接不会被 git 正常保存，**分发时不能依赖联接**。

## 5. 本仓库的落法

**分层：一份内容 + 一份薄入口。**

| 层 | 位置 | 放什么 | 谁来读 |
|---|---|---|---|
| 规则真源 | `AGENTS.md`（仓库根） | 9 条硬规则（"必须做什么"） | 所有认 AGENTS.md 的工具（含 Trae）；也是本项目规则的入口 |
| 规则详版 | `.trae/rules/project_rules.md` | 每条规则的展开：实现方式、合并规则、示例（"怎么做"） | Trae（自动注入）；其他工具按需读 |
| 薄入口 | `.codebuddy/CODEBUDDY.md`、`CLAUDE.md` | 只有一行导入/指向，**绝不复制正文** | WorkBuddy、Claude Code |
| 技能真源 | `.trae/skills/<技能>/`（`SKILL.md` + `web/` + `data-templates/`） | 全部技能内容 | 本仓库 |
| 技能入口（可选） | `.agents/skills/`、`.codebuddy/skills/` | 指向技能真源的**目录联接**，本机自用 | Cursor / Codex / WorkBuddy |

本机想一次喂给多个工具（示例命令，**联接不进 git，只在本机执行**）：

```powershell
# Windows：免管理员的目录联接（junction）
New-Item -ItemType Junction -Path .agents\skills -Target .trae\skills
New-Item -ItemType Junction -Path .codebuddy\skills -Target .trae\skills
```

macOS / Linux：`ln -s ../.trae/skills .agents/skills`（相对路径更稳）。

分发出去的包**不靠联接**：包里的技能就在 `.trae/skills/`，接收方按 `.codebuddy/CODEBUDDY.md` 与
`AGENTS.md` 的指引读取；需要 `.agents/skills/` 的，自己在包根跑一次上面对应的联接命令。

## 6. 维护规则（已写进 `AGENTS.md` 第 9 条）

1. **规则只改 `AGENTS.md` 的条目**；展开细节改 `.trae/rules/project_rules.md`。改一处必须同步另一处的对应条目，
   不允许出现"两份互相矛盾的规则正文"。
2. **新增工具入口只放薄壳**：能导入就导入（WorkBuddy 的 `.codebuddy/CODEBUDDY.md` 与 Claude Code 的
   `CLAUDE.md` 都用 `@` 导入 `AGENTS.md` 和 `.trae/rules/project_rules.md` 两份），不能导入就写指向，
   **不许把规则正文复制进去**。
3. **新增技能目录时优先对齐 `.agents/skills/`**（中立标准）；工具私有目录用联接，不手工维护第二份。
4. **技能 frontmatter 只写可移植字段**（`name` / `description` / `license` / `compatibility` / `metadata` / `allowed-tools`），
   工具私有字段（Cursor 的 `paths`/`icon`/`color` 等）不要写进通用技能。
5. **改了规则文件或技能入口后**：跑 `python tools/privacy_guard.py --all` 与 `python tools/smoke_test.py`，
   再 `python tools/build_dist.py --bundle` 打一次包 —— 入口文件必须随包一起发出去。

## 7. 参考

- AGENTS.md 官方站点（格式、60k+ 项目、迁移姿势、Aider/Gemini 配置）：https://agents.md/
- Agent Skills 标准与共建：https://agentskills.io/home ｜ https://agentskills.io/specification
- Anthropic 关于把技能作为开放标准发布的说明：https://claude.com/blog/building-agents-with-skills-equipping-agents-for-specialized-work
- Linux Foundation 成立 Agentic AI Foundation（MCP / goose / AGENTS.md）：https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation
- Cursor：技能目录与 frontmatter（含 `.agents/skills/`、兼容回退）https://cursor.com/docs/skills ｜ 规则与 AGENTS.md https://cursor.com/docs/rules
- Claude Code：技能 https://code.claude.com/docs/en/skills ｜ 插件与市场 https://code.claude.com/docs/en/plugins
- Codex 技能目录：https://dev.to/skillsboard/codex-skills-what-they-are-and-how-to-use-them-4gge
- 同步与分发工具：Ruler https://www.npmjs.com/package/@intellectronica/ruler ｜ RuleSync https://www.rulesync.dev/ ｜ `npx skills add` https://www.npmjs.com/package/skills
