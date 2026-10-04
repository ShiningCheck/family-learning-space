# 「成长家园」反馈中转服务（Cloudflare Worker）部署手册

> 面向作者本人的一次性部署文档。部署一次之后基本不需要再动。

## 一、这个服务是什么，为什么需要它

「成长家园」是一个本地家庭门户项目：每个家庭把仓库拷回家，在自己电脑上用
`python preview_server.py` 起一个 8090 端口的本地静态服务器给孩子用。

问题是：**分发出去之后，用户家里没有任何公网入口**，作者收不到「页面哪里不好用、
想要什么新功能」的反馈。所以需要一个部署在公网上的中转服务：

```
浏览器反馈组件
    │  POST /api/feedback（含截图 base64）
    ▼
用户本地 Python 服务器（8090）
    │  POST https://<你的worker>.workers.dev/feedback
    ▼
本 Cloudflare Worker（公网）
    ├──► 自动创建 GitHub Issue（截图先上传到仓库 feedback-assets/ 目录）
    └──► 推送飞书自定义机器人富文本卡片（带「在 GitHub 查看」按钮）
```

Worker 承担三件事：

1. **建 GitHub Issue**：把反馈变成结构化 Issue（分类标签、页面上下文、运行环境、截图），
   截图通过 Contents API 直接提交进仓库，Issue 正文内嵌图片。
2. **推飞书通知**：反馈一来手机上立刻能看到卡片。
3. **防滥用**：Worker URL 会写进公开分发的配置里，任何人都能 POST。因此有
   6MB 体积上限、`X-App-Key` 混淆门槛（注意：key 随代码公开，只是挡无脑扫描器，
   **不是真正的安全机制**）、per-IP 每小时限流（默认 10 条）、全局每日建 Issue
   上限（默认 20 条，超过后只推飞书不建 Issue）。

Cloudflare Workers 免费额度为 **10 万请求/天**，对家庭级反馈量绰绰有余。

## 二、前置条件

| 条件 | 说明 |
|---|---|
| Cloudflare 账号 | 免费注册即可，本服务用免费额度足够（10 万请求/天）。注册地址：https://dash.cloudflare.com/sign-up |
| GitHub 仓库 | 就是本仓库（接收反馈 Issue 与截图附件） |
| GitHub Personal Access Token | 见下面的逐步生成说明 |
| 飞书 | 用于建一个只有自己的群 + 自定义机器人（可选但强烈建议） |
| Node.js ≥ 18 | 本地跑 wrangler 用 |

### 生成 GitHub Personal Access Token（细粒度 token，推荐）

1. 登录 GitHub，点右上角头像 → **Settings**。
2. 左侧栏最底部点 **Developer settings**。
3. 选 **Personal access tokens → Fine-grained tokens**，点 **Generate new token**。
   （直达地址：https://github.com/settings/personal-access-tokens/new ）
4. 填写：
   - **Token name**：例如 `shan-learn-feedback-relay`；
   - **Expiration**：建议选长一点（例如 1 年），到期后需要重新生成并更新 secret；
   - **Repository access**：选 **Only select repositories**，选中接收反馈的那个仓库；
   - **Permissions → Repository permissions** 里设置两项：
     - **Issues**：`Read and write`
     - **Contents**：`Read and write`（用于上传截图附件）
5. 点 **Generate token**，立刻复制保存（页面关了就再也看不到了）。

### 或者：经典 token（Classic）

直达地址：https://github.com/settings/tokens/new ，勾选 **repo** 整个大类即可，
其余不勾。生成后复制保存。

## 三、部署步骤

在 `feedback-relay/` 目录下依次执行（PowerShell 用 `;` 分隔命令，不支持 `&&`）：

```powershell
cd <你的仓库目录>\feedback-relay

# 1. 安装 wrangler
npm install

# 2. 改 wrangler.toml：把 [vars] 里的 GITHUB_OWNER / GITHUB_REPO
#    从占位符 YOUR_GITHUB_NAME / YOUR_REPO_NAME 改成你的真实 GitHub 用户名和仓库名

# 3. 登录 Cloudflare（会弹浏览器授权）
npx wrangler login

# 4. 逐个注入敏感配置（每条命令回车后会提示你粘贴值，输入不回显）
npx wrangler secret put GITHUB_TOKEN     # 上面生成的 GitHub token
npx wrangler secret put LARK_WEBHOOK     # 飞书机器人 webhook 地址（第五节获取）
npx wrangler secret put LARK_SECRET      # 飞书机器人签名密钥（没开签名校验可跳过）
npx wrangler secret put RELAY_APP_KEY    # 自定义一个应用口令（与分发配置保持一致）

# 5. 部署
npm run deploy

# 6. 记下输出里的部署地址，形如：
#    https://shan-learn-feedback-relay.<你的子域>.workers.dev
```

> 提示：`wrangler login` 之后如果你还没有 workers.dev 子域，控制台会要求先设置一个；
> 设置过一次以后就固定了。

## 四、上线后必做的两件事

### 1. 在 GitHub 仓库里预先创建标签

GitHub 对 Issue 里不存在的 label 会返回 **422**。Worker 里已经做了三级降级容错
（全部标签 → 只用 `ISSUE_LABEL` → 不带标签），但为了让 Issue 自动带上分类标签，
请在仓库 **Issues → Labels → New label**（直达：`https://github.com/<owner>/<repo>/labels`）
逐个创建以下标签：

| 标签名 | 推荐颜色 | 用途 |
|---|---|---|
| `用户反馈` | `0E8A16`（绿） | 所有自动反馈 Issue 的固定标签 |
| `建议-新功能` | `A2EEEF`（浅蓝） | type = feature |
| `体验-不好用` | `FBCA04`（黄） | type = usability |
| `Bug-错误` | `D73A4A`（红） | type = bug |
| `其他-反馈` | `D4C5F9`（浅紫） | type = other |
| `优先级-高` | `E99695`（橙红） | severity = high |
| `优先级-阻塞` | `B60205`（深红） | severity = blocker |

### 2. 把 Worker URL 写进分发配置

把部署得到的 `https://xxx.workers.dev` 地址填到：

```
.trae/skills/growth-home/data-templates/feedback_channels.json  →  relay.url
```

同时把 `RELAY_APP_KEY` 的值填进该配置对应的 appKey 字段。这样分发出去的每个家庭
**零配置**即可把反馈送达你这里（data-templates 会随仓库分发，data/ 是各家自己的）。

## 五、如何拿到飞书自定义机器人 Webhook

1. 打开飞书，**新建一个群聊**（成员只有你自己即可，群名例如「成长家园反馈」）。
2. 进群 → 右上角 **···（群设置）** → **群机器人** → **添加机器人**。
3. 选择 **自定义机器人（Custom Bot）**，填名字（例如「成长家园反馈」）和描述，下一步。
4. 复制生成的 **Webhook 地址**（形如
   `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-...`），
   这就是 `LARK_WEBHOOK` 的值。
5. **（建议）** 在安全设置里勾选 **签名校验**，复制生成的密钥，这就是 `LARK_SECRET`
   的值。Worker 已按飞书官方算法实现加签（timestamp + "\n" + secret 作为 HMAC-SHA256
   的 key，对空字符串签名后 base64）。
6. 完成添加。之后可用 `npx wrangler secret put LARK_WEBHOOK`（和 `LARK_SECRET`）写入。

## 六、部署后自测

PowerShell 下完整自测流程（注意 PowerShell 不支持 `&&`，用 `;`；JSON 体先写文件
再用 `-InFile`，避免命令行转义地狱）：

```powershell
# 把 <WORKER_URL> 换成你的部署地址；如果配置了 RELAY_APP_KEY，把 <APP_KEY> 也换掉

# 1. 健康检查：确认 github / lark 两个通道都已配置（true）
Invoke-RestMethod -Uri '<WORKER_URL>/health'

# 2. 准备一条测试反馈的 JSON 文件
@'
{
  "type": "other",
  "summary": "部署自测",
  "message": "这是一条来自 PowerShell 的测试反馈，收到后请关闭本 Issue。",
  "expect": "GitHub 出现一条 Issue，飞书群收到一张卡片",
  "severity": "low",
  "contact": "",
  "page": { "path": "/learn/web/index.html", "tab": "home", "title": "门户首页", "url": "http://127.0.0.1:8090/" },
  "env": { "ua": "PowerShell-test", "platform": "Win32", "screen": "0x0@1", "lang": "zh-CN", "theme": "capybara", "online": true, "touch": false },
  "images": [],
  "client": { "appVersion": "0.1.0", "widgetVersion": "1.0.0", "installId": "selftest-00000000", "submittedAt": "2026-09-06T21:30:00+08:00" },
  "server": { "installId": "selftest-00000000", "machineId": "a1b2c3d4", "python": "3.11.9", "os": "Windows-11", "port": 8090, "access": "local", "gitCommit": "selftest" }
}
'@ | Set-Content -Path "$env:TEMP\fb-test.json" -Encoding UTF8

# 3. 提交测试反馈（配置了 RELAY_APP_KEY 才需要 -Headers 那行）
Invoke-RestMethod -Uri '<WORKER_URL>/feedback' -Method Post `
  -ContentType 'application/json' `
  -Headers @{ 'X-App-Key' = '<APP_KEY>' } `
  -InFile "$env:TEMP\fb-test.json"
```

用 curl.exe 也可以（Windows 10+ 自带，注意写 `curl.exe` 而不是 `curl`，
后者是 PowerShell 的 Invoke-WebRequest 别名）：

```powershell
curl.exe -s "<WORKER_URL>/health"
curl.exe -s -X POST "<WORKER_URL>/feedback" -H "Content-Type: application/json" -H "X-App-Key: <APP_KEY>" --data-binary "@$env:TEMP\fb-test.json"
```

预期返回（成功）：

```json
{ "ok": true, "id": "fbk_20260906_xxxxxxxx", "issueUrl": "https://github.com/.../issues/1",
  "issueNumber": 1, "delivered": ["github", "lark"], "failed": [], "retry": false,
  "github": "created", "lark": "sent" }
```

同时检查：GitHub 仓库出现新 Issue（带标签和完整表格），飞书群收到卡片。

## 七、日常运维

- **看实时日志**：`npm run tail`（在 feedback-relay/ 目录下）。所有外部调用的失败
  原因只写进 `console.error`，在这里能看到；客户端永远拿不到内部错误细节。
- **改限流阈值**：编辑 `wrangler.toml` 的 `[vars]` 中 `RATE_LIMIT_PER_HOUR`
  （单 IP 每小时上限）和 `DAILY_ISSUE_CAP`（全局每日建 Issue 上限），然后
  `npm run deploy` 重新部署即可。达到每日上限后反馈不会丢：飞书照常推送，
  响应里 `github` 字段为 `"capped"`。
- **截图清理**：用户截图会持续堆积在仓库 `feedback-assets/<年>/<月>/` 目录
  （每张 base64 上限 2.5MB、每次最多 3 张）。建议每 1~3 个月清理一次旧目录：
  直接删除对应年月子目录并提交即可（已建 Issue 里的图片链接会失效，但 Issue
  文字内容不受影响）。
- **私有仓库注意**：如果接收反馈的仓库是私有的，`raw.githubusercontent.com`
  的截图链接只有登录的协作者能打开；Issue 文字不受影响。反馈里不应包含孩子
  的真实姓名/学校等隐私信息（前端组件已有相应提示）。
- **token 到期**：细粒度 token 有有效期，到期后 GitHub 通道会开始返回
  `github:"failed"`（日志里是 401）。重新生成 token 后执行
  `npx wrangler secret put GITHUB_TOKEN` 即可，无需重新部署代码。

## 八、常见问题排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志里 GitHub 返回 **401** | token 失效/过期/权限不足 | 重新生成 token（确认勾选 Issues + Contents 读写），`npx wrangler secret put GITHUB_TOKEN` |
| 日志里 GitHub 返回 **404** | `GITHUB_OWNER` / `GITHUB_REPO` 写错，或 token 对该仓库无权限 | 核对 wrangler.toml 里的 owner/repo 拼写；确认 token 的 Repository access 选中了该仓库；改完 `npm run deploy` |
| 日志里 GitHub 返回 **422** | 标签在仓库里不存在（Worker 会自动降级重试），或 title/body 为空 | 按第四节创建全部 7 个标签；降级重试成功时 Issue 会少标签，属预期行为 |
| 飞书返回 **19021** | 签名校验失败：`LARK_SECRET` 没配或配错，或 Worker 与飞书服务器时钟差过大（超 1 小时） | 核对机器人「签名校验」密钥与 `npx wrangler secret put LARK_SECRET` 写入的值一致；确认机器人安全设置与 secret 配置匹配（要么都开、要么都关） |
| 飞书返回 **19022** / 其它非 0 code | webhook 地址错误或被移除 | 到群机器人设置里重新复制 webhook，更新 `LARK_WEBHOOK` |
| 客户端收到 **403** | `X-App-Key` 与 `RELAY_APP_KEY` 不一致 | 核对分发配置 `feedback_channels.json` 里的 appKey 与 secret 写入的值 |
| 客户端收到 **429** | 该 IP 一小时内提交超过 `RATE_LIMIT_PER_HOUR` 条 | 正常防滥用行为；如确属误伤可调大阈值后重新部署 |
| 响应里 `github:"capped"` | 当日建 Issue 数已达 `DAILY_ISSUE_CAP` | 正常防滥用行为，飞书仍会收到通知；次日自动恢复 |
| 国内访问 `workers.dev` 很慢/超时 | `*.workers.dev` 域名在部分网络环境下不稳定 | 给 Worker **绑定自定义域名**：Cloudflare Dashboard → Workers & Pages → 你的 Worker → Settings → Domains & Routes → Add → Custom Domain（需要一个托管在 Cloudflare 上的域名）。然后把 `feedback_channels.json` 的 `relay.url` 换成自定义域名地址 |
| 本地 `npm run dev` 时限流/计数不生效 | wrangler dev 本地模拟环境对 Cache API 支持有限 | 属预期：代码对 Cache API 异常做了 fail-open 处理，不影响本地调试主流程；限流行为以线上为准 |

## 九、环境变量清单（速查）

| 变量 | 配置方式 | 必填 | 含义 |
|---|---|---|---|
| `GITHUB_TOKEN` | secret | 建 Issue 必填 | GitHub PAT（Issues + Contents 读写） |
| `GITHUB_OWNER` | wrangler.toml [vars] | 建 Issue 必填 | 仓库拥有者 |
| `GITHUB_REPO` | wrangler.toml [vars] | 建 Issue 必填 | 仓库名 |
| `GITHUB_BRANCH` | wrangler.toml [vars]（可选） | 否 | 截图/Issue 提交分支；不设置则用仓库默认分支 |
| `ISSUE_LABEL` | wrangler.toml [vars] | 否（默认 `用户反馈`） | Issue 固定标签 |
| `ASSET_DIR` | wrangler.toml [vars] | 否（默认 `feedback-assets`） | 截图在仓库里的存放目录 |
| `RATE_LIMIT_PER_HOUR` | wrangler.toml [vars] | 否（默认 10） | 单 IP 每小时反馈上限 |
| `DAILY_ISSUE_CAP` | wrangler.toml [vars] | 否（默认 20） | 全局每日建 Issue 上限 |
| `LARK_WEBHOOK` | secret | 推飞书必填 | 飞书自定义机器人 webhook 地址 |
| `LARK_SECRET` | secret | 否 | 飞书机器人签名密钥（开了签名校验才需要） |
| `RELAY_APP_KEY` | secret | 否 | 应用口令；配置后客户端必须带 `X-App-Key` 头。会随分发代码公开，仅作为混淆门槛，不是安全机制 |

## 十、接口契约（供本地服务器/前端开发对照）

`POST /feedback` 请求体与响应体的完整字段契约见仓库根目录相关设计说明；
Worker 对缺失字段全部有安全默认值，字符串自动 trim + 截断
（message ≤ 4000 字、expect ≤ 1000、contact ≤ 200），type 白名单
feature/usability/bug/other，severity 白名单 low/medium/high/blocker，
images 最多 3 张、单张 base64 ≤ 2.5MB、mime 仅 jpeg/png/webp。
