/**
 * 「成长家园」页面改进反馈中转服务 —— Cloudflare Worker
 *
 * 数据流：
 *   浏览器反馈组件 → 用户本地 Python 服务器(/api/feedback) → 本 Worker(公网)
 *   → 自动创建 GitHub Issue（含截图上传到仓库）＋ 推送飞书富文本卡片
 *
 * 设计要点：
 * - 零外部依赖，只用 Cloudflare 内置 API（Cache API / ctx.waitUntil）与 Web 标准 API
 *   （fetch / crypto.subtle / TextEncoder / Response 等）。
 * - 所有响应（含错误响应）一律为 JSON 且携带完整 CORS 头。
 * - 防滥用：Content-Type 校验、6MB 体积上限、X-App-Key 混淆门槛、
 *   per-IP 每小时限流（Cache API）、全局每日建 Issue 上限（Cache API）。
 * - 绝不向客户端返回堆栈、密钥或任何内部错误细节，详细信息只写 console.error。
 */

// ==================== 常量 ====================

const SERVICE_NAME = 'shan-learn-feedback-relay';

/** 原始请求体长度上限：6 MB（超限返回 413） */
const MAX_BODY_LENGTH = 6 * 1024 * 1024;

/** 单张截图 base64 字符串长度上限：2.5 MB */
const MAX_IMAGE_B64_LENGTH = Math.floor(2.5 * 1024 * 1024);

/** 截图最多张数 */
const MAX_IMAGES = 3;

/** 每个外部请求（GitHub / 飞书）的超时时间：8 秒 */
const FETCH_TIMEOUT_MS = 8000;

/** 允许的截图 MIME 类型 → 文件扩展名 */
const ALLOWED_IMAGE_MIME = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
};

/** 反馈类型（白名单）→ 中文名 / emoji / GitHub 标签 */
const TYPE_MAP = {
  feature: { cn: '新功能建议', emoji: '✨', label: '建议-新功能' },
  usability: { cn: '体验问题', emoji: '🧭', label: '体验-不好用' },
  bug: { cn: '程序错误', emoji: '🐞', label: 'Bug-错误' },
  other: { cn: '其他', emoji: '💬', label: '其他-反馈' },
};

/** 严重程度（白名单）→ 中文名 / GitHub 标签（仅 high、blocker 会加优先级标签） */
const SEVERITY_MAP = {
  low: { cn: '低', label: '' },
  medium: { cn: '中', label: '' },
  high: { cn: '高', label: '优先级-高' },
  blocker: { cn: '阻塞', label: '优先级-阻塞' },
};

/** 飞书卡片头图颜色（按反馈类型区分，方便在群里一眼分辨） */
const LARK_CARD_COLOR = {
  feature: 'green',
  usability: 'orange',
  bug: 'red',
  other: 'blue',
};

/** 中国标准时间（Asia/Shanghai）相对 UTC 的固定偏移，毫秒 */
const CN_TZ_OFFSET_MS = 8 * 60 * 60 * 1000;

/** 统一 CORS 头：所有响应（含 404/415/429 等错误）都要带上 */
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-App-Key',
  'Access-Control-Max-Age': '86400',
};

// ==================== 基础工具函数 ====================

/**
 * 构造 JSON 响应，统一附带 CORS 头。
 * @param {*} obj 响应体对象
 * @param {number} status HTTP 状态码
 */
function jsonResp(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...CORS_HEADERS,
    },
  });
}

/**
 * 带 8 秒超时的 fetch。
 * 优先使用 AbortSignal.timeout()（Cloudflare Workers 已支持）；
 * 若运行环境不支持，则退化为 AbortController + setTimeout，
 * 并在 finally 中清理定时器，避免泄漏。
 */
async function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
  let timer = null;
  let signal;
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    signal = AbortSignal.timeout(timeoutMs);
  } else {
    const controller = new AbortController();
    timer = setTimeout(() => controller.abort(), timeoutMs);
    signal = controller.signal;
  }
  try {
    return await fetch(url, { ...options, signal });
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

/** 按 Unicode 码点安全截断字符串（不会把 emoji / 代理对切成半个字符） */
function truncate(str, maxLen) {
  if (typeof str !== 'string') return '';
  const chars = Array.from(str);
  if (chars.length <= maxLen) return str;
  return chars.slice(0, maxLen).join('');
}

/** 任意值 → 安全的裁剪后字符串（非字符串返回空串） */
function cleanStr(value, maxLen = 0) {
  if (typeof value !== 'string') return '';
  let s = value.trim();
  if (maxLen > 0) s = truncate(s, maxLen);
  return s;
}

/**
 * 去掉反引号序列（含 ``` 代码围栏），防止用户输入在 Markdown 里
 * 闭合代码块 / 引用块从而注入任意 Markdown 或 HTML。
 */
function stripBackticks(s) {
  return String(s).replace(/`+/g, "'");
}

/**
 * 表格单元格内的内联文本清洗：去反引号、去竖线、压掉换行，
 * 防止破坏 Markdown 表格结构。
 */
function sanitizeInline(s) {
  return stripBackticks(String(s)).replace(/\|/g, '¦').replace(/\s*\n\s*/g, ' ');
}

/** 字段缺失时统一显示「未提供」 */
function orNone(s) {
  const v = cleanStr(s);
  return v === '' ? '未提供' : v;
}

/** 取中国标准时间（UTC+8）的年月日时分各分量（均为补零字符串） */
function cnDateParts(date = new Date()) {
  const t = new Date(date.getTime() + CN_TZ_OFFSET_MS);
  const p = (n) => String(n).padStart(2, '0');
  return {
    yyyy: String(t.getUTCFullYear()),
    mm: p(t.getUTCMonth() + 1),
    dd: p(t.getUTCDate()),
    hh: p(t.getUTCHours()),
  };
}

/**
 * 把任意时间（ISO 字符串 / Date / 空）格式化为 UTC+8 显示：
 * `YYYY-MM-DD HH:mm (UTC+8)`。解析失败或未提供时用当前时间。
 */
function formatCnTime(input) {
  let d = input ? new Date(input) : new Date();
  if (isNaN(d.getTime())) d = new Date();
  const { yyyy, mm, dd, hh } = cnDateParts(d);
  const t = new Date(d.getTime() + CN_TZ_OFFSET_MS);
  const mi = String(t.getUTCMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi} (UTC+8)`;
}

/** 生成反馈 ID：fbk_<yyyymmdd>_<8位随机hex>（日期用 UTC+8） */
function makeFeedbackId() {
  const { yyyy, mm, dd } = cnDateParts(new Date());
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return `fbk_${yyyy}${mm}${dd}_${hex}`;
}

// ==================== Cache API 计数器（限流用） ====================
// 说明：Cache API 只能通过 caches.default 使用，且 key 必须是完整 URL 的 GET Request。
// 这里借用一个不会真实解析的内部域名（ratelimit.internal）作为计数器的命名空间。
// 本地 wrangler dev 环境可能不支持 Cache API，所有异常都被吞掉并按「计数 0」处理（fail-open），
// 保证开发调试不被卡死。

/** 读取计数器当前值；缓存未命中或出错时返回 0 */
async function cacheCounterGet(keyUrl) {
  try {
    const cache = caches.default;
    const hit = await cache.match(keyUrl);
    if (hit) {
      const data = await hit.json();
      const n = Number(data && data.count);
      return Number.isFinite(n) && n > 0 ? n : 0;
    }
  } catch (err) {
    console.error('cacheCounterGet 失败（忽略，按 0 处理）:', err && err.message);
  }
  return 0;
}

/**
 * 写入计数器新值（放进 ctx.waitUntil，不阻塞响应）。
 * @param {number} ttlSeconds 缓存 TTL，同时作为计数窗口的兜底过期时间
 */
function cacheCounterSet(ctx, keyUrl, count, ttlSeconds) {
  try {
    const cache = caches.default;
    const resp = new Response(JSON.stringify({ count, ts: Date.now() }), {
      headers: {
        'Content-Type': 'application/json',
        // Cache API 依据该响应头决定 TTL
        'Cache-Control': `max-age=${ttlSeconds}`,
      },
    });
    ctx.waitUntil(cache.put(keyUrl, resp));
  } catch (err) {
    console.error('cacheCounterSet 失败（忽略）:', err && err.message);
  }
}

// ==================== 请求体规范化 ====================

/**
 * 按接口契约规范化用户本地服务器 POST 过来的反馈 JSON。
 * 所有字符串 trim + 长度截断；type / severity 走白名单；
 * images 最多 3 张、单张 base64 ≤ 2.5MB、MIME 白名单。
 */
function normalizePayload(raw) {
  if (!raw || typeof raw !== 'object') raw = {};

  const type = TYPE_MAP[cleanStr(raw.type).toLowerCase()] ? cleanStr(raw.type).toLowerCase() : 'other';
  const severityRaw = cleanStr(raw.severity).toLowerCase();
  const severity = SEVERITY_MAP[severityRaw] ? severityRaw : ''; // 允许为空，为空时展示「未提供」

  const page = raw.page && typeof raw.page === 'object' ? raw.page : {};
  const envInfo = raw.env && typeof raw.env === 'object' ? raw.env : {};
  const client = raw.client && typeof raw.client === 'object' ? raw.client : {};
  const server = raw.server && typeof raw.server === 'object' ? raw.server : {};

  // ---- 截图规范化 ----
  const images = [];
  if (Array.isArray(raw.images)) {
    for (const item of raw.images) {
      if (images.length >= MAX_IMAGES) break; // 最多 3 张，多余丢弃
      if (!item || typeof item !== 'object') continue;
      const mime = cleanStr(item.mime).toLowerCase();
      const ext = ALLOWED_IMAGE_MIME[mime];
      if (!ext) continue; // MIME 不在白名单，丢弃
      let data = cleanStr(item.data);
      // 容错：如果前端误带了 data:image/xxx;base64, 前缀，剥掉它
      const prefixMatch = data.match(/^data:[^;,]*;base64,/i);
      if (prefixMatch) data = data.slice(prefixMatch[0].length);
      data = data.replace(/\s+/g, ''); // base64 中不应有空白字符
      if (!data) continue;
      if (data.length > MAX_IMAGE_B64_LENGTH) continue; // 单张超限，丢弃
      images.push({
        name: cleanStr(item.name, 100) || `screenshot.${ext}`,
        mime,
        ext,
        data,
      });
    }
  }

  return {
    type,
    severity,
    summary: cleanStr(raw.summary, 200),
    message: cleanStr(raw.message, 4000),
    expect: cleanStr(raw.expect, 1000),
    contact: cleanStr(raw.contact, 200),
    page: {
      path: cleanStr(page.path, 500),
      tab: cleanStr(page.tab, 100),
      title: cleanStr(page.title, 200),
      url: cleanStr(page.url, 1000),
    },
    env: {
      ua: cleanStr(envInfo.ua, 500),
      platform: cleanStr(envInfo.platform, 200),
      screen: cleanStr(envInfo.screen, 100),
      lang: cleanStr(envInfo.lang, 50),
      theme: cleanStr(envInfo.theme, 100),
      online: typeof envInfo.online === 'boolean' ? envInfo.online : null,
      touch: typeof envInfo.touch === 'boolean' ? envInfo.touch : null,
    },
    client: {
      appVersion: cleanStr(client.appVersion, 50),
      widgetVersion: cleanStr(client.widgetVersion, 50),
      installId: cleanStr(client.installId, 100),
      submittedAt: cleanStr(client.submittedAt, 100),
    },
    server: {
      installId: cleanStr(server.installId, 100),
      machineId: cleanStr(server.machineId, 32),
      python: cleanStr(server.python, 50),
      os: cleanStr(server.os, 200),
      port: Number.isFinite(Number(server.port)) ? Number(server.port) : null,
      access: cleanStr(server.access, 50),
      gitCommit: cleanStr(server.gitCommit, 64),
    },
    images,
  };
}

/** 匿名安装 ID：优先 client.installId，其次 server.installId */
function pickInstallId(f) {
  return f.client.installId || f.server.installId || '';
}

// ==================== GitHub：截图上传 + 建 Issue ====================

/** GitHub API 公共请求头 */
function githubHeaders(env) {
  return {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': SERVICE_NAME,
    'Content-Type': 'application/json',
  };
}

/**
 * 通过 Contents API 把一张截图（base64）上传到仓库。
 * 路径：{ASSET_DIR}/{yyyy}/{mm}/{feedbackId}-{序号}.{ext}
 * 返回可直接嵌入 Issue 的图片 URL（优先 download_url，取不到则拼 raw 地址）。
 * 单张失败由调用方捕获，不中断整体流程。
 */
async function uploadImageToGithub(env, feedbackId, image, index) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const assetDir = cleanStr(env.ASSET_DIR) || 'feedback-assets';
  const { yyyy, mm } = cnDateParts(new Date());
  const path = `${assetDir}/${yyyy}/${mm}/${feedbackId}-${index + 1}.${image.ext}`;

  const body = {
    message: `chore(feedback): 附件 ${feedbackId}`,
    content: image.data,
  };
  // 指定了 GITHUB_BRANCH 就提交到该分支；未指定则省略字段，走仓库默认分支
  if (cleanStr(env.GITHUB_BRANCH)) body.branch = cleanStr(env.GITHUB_BRANCH);

  const resp = await fetchWithTimeout(
    `https://api.github.com/repos/${owner}/${repo}/contents/${path}`,
    { method: 'PUT', headers: githubHeaders(env), body: JSON.stringify(body) }
  );
  if (!resp.ok) {
    throw new Error(`github_contents_upload_http_${resp.status}`);
  }
  const data = await resp.json().catch(() => ({}));
  // 优先用响应里的 download_url；取不到就自己拼 raw.githubusercontent.com 地址
  let url = data && data.content && data.content.download_url;
  if (!url) {
    url = `https://raw.githubusercontent.com/${owner}/${repo}/HEAD/${path}`;
  }
  return url;
}

/**
 * 组装 Issue 标题：`[反馈][{类型中文}] {摘要或正文首行}`
 * 摘要截断到 60 字并去掉换行，整体不超过 100 字符。
 */
function buildIssueTitle(f) {
  const typeCn = TYPE_MAP[f.type].cn;
  let headline = f.summary || f.message.split('\n')[0] || '';
  headline = stripBackticks(headline).replace(/\s+/g, ' ').trim();
  headline = truncate(headline, 60);
  let title = `[反馈][${typeCn}] ${headline}`.trim();
  return truncate(title, 100);
}

/**
 * 组装 Issue 标签：固定标签（env.ISSUE_LABEL，默认「用户反馈」）
 * ＋ 类型标签 ＋ 严重度标签（仅 high / blocker）。
 * 注意：这些标签需要先在仓库里手动创建，见 README；
 * 仓库里不存在某标签时 GitHub 会返回 422，createGithubIssue 里做了三级降级容错。
 */
function buildIssueLabels(env, f) {
  const base = cleanStr(env.ISSUE_LABEL) || '用户反馈';
  const labels = [base];
  const typeLabel = TYPE_MAP[f.type].label;
  if (typeLabel) labels.push(typeLabel);
  const sevLabel = f.severity ? SEVERITY_MAP[f.severity].label : '';
  if (sevLabel) labels.push(sevLabel);
  return labels;
}

/** 布尔值 → 中文展示（null 显示「未提供」） */
function boolCn(v) {
  if (v === true) return '是';
  if (v === false) return '否';
  return '未提供';
}

/** access 字段 → 中文展示 */
function accessCn(v) {
  if (v === 'lan') return '局域网';
  if (v === 'local') return '本机';
  return orNone(v);
}

/**
 * 生成 Issue 正文（Markdown）。
 * 安全处理：用户正文放在引用块里，所有反引号序列已被 stripBackticks 替换，
 * 表格单元格内的竖线/换行也做了清洗，避免注入 Markdown / HTML 或破坏表格。
 */
function buildIssueBody(f, feedbackId, imageUrls, failedImages) {
  const t = TYPE_MAP[f.type];
  const sevCn = f.severity ? SEVERITY_MAP[f.severity].cn : '未提供';
  const pageEntry = f.page.title || f.page.tab || '未提供';

  // 用户正文：逐行加 "> " 前缀放入引用块
  const messageQuote = f.message
    ? stripBackticks(f.message)
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n')
    : '> 未提供';

  const expectBlock = f.expect
    ? stripBackticks(f.expect)
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n')
    : '未提供';

  // ---- 截图区 ----
  let imagesSection;
  if (imageUrls.length === 0 && failedImages.length === 0) {
    imagesSection = '未提供';
  } else {
    const parts = imageUrls.map((url, i) => `![截图${i + 1}](${url})`);
    for (const idx of failedImages) {
      parts.push(`> ⚠️ 第 ${idx} 张截图上传失败，未包含在本 Issue 中。`);
    }
    imagesSection = parts.join('\n\n');
  }

  const installId = pickInstallId(f);
  const installIdShort = installId ? installId.slice(0, 8) : '未提供';
  const serverLine =
    f.server.python || f.server.port
      ? `Python ${orNone(f.server.python)} @ :${f.server.port === null ? '未提供' : f.server.port}`
      : '未提供';
  const appVersionLine = f.client.appVersion
    ? `${sanitizeInline(f.client.appVersion)}${f.server.gitCommit ? ` (commit ${sanitizeInline(f.server.gitCommit)})` : ''}`
    : '未提供';

  return `> 本 Issue 由「成长家园」应用内反馈通道自动创建。反馈 ID：\`${feedbackId}\`

## 📝 用户说了什么
${messageQuote}

## 🎯 期望效果
${expectBlock}

## 🏷️ 分类
| 类型 | 严重程度 | 入口页面 |
|---|---|---|
| ${t.emoji} ${t.cn} | ${sevCn} | ${sanitizeInline(pageEntry)} |

## 📍 页面上下文
| 项 | 值 |
|---|---|
| 页面路径 | \`${sanitizeInline(f.page.path) || '未提供'}\` |
| 页面标题 | ${sanitizeInline(f.page.title) || '未提供'} |
| 门户标签 | ${sanitizeInline(f.page.tab) || '未提供'} |
| 完整 URL | ${sanitizeInline(f.page.url) || '未提供'} |

## 🖥️ 运行环境
| 项 | 值 |
|---|---|
| 设备/系统 | ${sanitizeInline(f.server.os || f.env.platform) || '未提供'} |
| 浏览器 UA | ${sanitizeInline(f.env.ua) || '未提供'} |
| 屏幕 | ${sanitizeInline(f.env.screen) || '未提供'} |
| 语言 | ${sanitizeInline(f.env.lang) || '未提供'} |
| 主题皮肤 | ${sanitizeInline(f.env.theme) || '未提供'} |
| 网络在线 | ${boolCn(f.env.online)} |
| 触屏 | ${boolCn(f.env.touch)} |
| 访问方式 | ${accessCn(f.server.access)} |
| 本地服务器 | ${sanitizeInline(serverLine)}${f.server.machineId ? `（设备指纹 ${sanitizeInline(f.server.machineId)}）` : ''} |
| 应用版本 | ${appVersionLine} |
| 反馈组件版本 | ${sanitizeInline(f.client.widgetVersion) || '未提供'} |

## 👤 用户
| 匿名安装 ID | 首次提交时间 | 联系方式 |
|---|---|---|
| \`${installIdShort}\`（仅前 8 位，用于区分不同家庭，不含个人信息） | ${formatCnTime(f.client.submittedAt)} | ${sanitizeInline(f.contact) || '未提供'} |

## 📎 截图
${imagesSection}

## ✅ 处理进度
- [ ] 已确认可复现
- [ ] 已定位到技能/文件
- [ ] 已修复
- [ ] 已回复反馈用户
`;
}

/**
 * 创建 GitHub Issue，带标签三级降级容错：
 * GitHub 对不存在的 label 会返回 422，因此：
 *   1) 先尝试带全部 labels 创建；
 *   2) 若 422，退化为只带固定标签 env.ISSUE_LABEL；
 *   3) 再 422，则不带 labels 创建（标签可事后手动补）。
 */
async function createGithubIssue(env, title, body, labels) {
  const apiUrl = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/issues`;
  const attempt = async (useLabels) => {
    const payload = { title, body };
    if (useLabels && useLabels.length > 0) payload.labels = useLabels;
    return fetchWithTimeout(apiUrl, {
      method: 'POST',
      headers: githubHeaders(env),
      body: JSON.stringify(payload),
    });
  };

  let resp = await attempt(labels);
  if (resp.status === 422 && labels.length > 1) {
    console.error('建 Issue 返回 422（可能是标签不存在），降级为只用固定标签重试');
    resp = await attempt([cleanStr(env.ISSUE_LABEL) || '用户反馈']);
  }
  if (resp.status === 422) {
    console.error('建 Issue 仍返回 422，降级为不带标签重试');
    resp = await attempt([]);
  }
  if (!resp.ok) {
    throw new Error(`github_create_issue_http_${resp.status}`);
  }
  const data = await resp.json();
  return { issueUrl: data.html_url || '', issueNumber: data.number || null };
}

/**
 * GitHub 通道完整流程：截图串行上传 → 建 Issue → 每日计数器 +1。
 * 成功返回 { status:'created', issueUrl, issueNumber }。
 */
async function runGithubChannel(env, ctx, f, feedbackId, dayKey, dayCount) {
  // 1. 截图必须先于建 Issue 上传（Issue 正文要引用图片 URL），且串行执行，
  //    避免并发写同一仓库触发 GitHub 的冲突/限流。
  const imageUrls = [];
  const failedImages = []; // 记录失败截图的序号（从 1 开始），不中断整体流程
  for (let i = 0; i < f.images.length; i++) {
    try {
      const url = await uploadImageToGithub(env, feedbackId, f.images[i], i);
      imageUrls.push(url);
    } catch (err) {
      console.error(`截图 ${i + 1} 上传失败:`, err && err.message);
      failedImages.push(i + 1);
    }
  }

  // 2. 建 Issue
  const title = buildIssueTitle(f);
  const body = buildIssueBody(f, feedbackId, imageUrls, failedImages);
  const labels = buildIssueLabels(env, f);
  const result = await createGithubIssue(env, title, body, labels);

  // 3. 建 Issue 成功后，全局每日计数器 +1（不阻塞响应）
  cacheCounterSet(ctx, dayKey, dayCount + 1, 86400);

  return { status: 'created', issueUrl: result.issueUrl, issueNumber: result.issueNumber };
}

// ==================== 飞书：签名 + 富文本卡片 ====================

/**
 * 飞书自定义机器人签名校验算法（当 env.LARK_SECRET 非空时启用）：
 *   timestamp    = 当前秒级时间戳（字符串）
 *   stringToSign = timestamp + "\n" + secret
 *   把 stringToSign 作为 HMAC-SHA256 的【密钥】，对【空字符串】签名，结果 base64。
 * 用 Web Crypto 实现，无外部依赖。
 */
async function larkSign(secret, timestamp) {
  const enc = new TextEncoder();
  const stringToSign = `${timestamp}\n${secret}`;
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(stringToSign),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sigBuf = await crypto.subtle.sign('HMAC', key, enc.encode(''));
  return btoa(String.fromCharCode(...new Uint8Array(sigBuf)));
}

/** 组装飞书富文本卡片（interactive card） */
function buildLarkCard(f, feedbackId, issueUrl) {
  const t = TYPE_MAP[f.type];
  let headline = f.summary || f.message.split('\n')[0] || '';
  headline = truncate(headline.replace(/\s+/g, ' ').trim(), 40);
  const sevCn = f.severity ? SEVERITY_MAP[f.severity].cn : '未提供';
  const installId = pickInstallId(f);
  const pageLine = [f.page.tab, f.page.title].filter(Boolean).join('｜') || '未提供';

  const field = (label, value) => ({
    is_short: true,
    text: { tag: 'lark_md', content: `**${label}**\n${truncate(String(value || '未提供'), 120)}` },
  });

  const elements = [
    {
      tag: 'div',
      fields: [
        field('页面路径', f.page.path),
        field('门户标签', pageLine),
        field('设备/系统', f.server.os || f.env.platform),
        field('浏览器', f.env.ua),
        field('时间', formatCnTime(f.client.submittedAt)),
        field('匿名安装 ID', installId ? installId.slice(0, 8) : ''),
        field('严重程度', sevCn),
        field('联系方式', f.contact),
      ],
    },
    { tag: 'hr' },
    {
      tag: 'div',
      text: { tag: 'lark_md', content: `**用户反馈摘录**\n${truncate(f.message, 300) || '未提供'}` },
    },
  ];

  // 仅在成功拿到 issueUrl 时追加「在 GitHub 查看」按钮
  if (issueUrl) {
    elements.push({
      tag: 'action',
      actions: [
        {
          tag: 'button',
          text: { tag: 'plain_text', content: '在 GitHub 查看' },
          type: 'primary',
          url: issueUrl,
        },
      ],
    });
  }

  elements.push({
    tag: 'note',
    elements: [{ tag: 'plain_text', content: `反馈 ID：${feedbackId}` }],
  });

  return {
    config: { wide_screen_mode: true },
    header: {
      template: LARK_CARD_COLOR[f.type] || 'blue',
      title: { tag: 'plain_text', content: `${t.emoji} ${t.cn}｜${headline || '页面改进反馈'}` },
    },
    elements,
  };
}

/**
 * 推送飞书。飞书返回体里 code / StatusCode 非 0 视为失败。
 * 成功返回 { status:'sent' }，失败抛异常由上层捕获。
 */
async function runLarkChannel(env, f, feedbackId, issueUrl) {
  const body = {
    msg_type: 'interactive',
    card: buildLarkCard(f, feedbackId, issueUrl),
  };
  // 若配置了签名密钥，按飞书自定义机器人签名算法加签
  if (cleanStr(env.LARK_SECRET)) {
    const timestamp = String(Math.floor(Date.now() / 1000));
    body.timestamp = timestamp;
    body.sign = await larkSign(env.LARK_SECRET, timestamp);
  }

  const resp = await fetchWithTimeout(env.LARK_WEBHOOK, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  let code = 0;
  if (typeof data.code !== 'undefined') code = Number(data.code);
  else if (typeof data.StatusCode !== 'undefined') code = Number(data.StatusCode);
  if (!resp.ok || code !== 0) {
    // 错误详情只进日志，不回传给客户端
    console.error('飞书推送失败:', resp.status, JSON.stringify(data).slice(0, 500));
    throw new Error(`lark_send_failed_http_${resp.status}_code_${code}`);
  }
  return { status: 'sent' };
}

// ==================== 主入口 ====================

export default {
  async fetch(request, env, ctx) {
    try {
      const url = new URL(request.url);
      const method = request.method.toUpperCase();

      // ---- CORS 预检：任何路径的 OPTIONS 都返回 204 + 完整 CORS 头 ----
      if (method === 'OPTIONS') {
        return new Response(null, { status: 204, headers: CORS_HEADERS });
      }

      // ---- 健康检查 ----
      if (method === 'GET' && url.pathname === '/health') {
        return jsonResp({
          ok: true,
          service: SERVICE_NAME,
          // 只暴露「是否已配置」，不泄露任何密钥内容
          github: Boolean(env.GITHUB_TOKEN && env.GITHUB_OWNER && env.GITHUB_REPO),
          lark: Boolean(env.LARK_WEBHOOK),
        });
      }

      // ---- 反馈主逻辑 ----
      if (method === 'POST' && url.pathname === '/feedback') {
        return await handleFeedback(request, env, ctx);
      }

      // ---- 其它一律 404（同样是 JSON + CORS）----
      return jsonResp({ ok: false, error: 'not_found' }, 404);
    } catch (err) {
      // 兜底：任何未捕获异常都不向客户端泄露堆栈或密钥
      console.error('Worker 未捕获异常:', err);
      return jsonResp({ ok: false, error: 'internal_error', retry: true }, 500);
    }
  },
};

/**
 * POST /feedback 主流程。校验与防滥用严格按以下顺序执行：
 * 1) Content-Type 必须是 JSON        → 否则 415
 * 2) 原始 body ≤ 6 MB                → 否则 413
 * 3) X-App-Key 匹配（若配置了）       → 否则 403
 * 4) per-IP 每小时限流（Cache API）   → 超限 429
 * 5) 全局每日建 Issue 上限（Cache API）→ 超限不建 Issue 但仍推飞书，github:"capped"
 */
async function handleFeedback(request, env, ctx) {
  // ---- 1. Content-Type 校验 ----
  const contentType = (request.headers.get('Content-Type') || '').toLowerCase();
  if (!contentType.includes('application/json')) {
    return jsonResp({ ok: false, error: 'unsupported_media_type', retry: false }, 415);
  }

  // ---- 2. 体积上限（先看 Content-Length 快速拒绝，再读 body 二次确认）----
  const declaredLength = Number(request.headers.get('Content-Length') || 0);
  if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_LENGTH) {
    return jsonResp({ ok: false, error: 'payload_too_large', retry: false }, 413);
  }
  let rawBody;
  try {
    rawBody = await request.text();
  } catch (err) {
    console.error('读取请求体失败:', err && err.message);
    return jsonResp({ ok: false, error: 'bad_request', retry: false }, 400);
  }
  // 注意：rawBody.length 是 UTF-16 码元数，与字节数近似（中文场景略宽松），够用
  if (rawBody.length > MAX_BODY_LENGTH) {
    return jsonResp({ ok: false, error: 'payload_too_large', retry: false }, 413);
  }

  // ---- 3. 应用密钥校验 ----
  // 重要说明：RELAY_APP_KEY 会随分发出去的代码/配置公开，任何人都能拿到。
  // 它【不是真正的安全机制】，只是提高滥用门槛的混淆手段（挡住无脑扫描器和
  // 不看代码的人）。真正的兜底是后面的 per-IP 限流和每日 Issue 上限。
  if (cleanStr(env.RELAY_APP_KEY)) {
    const provided = request.headers.get('X-App-Key') || '';
    if (provided !== env.RELAY_APP_KEY) {
      return jsonResp({ ok: false, error: 'forbidden', retry: false }, 403);
    }
  }

  // ---- 解析 + 规范化 ----
  let payload;
  try {
    payload = JSON.parse(rawBody);
  } catch (err) {
    return jsonResp({ ok: false, error: 'invalid_json', retry: false }, 400);
  }
  const f = normalizePayload(payload);
  if (!f.message) {
    // message 是契约里唯一的必填字段
    return jsonResp({ ok: false, error: 'message_required', retry: false }, 400);
  }

  const feedbackId = makeFeedbackId();
  const { yyyy, mm, dd, hh } = cnDateParts(new Date());

  // ---- 4. per-IP 每小时限流（Cache API 计数器）----
  const clientIp = request.headers.get('CF-Connecting-IP') || 'unknown';
  const rateLimit = Number(env.RATE_LIMIT_PER_HOUR) > 0 ? Number(env.RATE_LIMIT_PER_HOUR) : 10;
  const ipKey = `https://ratelimit.internal/${encodeURIComponent(clientIp)}/${yyyy}${mm}${dd}${hh}`;
  const ipCount = await cacheCounterGet(ipKey);
  if (ipCount >= rateLimit) {
    return jsonResp({ ok: false, error: 'rate_limited', retry: true }, 429);
  }
  // 通过校验即计数 +1（TTL 3600 秒，小时桶自然滚动）
  cacheCounterSet(ctx, ipKey, ipCount + 1, 3600);

  // ---- 5. 全局每日建 Issue 上限 ----
  const githubReady = Boolean(
    cleanStr(env.GITHUB_TOKEN) && cleanStr(env.GITHUB_OWNER) && cleanStr(env.GITHUB_REPO)
  );
  const dailyCap = Number(env.DAILY_ISSUE_CAP) > 0 ? Number(env.DAILY_ISSUE_CAP) : 20;
  const dayKey = `https://ratelimit.internal/daily-issues/${yyyy}${mm}${dd}`;
  let dayCount = 0;
  let githubCapped = false;
  if (githubReady) {
    dayCount = await cacheCounterGet(dayKey);
    // 超过每日上限：不再建 Issue，但飞书照常推送，响应里 github:"capped"
    githubCapped = dayCount >= dailyCap;
  }

  // ---- 执行两个通道，用 Promise.allSettled 收集结果（GitHub 内部：截图串行上传 → 建 Issue）----
  // 说明：飞书卡片底部需要在拿到 issueUrl 时追加「在 GitHub 查看」按钮，
  // 因此飞书通道挂在 GitHub 通道的落定结果之后启动（then 的两个分支分别处理
  // GitHub 成功/失败，GitHub 失败绝不会阻塞飞书发送），整体仍由 allSettled 收集，
  // 任何一个通道的异常都不会影响另一个通道的结果上报。
  const githubTask = githubReady
    ? githubCapped
      ? Promise.resolve({ status: 'capped' })
      : runGithubChannel(env, ctx, f, feedbackId, dayKey, dayCount)
    : Promise.resolve({ status: 'skipped' });
  const larkTask = cleanStr(env.LARK_WEBHOOK)
    ? githubTask.then(
        (gh) => runLarkChannel(env, f, feedbackId, gh.status === 'created' ? gh.issueUrl || null : null),
        () => runLarkChannel(env, f, feedbackId, null)
      )
    : Promise.resolve({ status: 'skipped' });

  const [ghResult, larkResult] = await Promise.allSettled([githubTask, larkTask]);

  const githubStatus = ghResult.status === 'fulfilled' ? ghResult.value.status : 'failed';
  const larkStatus = larkResult.status === 'fulfilled' ? larkResult.value.status : 'failed';
  if (ghResult.status === 'rejected') {
    console.error('GitHub 通道失败:', ghResult.reason && ghResult.reason.message);
  }
  if (larkResult.status === 'rejected') {
    console.error('飞书通道失败:', larkResult.reason && larkResult.reason.message);
  }

  const delivered = [];
  const failed = [];
  if (githubStatus === 'created') delivered.push('github');
  else if (githubStatus === 'failed') failed.push('github');
  if (larkStatus === 'sent') delivered.push('lark');
  else if (larkStatus === 'failed') failed.push('lark');

  const issueUrl = ghResult.status === 'fulfilled' ? ghResult.value.issueUrl || null : null;
  const issueNumber = ghResult.status === 'fulfilled' ? ghResult.value.issueNumber ?? null : null;

  // ---- 全部（尝试过的）通道都失败：502，允许客户端重试 ----
  if (delivered.length === 0 && failed.length > 0) {
    return jsonResp(
      {
        ok: false,
        error: 'all_channels_failed',
        retry: true,
        id: feedbackId,
        // detail 只放通道状态，不含任何错误堆栈/密钥
        detail: { github: githubStatus, lark: larkStatus },
      },
      502
    );
  }

  // ---- 成功或部分成功：ok:true；部分失败时 retry:false，避免客户端重试造成重复推送 ----
  return jsonResp({
    ok: true,
    id: feedbackId,
    issueUrl,
    issueNumber,
    delivered,
    failed,
    retry: false,
    github: githubStatus,
    lark: larkStatus,
  });
}
