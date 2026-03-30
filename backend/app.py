
import base64
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BASE_DIR / "web"

SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT UNIQUE NOT NULL,
  agent_id TEXT NOT NULL,
  payee TEXT NOT NULL,
  amount REAL NOT NULL,
  purpose TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  callback_url TEXT,
  status TEXT NOT NULL,
  reason_code TEXT,
  nonce TEXT,
  issued_at TEXT,
  preauth_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  approved_at TEXT,
  executed_at TEXT,
  tx_id TEXT,
  approval_note TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  approval_flag TEXT NOT NULL,
  signature TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  agent_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  threshold REAL NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_account (
  id INTEGER PRIMARY KEY CHECK(id=1),
  total_balance REAL NOT NULL,
  protected_balance REAL NOT NULL,
  available_quota REAL NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_quotas (
  agent_id TEXT PRIMARY KEY,
  allocated_quota REAL NOT NULL,
  consumed_quota REAL NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_movements (
  movement_id TEXT PRIMARY KEY,
  movement_type TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  amount REAL NOT NULL,
  operator TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
  agent_id TEXT PRIMARY KEY,
  whitelist_json TEXT NOT NULL,
  single_limit REAL NOT NULL,
  daily_limit REAL NOT NULL,
  allowed_hours_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preauthorizations (
  preauth_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  total_amount REAL NOT NULL,
  remaining_amount REAL NOT NULL,
  starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  status TEXT NOT NULL,
  payee_whitelist_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_nonces (
  nonce TEXT PRIMARY KEY,
  issued_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_quota_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT UNIQUE NOT NULL,
  agent_id TEXT NOT NULL,
  delta_quota INTEGER NOT NULL,
  reason TEXT NOT NULL,
  request_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consumption_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id TEXT UNIQUE NOT NULL,
  request_id TEXT UNIQUE NOT NULL,
  agent_id TEXT NOT NULL,
  amount REAL NOT NULL,
  payee TEXT NOT NULL,
  purpose TEXT NOT NULL,
  tx_hash TEXT NOT NULL,
  tx_detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_challenges (
  request_id TEXT PRIMARY KEY,
  challenge TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE IF NOT EXISTS user_profiles (
  user_token TEXT PRIMARY KEY,
  mobile TEXT,
  mobile_bound INTEGER NOT NULL DEFAULT 0,
  id_card_no TEXT,
  id_card_bound INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connector_installs (
  install_id TEXT PRIMARY KEY,
  install_link TEXT NOT NULL,
  bind_token TEXT NOT NULL,
  bind_link TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  status TEXT NOT NULL,
  bound_agent_id TEXT,
  created_at TEXT NOT NULL,
  installed_at TEXT,
  confirmed_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_bindings (
  binding_id TEXT PRIMARY KEY,
  user_token TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  connector_install_id TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_token, agent_id)
);
"""

def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def money(v):
    return round(float(v), 2)


def parse_iso8601(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid iso8601")
    x = value.strip().replace("Z", "+00:00")
    x = re.sub(r"\.(\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r".\1", x)
    dt = datetime.fromisoformat(x)
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)


def parse_json_list(raw):
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except json.JSONDecodeError:
        return []


def _is_blocked_callback_ip(ip_text):
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def valid_callback(url):
    if not url:
        return None
    normalized = str(url).strip()
    u = urlparse(normalized)
    if u.scheme not in {"http", "https"} or not u.netloc:
        raise ValueError("callback_url must be valid http/https")
    hostname = (u.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("callback_url must contain a valid host")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise ValueError("callback_url localhost is not allowed")
    try:
        resolved = {item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise ValueError("callback_url host cannot be resolved")
    if not resolved:
        raise ValueError("callback_url host cannot be resolved")
    for ip_text in resolved:
        if _is_blocked_callback_ip(ip_text):
            raise ValueError("callback_url points to private/local network address")
    return normalized


def mask_with_edges(value, left, right):
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= left + right:
        return "*" * len(text)
    return f"{text[:left]}{'*' * (len(text)-left-right)}{text[-right:]}"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DB_PATH=str(BASE_DIR / "backend" / "aegis_mvp.db"),
        AGENT_TOKEN=os.getenv("AEGIS_AGENT_TOKEN", "dev-agent-token"),
        USER_TOKEN=os.getenv("AEGIS_USER_TOKEN", "dev-user-token"),
        INTERNAL_TOKEN=os.getenv("AEGIS_INTERNAL_TOKEN", "dev-internal-token"),
        CALLBACK_TIMEOUT_SECONDS=float(os.getenv("AEGIS_CALLBACK_TIMEOUT_SECONDS", "3")),
        INITIAL_TOTAL_BALANCE=float(os.getenv("AEGIS_INITIAL_TOTAL_BALANCE", "100")),
        INITIAL_AVAILABLE_QUOTA=float(os.getenv("AEGIS_INITIAL_AVAILABLE_QUOTA", "20")),
        DEFAULT_AGENT_THRESHOLD=float(os.getenv("AEGIS_DEFAULT_AGENT_THRESHOLD", "0.8")),
        DEFAULT_SINGLE_LIMIT=float(os.getenv("AEGIS_DEFAULT_SINGLE_LIMIT", "0.1")),
        DEFAULT_DAILY_LIMIT=float(os.getenv("AEGIS_DEFAULT_DAILY_LIMIT", "10")),
        API_QUOTA_PER_YUAN=int(os.getenv("AEGIS_API_QUOTA_PER_YUAN", "2000")),
        CHALLENGE_TTL_SECONDS=int(os.getenv("AEGIS_CHALLENGE_TTL_SECONDS", "120")),
        ALLOW_SIMULATED_BIO=(os.getenv("AEGIS_ALLOW_SIMULATED_BIO", "1") == "1"),
        REQUEST_MAX_AGE_SECONDS=int(os.getenv("AEGIS_REQUEST_MAX_AGE_SECONDS", "300")),
        REQUEST_FUTURE_TOLERANCE_SECONDS=int(os.getenv("AEGIS_REQUEST_FUTURE_TOLERANCE_SECONDS", "30")),
    )
    if test_config:
        app.config.update(test_config)

    lock = threading.Lock()

    def db():
        if "db" not in g:
            conn = sqlite3.connect(app.config["DB_PATH"], check_same_thread=False)
            conn.row_factory = sqlite3.Row
            g.db = conn
        return g.db

    @app.teardown_appcontext
    def close(_=None):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def ensure_column(conn, table_name, col_name, ddl_type):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if col_name not in cols:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {ddl_type}")

    def init_db():
        path = Path(app.config["DB_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        ensure_column(conn, "payment_requests", "reason_code", "TEXT")
        ensure_column(conn, "payment_requests", "nonce", "TEXT")
        ensure_column(conn, "payment_requests", "issued_at", "TEXT")
        ensure_column(conn, "payment_requests", "preauth_id", "TEXT")
        now = iso(utcnow())
        conn.execute(
            "INSERT OR IGNORE INTO agents(agent_id,name,status,threshold,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ("api_agent_001", "API采购Agent", "connected", app.config["DEFAULT_AGENT_THRESHOLD"], now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles(user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at) VALUES (?,?,?,?,?,?)",
            (app.config["USER_TOKEN"], "13800138000", 1, "110101199001011234", 1, now),
        )
        total = money(app.config["INITIAL_TOTAL_BALANCE"])
        available = min(total, money(app.config["INITIAL_AVAILABLE_QUOTA"]))
        protected = money(total - available)
        conn.execute(
            "INSERT OR IGNORE INTO quota_account(id,total_balance,protected_balance,available_quota,updated_at) VALUES (1,?,?,?,?)",
            (total, protected, available, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO agent_quotas(agent_id,allocated_quota,consumed_quota,updated_at) VALUES (?,?,?,?)",
            ("api_agent_001", available, 0.0, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO policies(agent_id,whitelist_json,single_limit,daily_limit,allowed_hours_json,updated_at) VALUES (?,?,?,?,?,?)",
            ("api_agent_001", json.dumps(["DeepSeek"], ensure_ascii=False), app.config["DEFAULT_SINGLE_LIMIT"], app.config["DEFAULT_DAILY_LIMIT"], json.dumps(list(range(24)), ensure_ascii=False), now),
        )
        conn.commit()
        conn.close()

    init_db()

    def req_dict(r):
        return {
            "request_id": r["request_id"], "agent_id": r["agent_id"], "payee": r["payee"], "amount": float(r["amount"]),
            "purpose": r["purpose"], "expires_at": r["expires_at"], "callback_url": r["callback_url"],
            "status": r["status"], "reason_code": r["reason_code"], "nonce": r["nonce"], "issued_at": r["issued_at"],
            "preauth_id": r["preauth_id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
            "approved_at": r["approved_at"], "executed_at": r["executed_at"], "tx_id": r["tx_id"], "approval_note": r["approval_note"],
        }

    def cons_dict(r):
        try:
            detail = json.loads(r["tx_detail_json"]) if r["tx_detail_json"] else {}
        except json.JSONDecodeError:
            detail = {"raw": r["tx_detail_json"]}
        return {
            "record_id": r["record_id"], "request_id": r["request_id"], "agent_id": r["agent_id"], "amount": float(r["amount"]),
            "payee": r["payee"], "purpose": r["purpose"], "tx_hash": r["tx_hash"], "tx_detail": detail, "created_at": r["created_at"],
        }

    def event(conn, req_id, typ, detail=None):
        conn.execute(
            "INSERT INTO events(request_id,event_type,event_detail,created_at) VALUES (?,?,?,?)",
            (req_id, typ, json.dumps(detail, ensure_ascii=False) if detail else None, iso(utcnow())),
        )

    def ok_agent():
        if request.headers.get("X-Agent-Token") != app.config["AGENT_TOKEN"]:
            return False, (jsonify({"error": "invalid agent token"}), 401)
        return True, ()

    def ok_user():
        if request.headers.get("X-User-Token") != app.config["USER_TOKEN"]:
            return False, (jsonify({"error": "invalid user token"}), 401)
        return True, ()

    def ok_internal():
        if request.headers.get("X-Internal-Token") != app.config["INTERNAL_TOKEN"]:
            return False, (jsonify({"error": "invalid internal token"}), 401)
        return True, ()

    def ok_agent_or_user():
        if request.headers.get("X-Agent-Token") == app.config["AGENT_TOKEN"]:
            return True, "agent", ()
        if request.headers.get("X-User-Token") == app.config["USER_TOKEN"]:
            return True, "user", ()
        return False, "", (jsonify({"error": "invalid token"}), 401)

    def quota_summary(conn):
        row = conn.execute("SELECT total_balance,protected_balance,available_quota,updated_at FROM quota_account WHERE id=1").fetchone()
        if row is None:
            now = iso(utcnow())
            conn.execute("INSERT INTO quota_account(id,total_balance,protected_balance,available_quota,updated_at) VALUES (1,0,0,0,?)", (now,))
            row = conn.execute("SELECT total_balance,protected_balance,available_quota,updated_at FROM quota_account WHERE id=1").fetchone()
        total = float(row["total_balance"])
        available = float(row["available_quota"])
        return {
            "total_balance": money(total),
            "protected_balance": money(row["protected_balance"]),
            "available_quota": money(available),
            "allocated_ratio_percent": round((available / total * 100), 2) if total > 0 else 0.0,
            "updated_at": row["updated_at"],
        }

    def ensure_agent(conn, agent_id, name=None):
        now = iso(utcnow())
        conn.execute("INSERT OR IGNORE INTO agents(agent_id,name,status,threshold,created_at,updated_at) VALUES (?,?,?,?,?,?)", (agent_id, name or agent_id, "connected", app.config["DEFAULT_AGENT_THRESHOLD"], now, now))
        conn.execute("INSERT OR IGNORE INTO agent_quotas(agent_id,allocated_quota,consumed_quota,updated_at) VALUES (?,?,?,?)", (agent_id, 0.0, 0.0, now))

    def ensure_policy(conn, agent_id):
        now = iso(utcnow())
        conn.execute("INSERT OR IGNORE INTO policies(agent_id,whitelist_json,single_limit,daily_limit,allowed_hours_json,updated_at) VALUES (?,?,?,?,?,?)", (agent_id, json.dumps([], ensure_ascii=False), app.config["DEFAULT_SINGLE_LIMIT"], app.config["DEFAULT_DAILY_LIMIT"], json.dumps(list(range(24)), ensure_ascii=False), now))

    def current_policy(conn, agent_id):
        ensure_policy(conn, agent_id)
        row = conn.execute("SELECT * FROM policies WHERE agent_id=?", (agent_id,)).fetchone()
        return {
            "agent_id": row["agent_id"],
            "whitelist": [str(x) for x in parse_json_list(row["whitelist_json"])],
            "single_limit": float(row["single_limit"]),
            "daily_limit": float(row["daily_limit"]),
            "allowed_hours": [int(x) for x in parse_json_list(row["allowed_hours_json"])],
            "updated_at": row["updated_at"],
        }

    def agent_available(conn, agent_id):
        row = conn.execute("SELECT allocated_quota,consumed_quota FROM agent_quotas WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            return 0.0
        return money(float(row["allocated_quota"]) - float(row["consumed_quota"]))

    def today_success_spend(conn, agent_id):
        row = conn.execute("SELECT COALESCE(SUM(amount),0) AS s FROM payment_requests WHERE agent_id=? AND status='SUCCESS' AND date(updated_at)=date('now')", (agent_id,)).fetchone()
        return money(row["s"] if row else 0)

    def current_api_quota(conn, agent_id):
        row = conn.execute("SELECT COALESCE(SUM(delta_quota),0) AS q FROM api_quota_ledger WHERE agent_id=?", (agent_id,)).fetchone()
        return int(row["q"] if row else 0)

    def hash_tx(req_id, agent_id, payee, amount, purpose, executed_at):
        raw = f"{req_id}|{agent_id}|{payee}|{amount:.2f}|{purpose}|{executed_at}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def validate_policy(conn, agent_id, payee, amount, now_dt):
        p = current_policy(conn, agent_id)
        if p["whitelist"] and payee not in p["whitelist"]:
            return False, "RULE_BLOCKED", "payee is not in whitelist"
        if amount > p["single_limit"]:
            return False, "RULE_BLOCKED", "amount exceeds single limit"
        if today_success_spend(conn, agent_id) + amount > p["daily_limit"]:
            return False, "RULE_BLOCKED", "amount exceeds daily limit"
        if p["allowed_hours"] and int(now_dt.hour) not in {int(x) for x in p["allowed_hours"]}:
            return False, "RULE_BLOCKED", "current hour is not allowed"
        return True, "", ""

    def expire_pending(conn):
        now = iso(utcnow())
        rows = conn.execute("SELECT request_id FROM payment_requests WHERE status='PENDING' AND expires_at < ?", (now,)).fetchall()
        if not rows:
            return
        ids = [r["request_id"] for r in rows]
        conn.execute(f"UPDATE payment_requests SET status='EXPIRED',reason_code='EXPIRED',updated_at=? WHERE request_id IN ({','.join(['?'] * len(ids))})", (now, *ids))
        for rid in ids:
            event(conn, rid, "REQUEST_EXPIRED", {"reason_code": "EXPIRED"})

    def expire_preauth(conn):
        now = iso(utcnow())
        conn.execute("UPDATE preauthorizations SET status='EXPIRED',updated_at=? WHERE status='ACTIVE' AND ends_at < ?", (now, now))

    def preauth_match(conn, agent_id, payee, amount, now_text):
        rows = conn.execute("SELECT * FROM preauthorizations WHERE agent_id=? AND status='ACTIVE' AND starts_at <= ? AND ends_at >= ? AND remaining_amount >= ? ORDER BY created_at", (agent_id, now_text, now_text, amount)).fetchall()
        for row in rows:
            wl = [str(x) for x in parse_json_list(row["payee_whitelist_json"])]
            if wl and payee not in wl:
                continue
            return row
        return None

    def list_agents(conn, user_token):
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
        bound_ids = {r["agent_id"] for r in conn.execute("SELECT agent_id FROM agent_bindings WHERE user_token=? AND status='BOUND'", (user_token,)).fetchall()}
        out = []
        for row in rows:
            req_row = conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE agent_id=? AND date(created_at)=date('now')", (row["agent_id"],)).fetchone()
            suc_row = conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE agent_id=? AND status='SUCCESS' AND date(updated_at)=date('now')", (row["agent_id"],)).fetchone()
            reqs = int(req_row["c"] if req_row else 0)
            succ = int(suc_row["c"] if suc_row else 0)
            avail = agent_available(conn, row["agent_id"])
            qrow = conn.execute("SELECT allocated_quota,consumed_quota FROM agent_quotas WHERE agent_id=?", (row["agent_id"],)).fetchone()
            allocated = money(qrow["allocated_quota"] if qrow else 0)
            consumed = money(qrow["consumed_quota"] if qrow else 0)
            out.append({
                "agent_id": row["agent_id"], "name": row["name"], "status": row["status"],
                "threshold": float(row["threshold"]), "today_requests": reqs, "today_success": succ,
                "today_success_rate": round((succ / reqs * 100), 2) if reqs else 0.0,
                "allocated_quota": allocated, "consumed_quota": consumed, "available_quota": avail,
                "current_api_quota": current_api_quota(conn, row["agent_id"]), "bound": row["agent_id"] in bound_ids,
                "created_at": row["created_at"], "updated_at": row["updated_at"],
            })
        return out

    def connector_status(conn):
        a = conn.execute("SELECT COUNT(*) AS c FROM connector_installs WHERE status='AWAITING_AGENT_INSTALL'").fetchone()["c"]
        u = conn.execute("SELECT COUNT(*) AS c FROM connector_installs WHERE status='AWAITING_USER_CONFIRM'").fetchone()["c"]
        b = conn.execute("SELECT COUNT(*) AS c FROM connector_installs WHERE status='BOUND'").fetchone()["c"]
        return {"awaiting_agent_install": int(a), "awaiting_user_confirm": int(u), "bound_total": int(b)}

    def create_auth_challenge(conn, request_id):
        challenge = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
        exp = iso(utcnow() + timedelta(seconds=app.config["CHALLENGE_TTL_SECONDS"]))
        conn.execute("INSERT INTO auth_challenges(request_id,challenge,expires_at,used_at) VALUES (?,?,?,NULL) ON CONFLICT(request_id) DO UPDATE SET challenge=excluded.challenge,expires_at=excluded.expires_at,used_at=NULL", (request_id, challenge, exp))
        return challenge

    def verify_assertion(conn, request_id, assertion):
        row = conn.execute("SELECT challenge,expires_at,used_at FROM auth_challenges WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return False, "biometric challenge not found"
        if row["used_at"]:
            return False, "biometric challenge already used"
        if parse_iso8601(row["expires_at"]) < utcnow():
            return False, "biometric challenge expired"
        response = assertion.get("response", {}) if isinstance(assertion, dict) else {}
        cdata_b64 = response.get("clientDataJSON")
        if not isinstance(cdata_b64, str) or not cdata_b64:
            return False, "invalid biometric assertion"
        pad = "=" * ((4 - len(cdata_b64) % 4) % 4)
        cdata = json.loads(base64.urlsafe_b64decode((cdata_b64 + pad).encode("ascii")).decode("utf-8"))
        if cdata.get("type") != "webauthn.get" or cdata.get("challenge") != row["challenge"]:
            return False, "biometric challenge mismatch"
        conn.execute("UPDATE auth_challenges SET used_at=? WHERE request_id=?", (iso(utcnow()), request_id))
        return True, "ok"

    def callback_for(req_row):
        if not req_row["callback_url"]:
            return
        payload = {"request_id": req_row["request_id"], "status": req_row["status"], "tx_id": req_row["tx_id"], "finished_at": req_row["executed_at"]}
        result = {"url": req_row["callback_url"], "ok": False}
        try:
            resp = requests.post(req_row["callback_url"], json=payload, timeout=app.config["CALLBACK_TIMEOUT_SECONDS"])
            result = {"url": req_row["callback_url"], "ok": resp.ok, "status_code": resp.status_code}
        except requests.RequestException as exc:
            result = {"url": req_row["callback_url"], "ok": False, "error": str(exc)}
        with lock:
            conn = db()
            event(conn, req_row["request_id"], "CALLBACK_ATTEMPTED", result)
            conn.commit()

    def execute(request_id, executor):
        conn = db()
        with lock:
            req = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
            if req is None:
                return {"error": "request not found"}, 404
            if req["status"] == "SUCCESS":
                return {"message": "already executed", "request": req_dict(req)}, 200
            if req["status"] != "APPROVED":
                return {"error": f"request status is {req['status']}, must be APPROVED"}, 409

            amount = float(req["amount"])
            q = quota_summary(conn)
            a_avail = agent_available(conn, req["agent_id"])
            if q["available_quota"] < amount or a_avail < amount:
                now = iso(utcnow())
                conn.execute("UPDATE payment_requests SET status='FAILED',reason_code='QUOTA_INSUFFICIENT',updated_at=?,approval_note=? WHERE request_id=?", (now, "insufficient available quota", request_id))
                event(conn, request_id, "PAYMENT_FAILED", {"reason_code": "QUOTA_INSUFFICIENT", "available_quota": q["available_quota"], "agent_available": a_avail, "required_amount": amount})
                conn.commit()
                failed = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
                return {"error": "insufficient available quota", "request": req_dict(failed)}, 409

            now = iso(utcnow())
            tx_id = f"sim_tx_{uuid.uuid4().hex[:12]}"
            total_after = money(q["total_balance"] - amount)
            available_after = money(q["available_quota"] - amount)
            conn.execute("UPDATE quota_account SET total_balance=?,available_quota=?,updated_at=? WHERE id=1", (total_after, available_after, now))
            conn.execute("UPDATE agent_quotas SET consumed_quota=consumed_quota+?,updated_at=? WHERE agent_id=?", (amount, now, req["agent_id"]))
            if req["preauth_id"]:
                conn.execute("UPDATE preauthorizations SET remaining_amount=MAX(0,remaining_amount-?),updated_at=? WHERE preauth_id=?", (amount, now, req["preauth_id"]))
                conn.execute("UPDATE preauthorizations SET status='EXHAUSTED',updated_at=? WHERE preauth_id=? AND remaining_amount <= 0.0001", (now, req["preauth_id"]))

            quota_delta = max(1, int(round(amount * app.config["API_QUOTA_PER_YUAN"])))
            tx_hash = hash_tx(req["request_id"], req["agent_id"], req["payee"], amount, req["purpose"], now)
            detail = {
                "tx_id": tx_id, "executor": executor, "quota_before": q,
                "quota_after": {"total_balance": total_after, "protected_balance": q["protected_balance"], "available_quota": available_after},
                "agent_available_before": a_avail, "agent_available_after": money(a_avail - amount),
                "api_quota_delta": quota_delta, "executed_at": now,
            }
            conn.execute("INSERT INTO api_quota_ledger(entry_id,agent_id,delta_quota,reason,request_id,created_at) VALUES (?,?,?,?,?,?)", (f"quota_{uuid.uuid4().hex[:12]}", req["agent_id"], quota_delta, "api_purchase", req["request_id"], now))
            conn.execute("INSERT INTO consumption_records(record_id,request_id,agent_id,amount,payee,purpose,tx_hash,tx_detail_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (f"cons_{uuid.uuid4().hex[:12]}", req["request_id"], req["agent_id"], amount, req["payee"], req["purpose"], tx_hash, json.dumps(detail, ensure_ascii=False), now))
            conn.execute("UPDATE payment_requests SET status='SUCCESS',reason_code='SUCCESS',tx_id=?,executed_at=?,updated_at=?,approval_note=? WHERE request_id=?", (tx_id, now, now, "executed from available quota", request_id))
            event(conn, request_id, "PAYMENT_EXECUTED", {"reason_code": "SUCCESS", "tx_id": tx_id, "tx_hash": tx_hash})
            conn.commit()
            updated = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()

        print(f"[PAYMENT_SUCCESS] request_id={updated['request_id']} amount={updated['amount']} payee={updated['payee']}")
        callback_for(updated)
        return {"message": "payment simulated successfully", "request": req_dict(updated)}, 200

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "time": iso(utcnow())}), 200

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/<path:path>")
    def static_files(path):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        target = WEB_DIR / path
        if not target.exists():
            return jsonify({"error": "not found"}), 404
        return send_from_directory(WEB_DIR, path)

    @app.post("/api/user/register")
    def user_register():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        mobile = str(payload.get("mobile", "")).strip()
        id_card = str(payload.get("id_card_no", "")).strip()
        now = iso(utcnow())
        conn = db()
        with lock:
            conn.execute(
                "INSERT INTO user_profiles(user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(user_token) DO UPDATE SET mobile=excluded.mobile,mobile_bound=excluded.mobile_bound,id_card_no=excluded.id_card_no,id_card_bound=excluded.id_card_bound,updated_at=excluded.updated_at",
                (app.config["USER_TOKEN"], mobile or None, 1 if mobile else 0, id_card or None, 1 if id_card else 0, now),
            )
            conn.commit()
        return jsonify({"message": "profile updated"}), 200

    @app.get("/api/user/profile")
    def get_user_profile():
        ok, err = ok_user()
        if not ok:
            return err
        token = request.headers.get("X-User-Token", "")
        conn = db()
        row = conn.execute("SELECT user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at FROM user_profiles WHERE user_token=?", (token,)).fetchone()
        if row is None:
            now = iso(utcnow())
            conn.execute("INSERT INTO user_profiles(user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at) VALUES (?,?,?,?,?,?)", (token, None, 0, None, 0, now))
            conn.commit()
            row = conn.execute("SELECT user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at FROM user_profiles WHERE user_token=?", (token,)).fetchone()
        bound = conn.execute("SELECT COUNT(*) AS c FROM agent_bindings WHERE user_token=? AND status='BOUND'", (token,)).fetchone()["c"]
        return jsonify({
            "mobile_bound": bool(row["mobile_bound"]),
            "mobile_masked": mask_with_edges(row["mobile"], 3, 4) if row["mobile_bound"] else "",
            "id_card_bound": bool(row["id_card_bound"]),
            "id_card_masked": mask_with_edges(row["id_card_no"], 6, 4) if row["id_card_bound"] else "",
            "bound_agents_count": int(bound),
            "connector_status": connector_status(conn),
            "updated_at": row["updated_at"],
        }), 200

    @app.get("/api/quota/summary")
    def quota_get():
        ok, err = ok_user()
        if not ok:
            return err
        return jsonify(quota_summary(db())), 200

    @app.post("/api/quota/allocate")
    def quota_allocate():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "api_agent_001")).strip() or "api_agent_001"
        try:
            amount = money(float(payload.get("amount", 0)))
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "invalid allocate amount"}), 400
        operator = str(payload.get("operator", "mobile_web_user")).strip() or "mobile_web_user"
        note = str(payload.get("note", "manual allocation")).strip()
        conn = db()
        with lock:
            ensure_agent(conn, agent_id)
            ensure_policy(conn, agent_id)
            q = quota_summary(conn)
            if q["protected_balance"] < amount:
                return jsonify({"error": "insufficient protected balance"}), 409
            now = iso(utcnow())
            conn.execute("UPDATE quota_account SET protected_balance=?,available_quota=?,updated_at=? WHERE id=1", (money(q["protected_balance"] - amount), money(q["available_quota"] + amount), now))
            conn.execute("UPDATE agent_quotas SET allocated_quota=allocated_quota+?,updated_at=? WHERE agent_id=?", (amount, now, agent_id))
            movement_id = f"mv_{uuid.uuid4().hex[:12]}"
            conn.execute("INSERT INTO quota_movements(movement_id,movement_type,agent_id,amount,operator,note,created_at) VALUES (?,?,?,?,?,?,?)", (movement_id, "ALLOCATE", agent_id, amount, operator, note, now))
            event(conn, f"quota::{movement_id}", "QUOTA_ALLOCATED", {"agent_id": agent_id, "amount": amount, "operator": operator})
            conn.commit()
        return jsonify({"message": "quota allocated", "movement_id": movement_id, "quota_summary": quota_summary(conn)}), 200

    @app.post("/api/quota/reclaim")
    def quota_reclaim():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "api_agent_001")).strip() or "api_agent_001"
        try:
            amount = money(float(payload.get("amount", 0)))
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "invalid reclaim amount"}), 400
        operator = str(payload.get("operator", "mobile_web_user")).strip() or "mobile_web_user"
        note = str(payload.get("note", "manual reclaim")).strip()
        conn = db()
        with lock:
            ensure_agent(conn, agent_id)
            q = quota_summary(conn)
            avail = agent_available(conn, agent_id)
            if avail < amount or q["available_quota"] < amount:
                return jsonify({"error": "insufficient available quota to reclaim"}), 409
            now = iso(utcnow())
            conn.execute("UPDATE quota_account SET protected_balance=?,available_quota=?,updated_at=? WHERE id=1", (money(q["protected_balance"] + amount), money(q["available_quota"] - amount), now))
            conn.execute("UPDATE agent_quotas SET allocated_quota=allocated_quota-?,updated_at=? WHERE agent_id=?", (amount, now, agent_id))
            movement_id = f"mv_{uuid.uuid4().hex[:12]}"
            conn.execute("INSERT INTO quota_movements(movement_id,movement_type,agent_id,amount,operator,note,created_at) VALUES (?,?,?,?,?,?,?)", (movement_id, "RECLAIM", agent_id, amount, operator, note, now))
            event(conn, f"quota::{movement_id}", "QUOTA_RECLAIMED", {"agent_id": agent_id, "amount": amount, "operator": operator})
            conn.commit()
        return jsonify({"message": "quota reclaimed", "movement_id": movement_id, "quota_summary": quota_summary(conn)}), 200

    @app.get("/api/policies")
    def policy_get():
        ok, err = ok_user()
        if not ok:
            return err
        agent_id = str(request.args.get("agent_id", "")).strip()
        conn = db()
        if agent_id:
            return jsonify({"policy": current_policy(conn, agent_id)}), 200
        rows = conn.execute("SELECT agent_id FROM policies ORDER BY agent_id").fetchall()
        return jsonify({"policies": [current_policy(conn, r["agent_id"]) for r in rows]}), 200

    @app.post("/api/policies")
    def policy_set():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400
        wl = payload.get("whitelist", [])
        hours = payload.get("allowed_hours", list(range(24)))
        if not isinstance(wl, list) or not isinstance(hours, list):
            return jsonify({"error": "whitelist and allowed_hours must be lists"}), 400
        try:
            single_limit = float(payload.get("single_limit", app.config["DEFAULT_SINGLE_LIMIT"]))
            daily_limit = float(payload.get("daily_limit", app.config["DEFAULT_DAILY_LIMIT"]))
            if single_limit <= 0 or daily_limit <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "invalid limits"}), 400
        norm_hours = sorted({int(h) for h in hours if isinstance(h, int) or str(h).isdigit()})
        norm_hours = [h for h in norm_hours if 0 <= h <= 23]
        if not norm_hours:
            return jsonify({"error": "allowed_hours cannot be empty"}), 400
        conn = db()
        with lock:
            ensure_agent(conn, agent_id)
            now = iso(utcnow())
            conn.execute(
                "INSERT INTO policies(agent_id,whitelist_json,single_limit,daily_limit,allowed_hours_json,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET whitelist_json=excluded.whitelist_json,single_limit=excluded.single_limit,daily_limit=excluded.daily_limit,allowed_hours_json=excluded.allowed_hours_json,updated_at=excluded.updated_at",
                (agent_id, json.dumps([str(x) for x in wl], ensure_ascii=False), single_limit, daily_limit, json.dumps(norm_hours, ensure_ascii=False), now),
            )
            event(conn, f"policy::{agent_id}", "POLICY_UPDATED", {"agent_id": agent_id})
            conn.commit()
        return jsonify({"message": "policy updated", "policy": current_policy(conn, agent_id)}), 200

    @app.get("/api/preauths")
    def preauth_get():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        with lock:
            expire_preauth(conn)
            conn.commit()
        agent_id = str(request.args.get("agent_id", "")).strip()
        if agent_id:
            rows = conn.execute("SELECT * FROM preauthorizations WHERE agent_id=? ORDER BY created_at DESC LIMIT 100", (agent_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM preauthorizations ORDER BY created_at DESC LIMIT 100").fetchall()
        out = []
        for r in rows:
            out.append({
                "preauth_id": r["preauth_id"], "agent_id": r["agent_id"], "total_amount": float(r["total_amount"]),
                "remaining_amount": float(r["remaining_amount"]), "starts_at": r["starts_at"], "ends_at": r["ends_at"],
                "status": r["status"], "payee_whitelist": [str(x) for x in parse_json_list(r["payee_whitelist_json"])],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            })
        return jsonify({"preauthorizations": out}), 200

    @app.post("/api/preauths")
    def preauth_create():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400
        try:
            total_amount = money(float(payload.get("total_amount", 0)))
            if total_amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "invalid total_amount"}), 400
        start_raw = payload.get("starts_at")
        end_raw = payload.get("ends_at")
        window_hours = int(payload.get("window_hours", 24))
        start_dt = parse_iso8601(str(start_raw)) if start_raw else utcnow()
        end_dt = parse_iso8601(str(end_raw)) if end_raw else start_dt + timedelta(hours=max(1, window_hours))
        if end_dt <= start_dt:
            return jsonify({"error": "ends_at must be after starts_at"}), 400
        payee_wl = payload.get("payee_whitelist", [])
        if not isinstance(payee_wl, list):
            return jsonify({"error": "payee_whitelist must be list"}), 400
        conn = db()
        with lock:
            ensure_agent(conn, agent_id)
            ensure_policy(conn, agent_id)
            preauth_id = f"pa_{uuid.uuid4().hex[:12]}"
            now = iso(utcnow())
            conn.execute("INSERT INTO preauthorizations(preauth_id,agent_id,total_amount,remaining_amount,starts_at,ends_at,status,payee_whitelist_json,created_at,updated_at) VALUES (?,?,?,?,?,?,'ACTIVE',?,?,?)", (preauth_id, agent_id, total_amount, total_amount, iso(start_dt), iso(end_dt), json.dumps([str(x) for x in payee_wl], ensure_ascii=False), now, now))
            event(conn, preauth_id, "PREAUTH_CREATED", {"agent_id": agent_id, "total_amount": total_amount})
            conn.commit()
        return jsonify({"message": "preauthorization created", "preauth_id": preauth_id}), 201

    @app.post("/api/connectors/install-link")
    def connector_install_link():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_name = str(payload.get("agent_name", "未命名Agent")).strip() or "未命名Agent"
        install_id = f"ins_{uuid.uuid4().hex[:10]}"
        bind_token = uuid.uuid4().hex
        install_link = f"https://aegis.local/connector/install/{install_id}?token={bind_token}"
        bind_link = f"https://aegis.local/bind/{bind_token}"
        now = iso(utcnow())
        conn = db()
        with lock:
            conn.execute("INSERT INTO connector_installs(install_id,install_link,bind_token,bind_link,agent_name,status,bound_agent_id,created_at,installed_at,confirmed_at) VALUES (?,?,?,?,?,'AWAITING_AGENT_INSTALL',NULL,?,?,NULL)", (install_id, install_link, bind_token, bind_link, agent_name, now, None))
            event(conn, install_id, "CONNECTOR_INSTALL_LINK_CREATED", {"agent_name": agent_name})
            conn.commit()
        return jsonify({"install_id": install_id, "install_link": install_link, "bind_token": bind_token}), 201

    @app.get("/api/connectors")
    def connectors_list():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        rows = conn.execute("SELECT install_id,install_link,bind_link,agent_name,status,bound_agent_id,created_at,installed_at,confirmed_at FROM connector_installs ORDER BY created_at DESC LIMIT 100").fetchall()
        return jsonify({"connectors": [{"install_id": r["install_id"], "install_link": r["install_link"], "bind_link": r["bind_link"], "agent_name": r["agent_name"], "status": r["status"], "bound_agent_id": r["bound_agent_id"], "created_at": r["created_at"], "installed_at": r["installed_at"], "confirmed_at": r["confirmed_at"]} for r in rows]}), 200

    @app.post("/api/connectors/bind-complete")
    def connector_bind_complete():
        ok, role, err = ok_agent_or_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        install_id = str(payload.get("install_id", "")).strip()
        agent_id = str(payload.get("agent_id", "")).strip()
        agent_name = str(payload.get("agent_name", agent_id)).strip() if agent_id else ""
        if not install_id or not agent_id:
            return jsonify({"error": "install_id and agent_id are required"}), 400
        conn = db()
        with lock:
            row = conn.execute("SELECT * FROM connector_installs WHERE install_id=?", (install_id,)).fetchone()
            if row is None:
                return jsonify({"error": "install_id not found"}), 404
            if row["status"] == "BOUND":
                return jsonify({"message": "already bound", "bind_link": row["bind_link"]}), 200
            ensure_agent(conn, agent_id, agent_name)
            now = iso(utcnow())
            conn.execute("UPDATE connector_installs SET status='AWAITING_USER_CONFIRM',bound_agent_id=?,installed_at=? WHERE install_id=?", (agent_id, now, install_id))
            event(conn, install_id, "CONNECTOR_BIND_COMPLETED_BY_AGENT", {"agent_id": agent_id, "via": role})
            conn.commit()
            bind_link = row["bind_link"]
        return jsonify({"message": "bind completed, waiting user confirm", "bind_link": bind_link}), 200

    @app.post("/api/connectors/confirm-binding")
    def connector_confirm_binding():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        bind_token = str(payload.get("bind_token", "")).strip()
        if not bind_token:
            return jsonify({"error": "bind_token is required"}), 400
        user_token = request.headers.get("X-User-Token", "")
        conn = db()
        with lock:
            row = conn.execute("SELECT * FROM connector_installs WHERE bind_token=?", (bind_token,)).fetchone()
            if row is None:
                return jsonify({"error": "bind_token not found"}), 404
            if row["status"] == "BOUND":
                return jsonify({"message": "already confirmed", "agent_id": row["bound_agent_id"]}), 200
            if row["status"] != "AWAITING_USER_CONFIRM" or not row["bound_agent_id"]:
                return jsonify({"error": "connector is not ready for user confirmation"}), 409
            now = iso(utcnow())
            binding_id = f"bd_{uuid.uuid4().hex[:12]}"
            conn.execute("INSERT INTO agent_bindings(binding_id,user_token,agent_id,connector_install_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_token,agent_id) DO UPDATE SET connector_install_id=excluded.connector_install_id,status='BOUND',updated_at=excluded.updated_at", (binding_id, user_token, row["bound_agent_id"], row["install_id"], "BOUND", now, now))
            conn.execute("UPDATE connector_installs SET status='BOUND',confirmed_at=? WHERE install_id=?", (now, row["install_id"]))
            event(conn, row["install_id"], "CONNECTOR_BOUND", {"agent_id": row["bound_agent_id"], "user_token": user_token})
            conn.commit()
        return jsonify({"message": "agent binding confirmed", "agent_id": row["bound_agent_id"]}), 200

    @app.post("/api/pay-requests")
    def create_pay_request():
        ok, err = ok_agent()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        try:
            request_id = str(payload.get("request_id") or f"req_{uuid.uuid4().hex[:14]}")
            agent_id = str(payload.get("agent_id", "")).strip()
            agent_name = str(payload.get("agent_name", agent_id)).strip() if agent_id else ""
            payee = str(payload.get("payee", "")).strip()
            purpose = str(payload.get("purpose", "")).strip()
            amount = money(float(payload.get("amount", 0)))
            callback_url = valid_callback(payload.get("callback_url"))
            expires_at = parse_iso8601(str(payload.get("expires_at"))) if payload.get("expires_at") else utcnow() + timedelta(minutes=10)
            nonce = str(payload.get("nonce", "")).strip() or f"{agent_id}:{request_id}"
            issued_at = parse_iso8601(str(payload.get("issued_at"))) if payload.get("issued_at") else utcnow()
            if not agent_id:
                raise ValueError("agent_id is required")
            if not payee:
                raise ValueError("payee is required")
            if not purpose:
                raise ValueError("purpose is required")
            if amount <= 0 or amount > 100000:
                raise ValueError("amount must be > 0 and <= 100000")
            if expires_at <= utcnow():
                raise ValueError("expires_at must be in the future")
            now_dt = utcnow()
            if (now_dt - issued_at).total_seconds() > app.config["REQUEST_MAX_AGE_SECONDS"]:
                raise ValueError("issued_at is too old")
            if (issued_at - now_dt).total_seconds() > app.config["REQUEST_FUTURE_TOLERANCE_SECONDS"]:
                raise ValueError("issued_at is too far in future")
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

        conn = db()
        auto_execute = False
        with lock:
            expire_pending(conn)
            expire_preauth(conn)
            ensure_agent(conn, agent_id, agent_name)
            ensure_policy(conn, agent_id)
            try:
                conn.execute("INSERT INTO request_nonces(nonce,issued_at,created_at) VALUES (?,?,?)", (nonce, iso(issued_at), iso(utcnow())))
            except sqlite3.IntegrityError:
                return jsonify({"error": "replay detected", "reason_code": "REPLAY_DETECTED"}), 409

            existing = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
            if existing is not None:
                same = existing["agent_id"] == agent_id and existing["payee"] == payee and abs(float(existing["amount"]) - amount) < 1e-9 and existing["purpose"] == purpose
                if same:
                    return jsonify({"message": "idempotent replay accepted", "request": req_dict(existing), "idempotent": True}), 200
                return jsonify({"error": "request_id already exists with different payload"}), 409

            ok_pol, reason_code, reason_msg = validate_policy(conn, agent_id, payee, amount, now_dt)
            now = iso(utcnow())
            if not ok_pol:
                conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'REJECTED',?,?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, reason_code, nonce, iso(issued_at), now, now))
                event(conn, request_id, "REQUEST_REJECTED", {"reason_code": reason_code, "reason": reason_msg})
                conn.commit()
                rej = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
                return jsonify({"error": reason_msg, "reason_code": reason_code, "request": req_dict(rej)}), 409

            q = quota_summary(conn)
            a_avail = agent_available(conn, agent_id)
            if q["available_quota"] < amount or a_avail < amount:
                conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'REJECTED','QUOTA_INSUFFICIENT',?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, nonce, iso(issued_at), now, now))
                event(conn, request_id, "REQUEST_REJECTED", {"reason_code": "QUOTA_INSUFFICIENT", "available_quota": q["available_quota"], "agent_available": a_avail, "required_amount": amount})
                conn.commit()
                rej = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
                return jsonify({"error": "insufficient available quota", "reason_code": "QUOTA_INSUFFICIENT", "request": req_dict(rej)}), 409

            conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'PENDING',NULL,?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, nonce, iso(issued_at), now, now))
            event(conn, request_id, "REQUEST_CREATED", {"agent_id": agent_id, "payee": payee, "amount": amount})
            hit = preauth_match(conn, agent_id, payee, amount, now)
            if hit is not None:
                conn.execute("UPDATE payment_requests SET status='APPROVED',approved_at=?,preauth_id=?,approval_note=?,updated_at=? WHERE request_id=?", (now, hit["preauth_id"], "approved via preauthorization", now, request_id))
                event(conn, request_id, "REQUEST_PREAUTHORIZED", {"preauth_id": hit["preauth_id"]})
                auto_execute = True
            conn.commit()

        if auto_execute:
            body, code = execute(request_id, "preauthorization")
            if code == 200:
                return jsonify(body), 201
            return jsonify(body), code
        created = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
        return jsonify({"message": "request accepted", "request": req_dict(created)}), 201

    @app.get("/api/pending-requests")
    def pending_requests():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        with lock:
            expire_pending(conn)
            conn.commit()
            rows = conn.execute("SELECT * FROM payment_requests WHERE status='PENDING' ORDER BY created_at ASC").fetchall()
        return jsonify({"pending_requests": [req_dict(r) for r in rows]}), 200

    @app.get("/api/requests/<request_id>")
    def request_detail(request_id):
        ok, err = ok_user()
        if not ok:
            return err
        row = db().execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return jsonify({"error": "request not found"}), 404
        return jsonify({"request": req_dict(row)}), 200

    @app.get("/api/auth/challenge")
    def auth_challenge():
        ok, err = ok_user()
        if not ok:
            return err
        request_id = str(request.args.get("request_id", "")).strip()
        if not request_id:
            return jsonify({"error": "request_id is required"}), 400
        conn = db()
        with lock:
            row = conn.execute("SELECT status FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                return jsonify({"error": "request not found"}), 404
            if row["status"] != "PENDING":
                return jsonify({"error": f"request status is {row['status']}, expected PENDING"}), 409
            challenge = create_auth_challenge(conn, request_id)
            conn.commit()
        return jsonify({"request_id": request_id, "challenge": challenge, "ttl_seconds": app.config["CHALLENGE_TTL_SECONDS"]}), 200

    @app.post("/api/sign")
    def sign_request():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        request_id = str(payload.get("request_id", "")).strip()
        approval = str(payload.get("approval", "")).strip()
        signed_by = str(payload.get("signed_by", "mobile_web_user")).strip()
        signature = str(payload.get("signature", "simulated_signature")).strip()
        assertion = payload.get("webauthn_assertion")
        if not request_id:
            return jsonify({"error": "request_id is required"}), 400
        if approval != "user_approved":
            return jsonify({"error": "approval must be 'user_approved'"}), 400
        conn = db()
        with lock:
            expire_pending(conn)
            row = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                return jsonify({"error": "request not found"}), 404
            if row["status"] != "PENDING":
                return jsonify({"error": f"request status is {row['status']}, expected PENDING"}), 409
            if assertion:
                ok_assertion, msg = verify_assertion(conn, request_id, assertion)
                if not ok_assertion:
                    conn.rollback()
                    return jsonify({"error": msg}), 401
            elif not app.config["ALLOW_SIMULATED_BIO"]:
                conn.rollback()
                return jsonify({"error": "biometric authentication required"}), 401
            now = iso(utcnow())
            conn.execute("UPDATE payment_requests SET status='APPROVED',approved_at=?,updated_at=?,approval_note=? WHERE request_id=?", (now, now, "approved via manual sign", request_id))
            conn.execute("INSERT INTO approvals(request_id,approved_by,approval_flag,signature,created_at) VALUES (?,?,?,?,?)", (request_id, signed_by, approval, signature, now))
            event(conn, request_id, "REQUEST_APPROVED", {"signed_by": signed_by, "auth_method": "webauthn" if assertion else "simulated"})
            conn.commit()
        body, code = execute(request_id, "sign_endpoint")
        return jsonify(body), code

    @app.post("/api/simulate-execute")
    def simulate_execute():
        ok, err = ok_internal()
        if not ok:
            return err
        request_id = str((request.get_json(silent=True) or {}).get("request_id", "")).strip()
        if not request_id:
            return jsonify({"error": "request_id is required"}), 400
        body, code = execute(request_id, "internal_endpoint")
        return jsonify(body), code

    @app.get("/api/consumptions")
    def consumptions():
        ok, err = ok_user()
        if not ok:
            return err
        try:
            limit = min(200, max(1, int(request.args.get("limit", "20"))))
        except ValueError:
            limit = 20
        agent_id = str(request.args.get("agent_id", "")).strip()
        conn = db()
        if agent_id:
            rows = conn.execute("SELECT * FROM consumption_records WHERE agent_id=? ORDER BY created_at DESC LIMIT ?", (agent_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM consumption_records ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return jsonify({"consumptions": [cons_dict(r) for r in rows]}), 200

    @app.get("/api/agents")
    def agents():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        token = request.headers.get("X-User-Token", "")
        return jsonify({"agents": list_agents(conn, token)}), 200

    @app.get("/api/agents/<agent_id>")
    def agent_detail(agent_id):
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            return jsonify({"error": "agent not found"}), 404
        recent = conn.execute("SELECT * FROM consumption_records WHERE agent_id=? ORDER BY created_at DESC LIMIT 5", (agent_id,)).fetchall()
        agents_payload = list_agents(conn, request.headers.get("X-User-Token", ""))
        agent_payload = [x for x in agents_payload if x["agent_id"] == agent_id][0]
        return jsonify({"agent": agent_payload, "policy": current_policy(conn, agent_id), "recent_consumptions": [cons_dict(r) for r in recent]}), 200

    @app.get("/api/audit/events")
    def audit_events():
        ok, err = ok_user()
        if not ok:
            return err
        try:
            limit = min(300, max(1, int(request.args.get("limit", "80"))))
        except ValueError:
            limit = 80
        request_id = str(request.args.get("request_id", "")).strip()
        conn = db()
        if request_id:
            rows = conn.execute("SELECT request_id,event_type,event_detail,created_at FROM events WHERE request_id=? ORDER BY id DESC LIMIT ?", (request_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT request_id,event_type,event_detail,created_at FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            try:
                detail = json.loads(r["event_detail"]) if r["event_detail"] else None
            except json.JSONDecodeError:
                detail = {"raw": r["event_detail"]}
            out.append({"request_id": r["request_id"], "event_type": r["event_type"], "event_detail": detail, "created_at": r["created_at"]})
        return jsonify({"events": out}), 200

    @app.get("/api/dashboard")
    def dashboard():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        token = request.headers.get("X-User-Token", "")
        with lock:
            expire_pending(conn)
            expire_preauth(conn)
            conn.commit()
        quota = quota_summary(conn)
        agents_payload = list_agents(conn, token)
        pending = conn.execute("SELECT * FROM payment_requests WHERE status='PENDING' ORDER BY created_at ASC LIMIT 50").fetchall()
        cons = conn.execute("SELECT * FROM consumption_records ORDER BY created_at DESC LIMIT 80").fetchall()
        preauths = conn.execute("SELECT * FROM preauthorizations ORDER BY created_at DESC LIMIT 30").fetchall()
        moves = conn.execute("SELECT movement_id,movement_type,agent_id,amount,operator,note,created_at FROM quota_movements ORDER BY created_at DESC LIMIT 50").fetchall()
        events_rows = conn.execute("SELECT request_id,event_type,event_detail,created_at FROM events ORDER BY id DESC LIMIT 80").fetchall()
        connectors = connector_status(conn)
        bound_count = int(conn.execute("SELECT COUNT(*) AS c FROM agent_bindings WHERE user_token=? AND status='BOUND'", (token,)).fetchone()["c"])
        req_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE date(created_at)=date('now')").fetchone()["c"])
        suc_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE status='SUCCESS' AND date(updated_at)=date('now')").fetchone()["c"])
        today_spend = money(conn.execute("SELECT COALESCE(SUM(amount),0) AS s FROM payment_requests WHERE status='SUCCESS' AND date(updated_at)=date('now')").fetchone()["s"])
        ev_payload = []
        for r in events_rows:
            try:
                detail = json.loads(r["event_detail"]) if r["event_detail"] else None
            except json.JSONDecodeError:
                detail = {"raw": r["event_detail"]}
            ev_payload.append({"request_id": r["request_id"], "event_type": r["event_type"], "event_detail": detail, "created_at": r["created_at"]})
        return jsonify({
            "summary": {"today_requests": req_cnt, "today_success": suc_cnt, "today_spend": today_spend},
            "quota_summary": quota,
            "agents": agents_payload,
            "pending_requests": [req_dict(r) for r in pending],
            "consumptions": [cons_dict(r) for r in cons],
            "preauthorizations": [{"preauth_id": r["preauth_id"], "agent_id": r["agent_id"], "total_amount": float(r["total_amount"]), "remaining_amount": float(r["remaining_amount"]), "starts_at": r["starts_at"], "ends_at": r["ends_at"], "status": r["status"], "payee_whitelist": [str(x) for x in parse_json_list(r["payee_whitelist_json"])], "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in preauths],
            "quota_movements": [{"movement_id": r["movement_id"], "movement_type": r["movement_type"], "agent_id": r["agent_id"], "amount": float(r["amount"]), "operator": r["operator"], "note": r["note"], "created_at": r["created_at"]} for r in moves],
            "audit_events": ev_payload,
            "connector_status": connectors,
            "binding_status": {"bound_agents_count": bound_count},
            "wallets": {"cold_wallet": {"balance": quota["protected_balance"], "updated_at": quota["updated_at"]}, "warm_wallet": {"balance": quota["available_quota"], "updated_at": quota["updated_at"]}, "today_warm_spend": today_spend},
            "wallet_transfers": [{"transfer_id": r["movement_id"], "from_wallet": "cold" if r["movement_type"] == "ALLOCATE" else "warm", "to_wallet": "warm" if r["movement_type"] == "ALLOCATE" else "cold", "amount": float(r["amount"]), "operator": r["operator"], "note": r["note"], "created_at": r["created_at"]} for r in moves],
            "external_topups": [],
        }), 200

    @app.get("/api/wallets")
    def legacy_wallets():
        ok, err = ok_user()
        if not ok:
            return err
        q = quota_summary(db())
        s = money(db().execute("SELECT COALESCE(SUM(amount),0) AS s FROM payment_requests WHERE status='SUCCESS' AND date(updated_at)=date('now')").fetchone()["s"])
        return jsonify({"cold_wallet": {"balance": q["protected_balance"], "updated_at": q["updated_at"]}, "warm_wallet": {"balance": q["available_quota"], "updated_at": q["updated_at"]}, "today_warm_spend": s}), 200

    @app.post("/api/wallets/transfer")
    def legacy_transfer():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        if str(payload.get("from_wallet", "cold")).lower() != "cold" or str(payload.get("to_wallet", "warm")).lower() != "warm":
            return jsonify({"error": "only cold -> warm is supported for compatibility"}), 400
        return quota_allocate()

    @app.get("/api/wallet-transfers")
    def legacy_wallet_transfers():
        ok, err = ok_user()
        if not ok:
            return err
        rows = db().execute("SELECT movement_id,movement_type,agent_id,amount,operator,note,created_at FROM quota_movements ORDER BY created_at DESC LIMIT 100").fetchall()
        return jsonify({"wallet_transfers": [{"transfer_id": r["movement_id"], "from_wallet": "cold" if r["movement_type"] == "ALLOCATE" else "warm", "to_wallet": "warm" if r["movement_type"] == "ALLOCATE" else "cold", "amount": float(r["amount"]), "operator": r["operator"], "note": r["note"], "created_at": r["created_at"]} for r in rows]}), 200

    @app.post("/api/wallets/external-topup")
    def legacy_external_topup():
        ok, err = ok_user()
        if not ok:
            return err
        return jsonify({"error": "external_topup is deprecated in non-custodial quota model"}), 410

    @app.get("/api/wallets/external-topups")
    def legacy_external_topups():
        ok, err = ok_user()
        if not ok:
            return err
        return jsonify({"external_topups": []}), 200

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=False)
