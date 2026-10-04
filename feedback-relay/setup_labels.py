"""在 GitHub 仓库里一次性建好反馈所需的标签。

为什么需要：中转服务建 Issue 时会带上分类标签，但 GitHub 的 Issue 接口
不会自动创建不存在的标签（会返回 422）。中转服务对此有降级处理（退化成
只带主标签、再不行就不带标签），但标签齐全时你在 Issue 列表里一眼就能分类。

用法（PowerShell）：
    $env:GITHUB_TOKEN = "ghp_xxx"          # 或 ghp_/github_pat_ 开头的令牌
    python feedback-relay/setup_labels.py --owner 你的用户名 --repo 你的仓库名

也可以直接把 token 写在参数里（不推荐，会留在命令历史里）：
    python feedback-relay/setup_labels.py --owner xxx --repo yyy --token ghp_zzz

脚本是幂等的：标签已存在就更新颜色和描述，不存在才创建。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"

# 名字 -> (颜色, 说明)。颜色与 feedback-relay/README.md 中的清单保持一致。
LABELS = {
    "用户反馈": ("0E8A16", "来自应用内「提建议」入口的用户反馈（中转服务自动打）"),
    "建议-新功能": ("A2EEEF", "用户希望新增的功能"),
    "体验-不好用": ("FBCA04", "功能有，但用起来别扭"),
    "Bug-错误": ("D73A4A", "点了没反应、显示不对、报错"),
    "其他-反馈": ("D4C5F9", "不属于以上分类的反馈"),
    "优先级-高": ("E99695", "用户标记为「很难用」"),
    "优先级-阻塞": ("B60205", "用户标记为「完全用不了」"),
}


def call(method, url, token, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "shan-learn-setup-labels")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(text) if text else {})
    except urllib.error.HTTPError as e:
        text = ""
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            return e.code, json.loads(text) if text else {}
        except Exception:
            return e.code, {"raw": text[:300]}
    except Exception as e:
        return 0, {"error": "%s: %s" % (type(e).__name__, e)}


def main():
    ap = argparse.ArgumentParser(description="为反馈 Issue 建好 GitHub 标签")
    ap.add_argument("--owner", required=True, help="GitHub 用户名或组织名")
    ap.add_argument("--repo", required=True, help="仓库名")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""),
                    help="GitHub 令牌，默认读环境变量 GITHUB_TOKEN")
    args = ap.parse_args()

    if not args.token:
        print("❌ 没有令牌。先执行：$env:GITHUB_TOKEN = \"ghp_xxx\"，或用 --token 传入。")
        return 2

    # 先确认仓库可访问，避免逐个标签报同样的错
    status, repo = call("GET", "%s/repos/%s/%s" % (API, args.owner, args.repo), args.token)
    if status != 200:
        print("❌ 读不到仓库 %s/%s（HTTP %s）" % (args.owner, args.repo, status))
        print("   %s" % json.dumps(repo, ensure_ascii=False)[:300])
        print("   常见原因：仓库名拼错、仓库还没建、令牌没有该仓库的权限。")
        return 1
    print("仓库确认：%s（%s）" % (repo.get("full_name"), "私有" if repo.get("private") else "公开"))

    created, updated, failed = [], [], []
    for name, (color, desc) in LABELS.items():
        quoted = urllib.parse.quote(name)
        base = "%s/repos/%s/%s/labels/%s" % (API, args.owner, args.repo, quoted)
        status, _ = call("GET", base, args.token)
        if status == 200:
            status, resp = call("PATCH", base, args.token, {"color": color, "description": desc})
            (updated if status == 200 else failed).append((name, status, resp))
            print("  ♻️  已存在，更新颜色  %s" % name)
        else:
            status, resp = call(
                "POST", "%s/repos/%s/%s/labels" % (API, args.owner, args.repo), args.token,
                {"name": name, "color": color, "description": desc})
            (created if status in (200, 201) else failed).append((name, status, resp))
            print("  ✅ 已创建            %s" % name if status in (200, 201)
                  else "  ❌ 创建失败(%s)    %s" % (status, name))

    print("\n新建 %d 个，更新 %d 个，失败 %d 个。" % (len(created), len(updated), len(failed)))
    if failed:
        for name, status, resp in failed:
            print("  ❌ %s -> HTTP %s %s" % (name, status, json.dumps(resp, ensure_ascii=False)[:200]))
        print("\n如果是 403/404，多半是令牌权限不够：需要 Issues 读写权限（细粒度令牌）或 repo（经典令牌）。")
        return 1
    print("标签齐了，中转服务建 Issue 时就能正常分类。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
