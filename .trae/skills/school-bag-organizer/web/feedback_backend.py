# -*- coding: utf-8 -*-
"""用户反馈本地后端（供各技能的 preview_server.py 复用）。

数据流（完整通道）：
  浏览器 feedback.js → 本地 Python 服务器 /api/feedback（本模块）
  → 落盘到 data/feedback/inbox/ → 转发到公网中转服务 feedback-relay/
  → 自动建 GitHub Issue + 推送飞书。

隐私与 opt-in 设计：
- 中转服务地址（relay.url）默认留空；留空时反馈只存本机，绝不外发。
- 只在部署者主动填好 relay.url（并部署 feedback-relay）后才会外发。
- 匿名安装 ID 为随机 UUID，不含任何个人信息；主机指纹是 SHA-256 不可逆前 8 位。
- 反馈正文、可选截图由用户主动提交；本模块不额外采集姓名/学校等信息。
"""
import base64
import hashlib
import hmac
import json
import os
import platform
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 3
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
FORWARD_TIMEOUT = 12
RETRY_INTERVAL = 300
MAX_RETRY_DAYS = 30
MAX_RECORDS = 300
RATE_WINDOW = 600
RATE_LIMIT = 6


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class FeedbackBackend:
    """每个技能实例化一个：传入技能根目录、端口与显示名。"""

    def __init__(self, skill_root, port, app_name):
        self.skill_root = skill_root
        self.port = port
        self.app_name = app_name
        # 技能根目录 = <repo>/.trae/skills/<skill>；向上三层到仓库根目录
        self.workspace_root = os.path.dirname(os.path.dirname(os.path.dirname(skill_root)))
        self.feedback_dir = os.path.join(skill_root, "data", "feedback")
        self.inbox = os.path.join(self.feedback_dir, "inbox")
        self.channels_file = os.path.join(skill_root, "data", "feedback_channels.json")
        self.channels_template = os.path.join(skill_root, "data-templates", "feedback_channels.json")
        self.version_file = os.path.join(self.workspace_root, "VERSION")
        self._lock = threading.Lock()
        self._rate_hits = []
        self._meta_cache = {"at": 0, "data": None}

    # ---------- 基础 ----------
    def _now_iso(self):
        return datetime.now(CN_TZ).isoformat(timespec="seconds")

    def load_channels(self):
        cfg = _load_json(self.channels_file)
        if cfg is None:
            cfg = _load_json(self.channels_template)
        if not isinstance(cfg, dict):
            cfg = {}
        cfg.setdefault("relay", {})
        cfg.setdefault("lark", {})
        cfg.setdefault("enabled", True)
        return cfg

    def get_install_id(self):
        os.makedirs(self.feedback_dir, exist_ok=True)
        path = os.path.join(self.feedback_dir, "install.json")
        data = _load_json(path)
        if isinstance(data, dict) and data.get("installId"):
            return data["installId"]
        iid = str(uuid.uuid4())
        try:
            _write_json(path, {"installId": iid, "createdAt": self._now_iso()})
        except Exception:
            pass
        return iid

    def get_git_commit(self):
        try:
            head = os.path.join(self.workspace_root, ".git", "HEAD")
            if not os.path.isfile(head):
                return ""
            with open(head, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("ref:"):
                ref_path = os.path.join(self.workspace_root, ".git", content[4:].strip())
                if os.path.isfile(ref_path):
                    with open(ref_path, "r", encoding="utf-8") as f:
                        return f.read().strip()[:12]
                return ""
            return content[:12]
        except Exception:
            return ""

    def machine_fingerprint(self):
        try:
            raw = "%s|%s|%s" % (socket.gethostname(), platform.machine(), platform.system())
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        except Exception:
            return ""

    def get_app_meta(self):
        with self._lock:
            if self._meta_cache["data"] and time.time() - self._meta_cache["at"] < 60:
                return self._meta_cache["data"]
        version = ""
        try:
            if os.path.isfile(self.version_file):
                with open(self.version_file, "r", encoding="utf-8") as f:
                    version = f.read().strip().splitlines()[0].strip()
        except Exception:
            version = ""
        meta = {
            "appVersion": version,
            "gitCommit": self.get_git_commit(),
            "python": "%d.%d.%d" % sys.version_info[:3],
            "os": "%s %s" % (platform.system(), platform.release()),
            "machineId": self.machine_fingerprint(),
            "port": self.port,
        }
        with self._lock:
            self._meta_cache["data"] = meta
            self._meta_cache["at"] = time.time()
        return meta

    def config_payload(self):
        ch = self.load_channels()
        relay = ch.get("relay") or {}
        return {
            "enabled": bool(ch.get("enabled", True)),
            "installId": self.get_install_id(),
            "relayUrl": relay.get("url") or "",
            "relayConfigured": bool(relay.get("url")),
            "serverAvailable": True,
            "pendingCount": self.count_pending(),
            **{k: v for k, v in self.get_app_meta().items()},
        }

    # ---------- 清洗 ----------
    @staticmethod
    def _sanitize_text(val, limit):
        if not isinstance(val, str):
            return ""
        return val.strip()[:limit]

    def normalize_payload(self, raw, client_ip):
        if not isinstance(raw, dict):
            raise ValueError("反馈格式不对")
        message = self._sanitize_text(raw.get("message"), 4000)
        if len(message) < 2:
            raise ValueError("反馈内容太短")

        ftype = raw.get("type")
        if ftype not in ("feature", "usability", "bug", "other"):
            ftype = "other"
        severity = raw.get("severity")
        if severity not in ("low", "medium", "high", "blocker"):
            severity = ""

        page = raw.get("page") if isinstance(raw.get("page"), dict) else {}
        envd = raw.get("env") if isinstance(raw.get("env"), dict) else {}
        client = raw.get("client") if isinstance(raw.get("client"), dict) else {}

        images = []
        for img in (raw.get("images") or [])[:MAX_IMAGES]:
            if not isinstance(img, dict):
                continue
            mime = str(img.get("mime") or "")
            data = re.sub(r"\s+", "", str(img.get("data") or ""))
            if data.startswith("data:"):
                data = data.split(",", 1)[-1]
            if mime not in ALLOWED_MIME or not data or len(data) > 3_500_000:
                continue
            try:
                base64.b64decode(data[:64], validate=True)
            except Exception:
                continue
            images.append({
                "name": self._sanitize_text(img.get("name"), 80) or "screenshot.jpg",
                "mime": mime,
                "data": data,
            })

        install_id = self._sanitize_text(client.get("installId"), 80) or self.get_install_id()
        return {
            "type": ftype,
            "summary": self._sanitize_text(raw.get("summary"), 120),
            "message": message,
            "expect": self._sanitize_text(raw.get("expect"), 1000),
            "severity": severity,
            "contact": self._sanitize_text(raw.get("contact"), 200),
            "page": {
                "path": self._sanitize_text(page.get("path"), 300),
                "title": self._sanitize_text(page.get("title"), 120),
                "tab": self._sanitize_text(page.get("tab"), 60),
                "skill": self.app_name,
                "url": self._sanitize_text(page.get("url"), 400),
                "via": self._sanitize_text(page.get("via"), 200),
            },
            "env": {
                "ua": self._sanitize_text(envd.get("ua"), 400),
                "platform": self._sanitize_text(envd.get("platform"), 80),
                "screen": self._sanitize_text(envd.get("screen"), 40),
                "viewport": self._sanitize_text(envd.get("viewport"), 40),
                "lang": self._sanitize_text(envd.get("lang"), 40),
                "theme": self._sanitize_text(envd.get("theme"), 60),
                "online": bool(envd.get("online", True)),
                "touch": bool(envd.get("touch", False)),
            },
            "images": images,
            "client": {
                "appVersion": self._sanitize_text(client.get("appVersion"), 40),
                "widgetVersion": self._sanitize_text(client.get("widgetVersion"), 40),
                "installId": install_id,
                "submittedAt": self._sanitize_text(client.get("submittedAt"), 60) or self._now_iso(),
            },
            "server": dict(
                self.get_app_meta(),
                installId=install_id,
                access=("localhost" if self._is_local(client_ip) else "lan"),
            ),
        }

    @staticmethod
    def _is_local(ip):
        return ip in ("127.0.0.1", "::1", "localhost") or str(ip).startswith("127.")

    # ---------- 落盘 ----------
    def new_feedback_id(self):
        return "fbk_%s_%s" % (datetime.now(CN_TZ).strftime("%Y%m%d"), uuid.uuid4().hex[:8])

    def save_record(self, record):
        os.makedirs(self.inbox, exist_ok=True)
        path = os.path.join(self.inbox, record["id"] + ".json")
        _write_json(path, record)
        self.prune_records()
        return path

    def prune_records(self):
        try:
            files = sorted(
                (os.path.join(self.inbox, f) for f in os.listdir(self.inbox) if f.endswith(".json")),
                key=os.path.getmtime,
            )
            for old in files[:-MAX_RECORDS]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    def list_records(self):
        out = []
        if not os.path.isdir(self.inbox):
            return out
        for name in sorted(os.listdir(self.inbox)):
            if not name.endswith(".json"):
                continue
            rec = _load_json(os.path.join(self.inbox, name))
            if isinstance(rec, dict):
                out.append(rec)
        out.sort(key=lambda r: r.get("receivedAt") or "", reverse=True)
        return out

    def count_pending(self):
        return sum(1 for r in self.list_records() if (r.get("delivery") or {}).get("state") == "pending")

    # ---------- 转发 ----------
    def _post_json(self, url, body, headers=None, timeout=FORWARD_TIMEOUT):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("User-Agent", "GrowthHome-Feedback/1.0")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(text) if text else {}
                except Exception:
                    return resp.status, {"raw": text[:300]}
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

    def _rate_limited(self):
        now = time.time()
        while self._rate_hits and now - self._rate_hits[0] > RATE_WINDOW:
            self._rate_hits.pop(0)
        if len(self._rate_hits) >= RATE_LIMIT:
            return True
        self._rate_hits.append(now)
        return False

    @staticmethod
    def _lark_sign(secret):
        ts = str(int(time.time()))
        string_to_sign = "%s\n%s" % (ts, secret)
        digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
        return ts, base64.b64encode(digest).decode("utf-8")

    def _push_lark(self, webhook, secret, text):
        body = {"msg_type": "text", "content": {"text": text}}
        if secret:
            ts, sign = self._lark_sign(secret)
            body["timestamp"] = ts
            body["sign"] = sign
        status, resp = self._post_json(webhook, body, timeout=8)
        code = resp.get("code", resp.get("StatusCode", 0)) if isinstance(resp, dict) else -1
        return status == 200 and code == 0

    def forward_record(self, record):
        ch = self.load_channels()
        if not ch.get("enabled", True):
            return False, {"skipped": "disabled"}
        relay = ch.get("relay") or {}
        url = (relay.get("url") or "").strip()
        lark = ch.get("lark") or {}

        if not url and not lark.get("webhook"):
            return False, {"relayError": "未配置中转服务地址"}

        if self._rate_limited():
            return False, {"error": "rate_limited", "retryAfter": RATE_WINDOW}

        delivered, failed, result = [], [], {}

        if url:
            headers = {}
            if relay.get("appKey"):
                headers["X-App-Key"] = str(relay["appKey"])
            try:
                status, resp = self._post_json(url, record.get("payload", {}), headers=headers)
                if status == 200 and isinstance(resp, dict) and resp.get("ok"):
                    delivered.append("relay")
                    result["issueUrl"] = resp.get("issueUrl") or ""
                    result["issueNumber"] = resp.get("issueNumber")
                    result["relay"] = {k: resp.get(k) for k in ("github", "lark", "delivered", "failed") if k in resp}
                    result["relayId"] = resp.get("id")
                else:
                    failed.append("relay")
                    result["relayError"] = "HTTP %s %s" % (status, json.dumps(resp, ensure_ascii=False)[:200])
            except Exception as e:
                failed.append("relay")
                result["relayError"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        else:
            result["relayError"] = "未配置中转服务地址"

        if lark.get("webhook"):
            try:
                p = record.get("payload", {})
                text = "【%s反馈】%s\n页面：%s %s\n内容：%s\n时间：%s\n匿名ID：%s" % (
                    self.app_name, p.get("type", ""), (p.get("page") or {}).get("title", ""),
                    (p.get("page") or {}).get("path", ""), (p.get("message") or "")[:200],
                    self._now_iso(), str((p.get("client") or {}).get("installId", ""))[:8],
                )
                if self._push_lark(lark["webhook"], lark.get("secret"), text):
                    delivered.append("lark")
                else:
                    failed.append("lark")
            except Exception as e:
                failed.append("lark")
                result["larkError"] = "%s: %s" % (type(e).__name__, str(e)[:160])

        ok = bool(delivered)
        result["delivered"] = delivered
        result["failed"] = failed
        return ok, result

    def update_delivery(self, record, ok, result):
        d = record.setdefault("delivery", {})
        d["attempts"] = int(d.get("attempts", 0)) + 1
        d["lastAttemptAt"] = self._now_iso()
        d["lastResult"] = result
        if ok:
            d["state"] = "sent"
            d["sentAt"] = self._now_iso()
            if result.get("issueUrl"):
                d["issueUrl"] = result["issueUrl"]
            d.pop("lastError", None)
        else:
            d["state"] = "pending"
            d["lastError"] = result.get("relayError") or result.get("larkError") or json.dumps(result, ensure_ascii=False)[:200]
            if result.get("retryAfter"):
                d["retryAfter"] = (datetime.now(CN_TZ) + timedelta(seconds=int(result["retryAfter"]))).isoformat(timespec="seconds")
        try:
            self.save_record(record)
        except Exception:
            pass
        return d

    def retry_pending_once(self):
        sent = 0
        cutoff = (datetime.now(CN_TZ) - timedelta(days=MAX_RETRY_DAYS)).isoformat(timespec="seconds")
        for rec in self.list_records():
            d = rec.get("delivery") or {}
            if d.get("state") != "pending":
                continue
            if (rec.get("receivedAt") or "") < cutoff:
                d.update(state="expired")
                try:
                    self.save_record(rec)
                except Exception:
                    pass
                continue
            if d.get("retryAfter") and d["retryAfter"] > self._now_iso():
                continue
            if int(d.get("attempts", 0)) >= 30:
                continue
            try:
                ok, result = self.forward_record(rec)
            except Exception as e:
                ok, result = False, {"relayError": "%s: %s" % (type(e).__name__, str(e)[:160])}
            self.update_delivery(rec, ok, result)
            if ok:
                sent += 1
            time.sleep(0.4)
        return sent

    def retry_loop(self):
        while True:
            time.sleep(RETRY_INTERVAL)
            try:
                n = self.retry_pending_once()
                if n:
                    print("  📮 反馈补发成功 %d 条" % n)
            except Exception:
                pass

    # ---------- HTTP 入口 ----------
    def handle_post(self, raw_body, client_ip):
        try:
            raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
        except Exception:
            return 400, {"ok": False, "error": "bad_json"}
        try:
            payload = self.normalize_payload(raw, client_ip)
        except ValueError as e:
            return 400, {"ok": False, "error": str(e)}

        record = {
            "id": self.new_feedback_id(),
            "receivedAt": self._now_iso(),
            "payload": payload,
            "delivery": {"state": "pending", "attempts": 0},
        }
        try:
            self.save_record(record)
        except Exception as e:
            return 500, {"ok": False, "error": "本地保存失败: %s" % e}

        try:
            ok, result = self.forward_record(record)
        except Exception as e:
            ok, result = False, {"relayError": "%s: %s" % (type(e).__name__, str(e)[:160])}
        d = self.update_delivery(record, ok, result)

        if ok:
            return 200, {
                "ok": True, "id": record["id"], "queued": False,
                "issueUrl": d.get("issueUrl", ""),
                "issueNumber": (result or {}).get("issueNumber"),
                "delivered": result.get("delivered", []),
                "failed": result.get("failed", []),
                "message": "已送达",
            }
        return 200, {
            "ok": True, "id": record["id"], "queued": True,
            "delivered": [], "failed": result.get("failed", []),
            "message": "已存到本机，联网后自动补发",
            "reason": (result.get("relayError") or "")[:200],
        }

    def status_payload(self):
        recs = self.list_records()[:50]
        slim = []
        for r in recs:
            d = r.get("delivery") or {}
            p = r.get("payload") or {}
            slim.append({
                "id": r.get("id"),
                "receivedAt": r.get("receivedAt"),
                "type": p.get("type"),
                "page": (p.get("page") or {}).get("title"),
                "state": d.get("state"),
                "attempts": d.get("attempts"),
                "issueUrl": d.get("issueUrl", ""),
                "lastError": d.get("lastError", ""),
            })
        return {"count": len(slim), "pending": self.count_pending(), "records": slim}
