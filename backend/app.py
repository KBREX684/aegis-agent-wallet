import base64
import hashlib
import json
import os
import re
import sqlite3
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


def valid_callback(url):
    if not url:
        return None
    u = urlparse(str(url).strip())
    if u.scheme not in {"http", "https"} or not u.netloc:
        raise ValueError("callback_url must be valid http/https")
    return str(url).strip()


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

    def init_db():
        path = Path(app.config["DB_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        now = iso(utcnow())
        conn.execute("INSERT OR IGNORE INTO agents(agent_id,name,status,threshold,created_at,updated_at) VALUES (?,?,?,?,?,?)", ("api_agent_001", "API采购Agent", "connected", app.config["DEFAULT_AGENT_THRESHOLD"], now, now))
        conn.execute("INSERT OR IGNORE INTO user_profiles(user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at) VALUES (?,?,?,?,?,?)", (app.config["USER_TOKEN"], "13800138000", 1, "110101199001011234", 1, now))
        total = money(app.config["INITIAL_TOTAL_BALANCE"])
        available = min(total, money(app.config["INITIAL_AVAILABLE_QUOTA"]))
        conn.execute("INSERT OR IGNORE INTO quota_account(id,total_balance,protected_balance,available_quota,updated_at) VALUES (1,?,?,?,?)", (total, money(total - available), available, now))
        conn.execute("INSERT OR IGNORE INTO agent_quotas(agent_id,allocated_quota,consumed_quota,updated_at) VALUES (?,?,?,?)", ("api_agent_001", available, 0.0, now))
        conn.execute("INSERT OR IGNORE INTO policies(agent_id,whitelist_json,single_limit,daily_limit,allowed_hours_json,updated_at) VALUES (?,?,?,?,?,?)", ("api_agent_001", json.dumps(["DeepSeek"], ensure_ascii=False), app.config["DEFAULT_SINGLE_LIMIT"], app.config["DEFAULT_DAILY_LIMIT"], json.dumps(list(range(24)), ensure_ascii=False), now))
        conn.commit()
        conn.close()

    init_db()

    def event(conn, req_id, typ, detail=None):
        conn.execute("INSERT INTO events(request_id,event_type,event_detail,created_at) VALUES (?,?,?,?)", (req_id, typ, json.dumps(detail, ensure_ascii=False) if detail else None, iso(utcnow())))

    def ok_agent():
        if request.headers.get("X-Agent-Token") != app.config["AGENT_TOKEN"]:
            return False, (jsonify({"error": "invalid agent token"}), 401)
        return True, ()

    def ok_user():
        if request.headers.get("X-User-Token") != app.config["USER_TOKEN"]:
            return False, (jsonify({"error": "invalid user token"}), 401)
        return True, ()

    def quota_summary(conn):
        row = conn.execute("SELECT total_balance,protected_balance,available_quota,updated_at FROM quota_account WHERE id=1").fetchone()
        total = float(row["total_balance"])
        avail = float(row["available_quota"])
        return {"total_balance": money(total), "protected_balance": money(row["protected_balance"]), "available_quota": money(avail), "allocated_ratio_percent": round((avail / total * 100), 2) if total > 0 else 0.0, "updated_at": row["updated_at"]}

    def current_policy(conn, agent_id):
        row = conn.execute("SELECT * FROM policies WHERE agent_id=?", (agent_id,)).fetchone()
        return {"agent_id": row["agent_id"], "whitelist": [str(x) for x in parse_json_list(row["whitelist_json"])], "single_limit": float(row["single_limit"]), "daily_limit": float(row["daily_limit"]), "allowed_hours": [int(x) for x in parse_json_list(row["allowed_hours_json"])], "updated_at": row["updated_at"]}

    def agent_available(conn, agent_id):
        row = conn.execute("SELECT allocated_quota,consumed_quota FROM agent_quotas WHERE agent_id=?", (agent_id,)).fetchone()
        return money(float(row["allocated_quota"]) - float(row["consumed_quota"])) if row else 0.0

    def hash_tx(req_id, agent_id, payee, amount, purpose, executed_at):
        raw = f"{req_id}|{agent_id}|{payee}|{amount:.2f}|{purpose}|{executed_at}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def req_dict(r):
        return {"request_id": r["request_id"], "agent_id": r["agent_id"], "payee": r["payee"], "amount": float(r["amount"]), "purpose": r["purpose"], "expires_at": r["expires_at"], "callback_url": r["callback_url"], "status": r["status"], "reason_code": r["reason_code"], "nonce": r["nonce"], "issued_at": r["issued_at"], "preauth_id": r["preauth_id"], "created_at": r["created_at"], "updated_at": r["updated_at"], "approved_at": r["approved_at"], "executed_at": r["executed_at"], "tx_id": r["tx_id"], "approval_note": r["approval_note"]}

    def cons_dict(r):
        detail = {}
        try:
            detail = json.loads(r["tx_detail_json"]) if r["tx_detail_json"] else {}
        except json.JSONDecodeError:
            detail = {"raw": r["tx_detail_json"]}
        return {"record_id": r["record_id"], "request_id": r["request_id"], "agent_id": r["agent_id"], "amount": float(r["amount"]), "payee": r["payee"], "purpose": r["purpose"], "tx_hash": r["tx_hash"], "tx_detail": detail, "created_at": r["created_at"]}

    def execute(request_id):
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
            if q["available_quota"] < amount or agent_available(conn, req["agent_id"]) < amount:
                now = iso(utcnow())
                conn.execute("UPDATE payment_requests SET status='FAILED',reason_code='QUOTA_INSUFFICIENT',updated_at=? WHERE request_id=?", (now, request_id))
                event(conn, request_id, "PAYMENT_FAILED", {"reason_code": "QUOTA_INSUFFICIENT"})
                conn.commit()
                failed = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
                return {"error": "insufficient available quota", "request": req_dict(failed)}, 409
            now = iso(utcnow())
            tx_id = f"sim_tx_{uuid.uuid4().hex[:12]}"
            conn.execute("UPDATE quota_account SET total_balance=?,available_quota=?,updated_at=? WHERE id=1", (money(q["total_balance"] - amount), money(q["available_quota"] - amount), now))
            conn.execute("UPDATE agent_quotas SET consumed_quota=consumed_quota+?,updated_at=? WHERE agent_id=?", (amount, now, req["agent_id"]))
            quota_delta = max(1, int(round(amount * app.config["API_QUOTA_PER_YUAN"])))
            tx_hash = hash_tx(req["request_id"], req["agent_id"], req["payee"], amount, req["purpose"], now)
            detail = {"tx_id": tx_id, "executed_at": now, "api_quota_delta": quota_delta}
            conn.execute("INSERT INTO api_quota_ledger(entry_id,agent_id,delta_quota,reason,request_id,created_at) VALUES (?,?,?,?,?,?)", (f"quota_{uuid.uuid4().hex[:12]}", req["agent_id"], quota_delta, "api_purchase", req["request_id"], now))
            conn.execute("INSERT INTO consumption_records(record_id,request_id,agent_id,amount,payee,purpose,tx_hash,tx_detail_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (f"cons_{uuid.uuid4().hex[:12]}", req["request_id"], req["agent_id"], amount, req["payee"], req["purpose"], tx_hash, json.dumps(detail, ensure_ascii=False), now))
            conn.execute("UPDATE payment_requests SET status='SUCCESS',reason_code='SUCCESS',tx_id=?,executed_at=?,updated_at=?,approval_note=? WHERE request_id=?", (tx_id, now, now, "executed from available quota", request_id))
            event(conn, request_id, "PAYMENT_EXECUTED", {"tx_id": tx_id, "tx_hash": tx_hash, "reason_code": "SUCCESS"})
            conn.commit()
            updated = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
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

    @app.get("/api/user/profile")
    def user_profile():
        ok, err = ok_user()
        if not ok:
            return err
        token = request.headers.get("X-User-Token", "")
        conn = db()
        row = conn.execute("SELECT * FROM user_profiles WHERE user_token=?", (token,)).fetchone()
        if row is None:
            now = iso(utcnow())
            conn.execute("INSERT INTO user_profiles(user_token,mobile,mobile_bound,id_card_no,id_card_bound,updated_at) VALUES (?,?,?,?,?,?)", (token, None, 0, None, 0, now))
            conn.commit()
            row = conn.execute("SELECT * FROM user_profiles WHERE user_token=?", (token,)).fetchone()
        bound = conn.execute("SELECT COUNT(*) AS c FROM agent_bindings WHERE user_token=? AND status='BOUND'", (token,)).fetchone()["c"]
        return jsonify({
            "mobile_bound": bool(row["mobile_bound"]),
            "mobile_masked": row["mobile"][:3] + "****" + row["mobile"][-4:] if row["mobile_bound"] and row["mobile"] else "",
            "id_card_bound": bool(row["id_card_bound"]),
            "id_card_masked": row["id_card_no"][:6] + "********" + row["id_card_no"][-4:] if row["id_card_bound"] and row["id_card_no"] else "",
            "bound_agents_count": int(bound),
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
        amount = money(float(payload.get("amount", 0)))
        if amount <= 0:
            return jsonify({"error": "invalid allocate amount"}), 400
        conn = db()
        with lock:
            q = quota_summary(conn)
            if q["protected_balance"] < amount:
                return jsonify({"error": "insufficient protected balance"}), 409
            now = iso(utcnow())
            conn.execute("UPDATE quota_account SET protected_balance=?,available_quota=?,updated_at=? WHERE id=1", (money(q["protected_balance"] - amount), money(q["available_quota"] + amount), now))
            conn.execute("INSERT OR IGNORE INTO agent_quotas(agent_id,allocated_quota,consumed_quota,updated_at) VALUES (?,?,?,?)", (agent_id, 0, 0, now))
            conn.execute("UPDATE agent_quotas SET allocated_quota=allocated_quota+?,updated_at=? WHERE agent_id=?", (amount, now, agent_id))
            conn.execute("INSERT INTO quota_movements(movement_id,movement_type,agent_id,amount,operator,note,created_at) VALUES (?,?,?,?,?,?,?)", (f"mv_{uuid.uuid4().hex[:12]}", "ALLOCATE", agent_id, amount, "mobile_web_user", "manual allocation", now))
            conn.commit()
        return jsonify({"message": "quota allocated", "quota_summary": quota_summary(conn)}), 200

    @app.post("/api/quota/reclaim")
    def quota_reclaim():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "api_agent_001")).strip() or "api_agent_001"
        amount = money(float(payload.get("amount", 0)))
        if amount <= 0:
            return jsonify({"error": "invalid reclaim amount"}), 400
        conn = db()
        with lock:
            q = quota_summary(conn)
            if agent_available(conn, agent_id) < amount or q["available_quota"] < amount:
                return jsonify({"error": "insufficient available quota to reclaim"}), 409
            now = iso(utcnow())
            conn.execute("UPDATE quota_account SET protected_balance=?,available_quota=?,updated_at=? WHERE id=1", (money(q["protected_balance"] + amount), money(q["available_quota"] - amount), now))
            conn.execute("UPDATE agent_quotas SET allocated_quota=allocated_quota-?,updated_at=? WHERE agent_id=?", (amount, now, agent_id))
            conn.execute("INSERT INTO quota_movements(movement_id,movement_type,agent_id,amount,operator,note,created_at) VALUES (?,?,?,?,?,?,?)", (f"mv_{uuid.uuid4().hex[:12]}", "RECLAIM", agent_id, amount, "mobile_web_user", "manual reclaim", now))
            conn.commit()
        return jsonify({"message": "quota reclaimed", "quota_summary": quota_summary(conn)}), 200

    @app.get("/api/policies")
    def policies_get():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        agent_id = str(request.args.get("agent_id", "")).strip()
        if agent_id:
            return jsonify({"policy": current_policy(conn, agent_id)}), 200
        rows = conn.execute("SELECT agent_id FROM policies ORDER BY agent_id").fetchall()
        return jsonify({"policies": [current_policy(conn, r["agent_id"]) for r in rows]}), 200

    @app.post("/api/policies")
    def policies_set():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400
        wl = payload.get("whitelist", [])
        hours = payload.get("allowed_hours", list(range(24)))
        single = float(payload.get("single_limit", app.config["DEFAULT_SINGLE_LIMIT"]))
        daily = float(payload.get("daily_limit", app.config["DEFAULT_DAILY_LIMIT"]))
        now = iso(utcnow())
        conn = db()
        with lock:
            conn.execute("INSERT INTO policies(agent_id,whitelist_json,single_limit,daily_limit,allowed_hours_json,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET whitelist_json=excluded.whitelist_json,single_limit=excluded.single_limit,daily_limit=excluded.daily_limit,allowed_hours_json=excluded.allowed_hours_json,updated_at=excluded.updated_at", (agent_id, json.dumps([str(x) for x in wl], ensure_ascii=False), single, daily, json.dumps([int(x) for x in hours], ensure_ascii=False), now))
            conn.commit()
        return jsonify({"message": "policy updated", "policy": current_policy(conn, agent_id)}), 200

    @app.get("/api/preauths")
    def preauths_get():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        rows = conn.execute("SELECT * FROM preauthorizations ORDER BY created_at DESC LIMIT 100").fetchall()
        return jsonify({"preauthorizations": [{"preauth_id": r["preauth_id"], "agent_id": r["agent_id"], "total_amount": float(r["total_amount"]), "remaining_amount": float(r["remaining_amount"]), "starts_at": r["starts_at"], "ends_at": r["ends_at"], "status": r["status"], "payee_whitelist": [str(x) for x in parse_json_list(r["payee_whitelist_json"])], "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]}), 200

    @app.post("/api/preauths")
    def preauths_create():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400
        total_amount = money(float(payload.get("total_amount", 0)))
        if total_amount <= 0:
            return jsonify({"error": "invalid total_amount"}), 400
        start = parse_iso8601(str(payload.get("starts_at"))) if payload.get("starts_at") else utcnow()
        end = parse_iso8601(str(payload.get("ends_at"))) if payload.get("ends_at") else start + timedelta(hours=int(payload.get("window_hours", 24)))
        if end <= start:
            return jsonify({"error": "ends_at must be after starts_at"}), 400
        preauth_id = f"pa_{uuid.uuid4().hex[:12]}"
        now = iso(utcnow())
        conn = db()
        with lock:
            conn.execute("INSERT INTO preauthorizations(preauth_id,agent_id,total_amount,remaining_amount,starts_at,ends_at,status,payee_whitelist_json,created_at,updated_at) VALUES (?,?,?,?,?,?, 'ACTIVE',?,?,?)", (preauth_id, agent_id, total_amount, total_amount, iso(start), iso(end), json.dumps(payload.get("payee_whitelist", []), ensure_ascii=False), now, now))
            conn.commit()
        return jsonify({"message": "preauthorization created", "preauth_id": preauth_id}), 201

    @app.post("/api/connectors/install-link")
    def connector_install():
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
            conn.commit()
        return jsonify({"install_id": install_id, "install_link": install_link, "bind_token": bind_token}), 201

    @app.get("/api/connectors")
    def connectors_get():
        ok, err = ok_user()
        if not ok:
            return err
        rows = db().execute("SELECT install_id,install_link,bind_link,agent_name,status,bound_agent_id,created_at,installed_at,confirmed_at FROM connector_installs ORDER BY created_at DESC LIMIT 100").fetchall()
        return jsonify({"connectors": [{"install_id": r["install_id"], "install_link": r["install_link"], "bind_link": r["bind_link"], "agent_name": r["agent_name"], "status": r["status"], "bound_agent_id": r["bound_agent_id"], "created_at": r["created_at"], "installed_at": r["installed_at"], "confirmed_at": r["confirmed_at"]} for r in rows]}), 200

    @app.post("/api/connectors/bind-complete")
    def connector_bind_complete():
        if request.headers.get("X-Agent-Token") != app.config["AGENT_TOKEN"] and request.headers.get("X-User-Token") != app.config["USER_TOKEN"]:
            return jsonify({"error": "invalid token"}), 401
        payload = request.get_json(silent=True) or {}
        install_id = str(payload.get("install_id", "")).strip()
        agent_id = str(payload.get("agent_id", "")).strip()
        if not install_id or not agent_id:
            return jsonify({"error": "install_id and agent_id are required"}), 400
        conn = db()
        with lock:
            row = conn.execute("SELECT * FROM connector_installs WHERE install_id=?", (install_id,)).fetchone()
            if row is None:
                return jsonify({"error": "install_id not found"}), 404
            conn.execute("INSERT OR IGNORE INTO agents(agent_id,name,status,threshold,created_at,updated_at) VALUES (?,?,?,?,?,?)", (agent_id, str(payload.get("agent_name", agent_id)), "connected", app.config["DEFAULT_AGENT_THRESHOLD"], iso(utcnow()), iso(utcnow())))
            conn.execute("UPDATE connector_installs SET status='AWAITING_USER_CONFIRM',bound_agent_id=?,installed_at=? WHERE install_id=?", (agent_id, iso(utcnow()), install_id))
            conn.commit()
            return jsonify({"message": "bind completed, waiting user confirm", "bind_link": row["bind_link"]}), 200

    @app.post("/api/connectors/confirm-binding")
    def connector_confirm():
        ok, err = ok_user()
        if not ok:
            return err
        bind_token = str((request.get_json(silent=True) or {}).get("bind_token", "")).strip()
        if not bind_token:
            return jsonify({"error": "bind_token is required"}), 400
        token = request.headers.get("X-User-Token", "")
        conn = db()
        with lock:
            row = conn.execute("SELECT * FROM connector_installs WHERE bind_token=?", (bind_token,)).fetchone()
            if row is None:
                return jsonify({"error": "bind_token not found"}), 404
            if row["status"] != "AWAITING_USER_CONFIRM":
                return jsonify({"error": "connector is not ready for user confirmation"}), 409
            now = iso(utcnow())
            conn.execute("INSERT INTO agent_bindings(binding_id,user_token,agent_id,connector_install_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_token,agent_id) DO UPDATE SET connector_install_id=excluded.connector_install_id,status='BOUND',updated_at=excluded.updated_at", (f"bd_{uuid.uuid4().hex[:12]}", token, row["bound_agent_id"], row["install_id"], "BOUND", now, now))
            conn.execute("UPDATE connector_installs SET status='BOUND',confirmed_at=? WHERE install_id=?", (now, row["install_id"]))
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
            payee = str(payload.get("payee", "")).strip()
            purpose = str(payload.get("purpose", "")).strip()
            amount = money(float(payload.get("amount", 0)))
            callback_url = valid_callback(payload.get("callback_url"))
            expires_at = parse_iso8601(str(payload.get("expires_at"))) if payload.get("expires_at") else utcnow() + timedelta(minutes=10)
            nonce = str(payload.get("nonce", "")).strip() or f"{agent_id}:{request_id}"
            issued_at = parse_iso8601(str(payload.get("issued_at"))) if payload.get("issued_at") else utcnow()
            if not agent_id or not payee or not purpose:
                raise ValueError("agent_id/payee/purpose required")
            if amount <= 0:
                raise ValueError("amount must be > 0")
            if expires_at <= utcnow():
                raise ValueError("expires_at must be in the future")
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

        conn = db()
        auto_execute = False
        with lock:
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

            policy = current_policy(conn, agent_id)
            now = iso(utcnow())
            if policy["whitelist"] and payee not in policy["whitelist"]:
                conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'REJECTED','RULE_BLOCKED',?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, nonce, iso(issued_at), now, now))
                conn.commit()
                return jsonify({"error": "payee is not in whitelist", "reason_code": "RULE_BLOCKED"}), 409
            if amount > policy["single_limit"]:
                conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'REJECTED','RULE_BLOCKED',?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, nonce, iso(issued_at), now, now))
                conn.commit()
                return jsonify({"error": "amount exceeds single limit", "reason_code": "RULE_BLOCKED"}), 409
            if agent_available(conn, agent_id) < amount or quota_summary(conn)["available_quota"] < amount:
                conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'REJECTED','QUOTA_INSUFFICIENT',?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, nonce, iso(issued_at), now, now))
                conn.commit()
                return jsonify({"error": "insufficient available quota", "reason_code": "QUOTA_INSUFFICIENT"}), 409

            conn.execute("INSERT INTO payment_requests(request_id,agent_id,payee,amount,purpose,expires_at,callback_url,status,reason_code,nonce,issued_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'PENDING',NULL,?,?,?,?)", (request_id, agent_id, payee, amount, purpose, iso(expires_at), callback_url, nonce, iso(issued_at), now, now))
            hit = conn.execute("SELECT * FROM preauthorizations WHERE agent_id=? AND status='ACTIVE' AND starts_at <= ? AND ends_at >= ? AND remaining_amount >= ? ORDER BY created_at LIMIT 1", (agent_id, now, now, amount)).fetchone()
            if hit is not None:
                conn.execute("UPDATE payment_requests SET status='APPROVED',approved_at=?,preauth_id=?,approval_note=?,updated_at=? WHERE request_id=?", (now, hit["preauth_id"], "approved via preauthorization", now, request_id))
                auto_execute = True
            conn.commit()

        if auto_execute:
            body, code = execute(request_id)
            return jsonify(body), 201 if code == 200 else code

        created = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
        return jsonify({"message": "request accepted", "request": req_dict(created)}), 201

    @app.get("/api/pending-requests")
    def pending_requests():
        ok, err = ok_user()
        if not ok:
            return err
        rows = db().execute("SELECT * FROM payment_requests WHERE status='PENDING' ORDER BY created_at ASC").fetchall()
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

    @app.post("/api/sign")
    def sign():
        ok, err = ok_user()
        if not ok:
            return err
        payload = request.get_json(silent=True) or {}
        request_id = str(payload.get("request_id", "")).strip()
        if not request_id:
            return jsonify({"error": "request_id is required"}), 400
        conn = db()
        with lock:
            row = conn.execute("SELECT * FROM payment_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                return jsonify({"error": "request not found"}), 404
            if row["status"] != "PENDING":
                return jsonify({"error": f"request status is {row['status']}, expected PENDING"}), 409
            now = iso(utcnow())
            conn.execute("UPDATE payment_requests SET status='APPROVED',approved_at=?,updated_at=?,approval_note=? WHERE request_id=?", (now, now, "approved via manual sign", request_id))
            conn.execute("INSERT INTO approvals(request_id,approved_by,approval_flag,signature,created_at) VALUES (?,?,?,?,?)", (request_id, str(payload.get("signed_by", "mobile_web_user")), "user_approved", str(payload.get("signature", "simulated_signature")), now))
            conn.commit()
        body, code = execute(request_id)
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
        if agent_id:
            rows = db().execute("SELECT * FROM consumption_records WHERE agent_id=? ORDER BY created_at DESC LIMIT ?", (agent_id, limit)).fetchall()
        else:
            rows = db().execute("SELECT * FROM consumption_records ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return jsonify({"consumptions": [cons_dict(r) for r in rows]}), 200

    @app.get("/api/agents")
    def agents_get():
        ok, err = ok_user()
        if not ok:
            return err
        conn = db()
        token = request.headers.get("X-User-Token", "")
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
        bound_ids = {r["agent_id"] for r in conn.execute("SELECT agent_id FROM agent_bindings WHERE user_token=? AND status='BOUND'", (token,)).fetchall()}
        out = []
        for r in rows:
            reqs = int(conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE agent_id=? AND date(created_at)=date('now')", (r["agent_id"],)).fetchone()["c"])
            succ = int(conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE agent_id=? AND status='SUCCESS' AND date(updated_at)=date('now')", (r["agent_id"],)).fetchone()["c"])
            aq = conn.execute("SELECT allocated_quota,consumed_quota FROM agent_quotas WHERE agent_id=?", (r["agent_id"],)).fetchone()
            allocated = money(aq["allocated_quota"] if aq else 0)
            consumed = money(aq["consumed_quota"] if aq else 0)
            out.append({"agent_id": r["agent_id"], "name": r["name"], "status": r["status"], "threshold": float(r["threshold"]), "today_requests": reqs, "today_success": succ, "today_success_rate": round((succ / reqs * 100), 2) if reqs else 0.0, "allocated_quota": allocated, "consumed_quota": consumed, "available_quota": money(allocated - consumed), "current_api_quota": int(conn.execute("SELECT COALESCE(SUM(delta_quota),0) AS q FROM api_quota_ledger WHERE agent_id=?", (r["agent_id"],)).fetchone()["q"]), "bound": r["agent_id"] in bound_ids, "created_at": r["created_at"], "updated_at": r["updated_at"]})
        return jsonify({"agents": out}), 200

    @app.get("/api/agents/<agent_id>")
    def agent_detail(agent_id):
        ok, err = ok_user()
        if not ok:
            return err
        row = db().execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            return jsonify({"error": "agent not found"}), 404
        ag = [x for x in agents_get().json["agents"] if x["agent_id"] == agent_id][0]
        recent = db().execute("SELECT * FROM consumption_records WHERE agent_id=? ORDER BY created_at DESC LIMIT 5", (agent_id,)).fetchall()
        return jsonify({"agent": ag, "policy": current_policy(db(), agent_id), "recent_consumptions": [cons_dict(r) for r in recent]}), 200

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
        if request_id:
            rows = db().execute("SELECT request_id,event_type,event_detail,created_at FROM events WHERE request_id=? ORDER BY id DESC LIMIT ?", (request_id, limit)).fetchall()
        else:
            rows = db().execute("SELECT request_id,event_type,event_detail,created_at FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
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
        agents = agents_get().json["agents"]
        pending = conn.execute("SELECT * FROM payment_requests WHERE status='PENDING' ORDER BY created_at ASC LIMIT 50").fetchall()
        cons = conn.execute("SELECT * FROM consumption_records ORDER BY created_at DESC LIMIT 80").fetchall()
        pre = conn.execute("SELECT * FROM preauthorizations ORDER BY created_at DESC LIMIT 30").fetchall()
        moves = conn.execute("SELECT movement_id,movement_type,agent_id,amount,operator,note,created_at FROM quota_movements ORDER BY created_at DESC LIMIT 50").fetchall()
        events = audit_events().json["events"]
        req_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE date(created_at)=date('now')").fetchone()["c"])
        suc_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE status='SUCCESS' AND date(updated_at)=date('now')").fetchone()["c"])
        spend = money(conn.execute("SELECT COALESCE(SUM(amount),0) AS s FROM payment_requests WHERE status='SUCCESS' AND date(updated_at)=date('now')").fetchone()["s"])
        bound_count = int(conn.execute("SELECT COUNT(*) AS c FROM agent_bindings WHERE user_token=? AND status='BOUND'", (token,)).fetchone()["c"])
        conn_status = {
            "awaiting_agent_install": int(conn.execute("SELECT COUNT(*) AS c FROM connector_installs WHERE status='AWAITING_AGENT_INSTALL'").fetchone()["c"]),
            "awaiting_user_confirm": int(conn.execute("SELECT COUNT(*) AS c FROM connector_installs WHERE status='AWAITING_USER_CONFIRM'").fetchone()["c"]),
            "bound_total": int(conn.execute("SELECT COUNT(*) AS c FROM connector_installs WHERE status='BOUND'").fetchone()["c"]),
        }
        q = quota_summary(conn)
        return jsonify({
            "summary": {"today_requests": req_cnt, "today_success": suc_cnt, "today_spend": spend},
            "quota_summary": q,
            "agents": agents,
            "pending_requests": [req_dict(r) for r in pending],
            "consumptions": [cons_dict(r) for r in cons],
            "preauthorizations": [{"preauth_id": r["preauth_id"], "agent_id": r["agent_id"], "total_amount": float(r["total_amount"]), "remaining_amount": float(r["remaining_amount"]), "starts_at": r["starts_at"], "ends_at": r["ends_at"], "status": r["status"], "payee_whitelist": [str(x) for x in parse_json_list(r["payee_whitelist_json"])], "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in pre],
            "quota_movements": [{"movement_id": r["movement_id"], "movement_type": r["movement_type"], "agent_id": r["agent_id"], "amount": float(r["amount"]), "operator": r["operator"], "note": r["note"], "created_at": r["created_at"]} for r in moves],
            "audit_events": events,
            "connector_status": conn_status,
            "binding_status": {"bound_agents_count": bound_count},
            "wallets": {"cold_wallet": {"balance": q["protected_balance"], "updated_at": q["updated_at"]}, "warm_wallet": {"balance": q["available_quota"], "updated_at": q["updated_at"]}, "today_warm_spend": spend},
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
