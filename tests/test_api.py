import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app import create_app


def iso_in(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "AGENT_TOKEN": "agent-token",
                "USER_TOKEN": "user-token",
                "INTERNAL_TOKEN": "internal-token",
                "INITIAL_TOTAL_BALANCE": 100.0,
                "INITIAL_AVAILABLE_QUOTA": 20.0,
                "API_QUOTA_PER_YUAN": 2000,
                "ALLOW_SIMULATED_BIO": True,
            }
        )
        self.client = self.app.test_client()
        self.client.post(
            "/api/policies",
            json={
                "agent_id": "api_agent_001",
                "whitelist": ["DeepSeek"],
                "single_limit": 10.0,
                "daily_limit": 100.0,
                "allowed_hours": list(range(24)),
            },
            headers={"X-User-Token": "user-token"},
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create(self, request_id="req_t_001", amount=0.05, payee="DeepSeek"):
        return self.client.post(
            "/api/pay-requests",
            json={
                "request_id": request_id,
                "agent_id": "api_agent_001",
                "payee": payee,
                "amount": amount,
                "purpose": "buy api calls",
                "expires_at": iso_in(10),
                "nonce": f"nonce_{request_id}",
                "issued_at": iso_in(0),
            },
            headers={"X-Agent-Token": "agent-token"},
        )

    def _sign(self, request_id):
        return self.client.post(
            "/api/sign",
            json={"request_id": request_id, "approval": "user_approved", "signed_by": "tester"},
            headers={"X-User-Token": "user-token"},
        )

    def test_quota_summary_initialized(self):
        resp = self.client.get("/api/quota/summary", headers={"X-User-Token": "user-token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total_balance"], 100.0)
        self.assertEqual(data["protected_balance"], 80.0)
        self.assertEqual(data["available_quota"], 20.0)

    def test_allocate_and_reclaim(self):
        a = self.client.post(
            "/api/quota/allocate",
            json={"agent_id": "api_agent_001", "amount": 5},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(a.status_code, 200)
        r = self.client.post(
            "/api/quota/reclaim",
            json={"agent_id": "api_agent_001", "amount": 3},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(r.status_code, 200)
        q = self.client.get("/api/quota/summary", headers={"X-User-Token": "user-token"}).get_json()
        self.assertEqual(q["protected_balance"], 78.0)
        self.assertEqual(q["available_quota"], 22.0)

    def test_allocate_fails_when_protected_insufficient(self):
        resp = self.client.post(
            "/api/quota/allocate",
            json={"agent_id": "api_agent_001", "amount": 999},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(resp.status_code, 409)

    def test_rule_blocked_by_whitelist(self):
        resp = self._create("req_rule_block", payee="OtherVendor")
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body["reason_code"], "RULE_BLOCKED")
        self.assertEqual(body["request"]["status"], "REJECTED")

    def test_create_and_sign_success(self):
        self.assertEqual(self._create("req_sign_ok", amount=1).status_code, 201)
        signed = self._sign("req_sign_ok")
        self.assertEqual(signed.status_code, 200)
        detail = self.client.get("/api/requests/req_sign_ok", headers={"X-User-Token": "user-token"}).get_json()["request"]
        self.assertEqual(detail["status"], "SUCCESS")

    def test_request_rejected_when_available_insufficient(self):
        self.assertEqual(self._create("req_big", amount=30).status_code, 409)

    def test_preauth_direct_execute(self):
        pre = self.client.post(
            "/api/preauths",
            json={"agent_id": "api_agent_001", "total_amount": 3, "window_hours": 24, "payee_whitelist": ["DeepSeek"]},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(pre.status_code, 201)
        created = self._create("req_auto_exec", amount=0.5)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["request"]["status"], "SUCCESS")

    def test_consumption_hash_recomputes(self):
        self.assertEqual(self._create("req_hash", amount=0.8).status_code, 201)
        signed = self._sign("req_hash")
        self.assertEqual(signed.status_code, 200)
        req = signed.get_json()["request"]
        cons = self.client.get("/api/consumptions", headers={"X-User-Token": "user-token"}).get_json()["consumptions"]
        one = [c for c in cons if c["request_id"] == "req_hash"][0]
        raw = f"req_hash|api_agent_001|DeepSeek|0.80|buy api calls|{req['executed_at']}"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.assertEqual(one["tx_hash"], expected)

    def test_connector_binding_flow(self):
        i = self.client.post(
            "/api/connectors/install-link",
            json={"agent_name": "Demo Agent"},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(i.status_code, 201)
        install_id = i.get_json()["install_id"]
        bind_token = i.get_json()["bind_token"]

        b = self.client.post(
            "/api/connectors/bind-complete",
            json={"install_id": install_id, "agent_id": "demo_agent_01", "agent_name": "Demo Agent"},
            headers={"X-Agent-Token": "agent-token"},
        )
        self.assertEqual(b.status_code, 200)

        c = self.client.post(
            "/api/connectors/confirm-binding",
            json={"bind_token": bind_token},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(c.status_code, 200)

        profile = self.client.get("/api/user/profile", headers={"X-User-Token": "user-token"}).get_json()
        self.assertGreaterEqual(profile["bound_agents_count"], 1)

    def test_replay_nonce_is_rejected(self):
        self.assertEqual(self._create("req_nonce_a", amount=0.1).status_code, 201)
        replay = self.client.post(
            "/api/pay-requests",
            json={
                "request_id": "req_nonce_b",
                "agent_id": "api_agent_001",
                "payee": "DeepSeek",
                "amount": 0.1,
                "purpose": "buy api calls",
                "expires_at": iso_in(10),
                "nonce": "nonce_req_nonce_a",
                "issued_at": iso_in(0),
            },
            headers={"X-Agent-Token": "agent-token"},
        )
        self.assertEqual(replay.status_code, 409)

    def test_dashboard_blocks_present(self):
        data = self.client.get("/api/dashboard", headers={"X-User-Token": "user-token"}).get_json()
        for key in ["summary", "quota_summary", "agents", "pending_requests", "consumptions", "audit_events", "connector_status"]:
            self.assertIn(key, data)

    def test_legacy_wallet_transfer_maps_to_allocate(self):
        resp = self.client.post(
            "/api/wallets/transfer",
            json={"from_wallet": "cold", "to_wallet": "warm", "agent_id": "api_agent_001", "amount": 2},
            headers={"X-User-Token": "user-token"},
        )
        self.assertEqual(resp.status_code, 200)
        wallets = self.client.get("/api/wallets", headers={"X-User-Token": "user-token"}).get_json()
        self.assertEqual(wallets["warm_wallet"]["balance"], 22.0)

    def test_expired_request_cannot_sign(self):
        self.assertEqual(self._create("req_expired", amount=0.1).status_code, 201)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE payment_requests SET expires_at=? WHERE request_id=?", (iso_in(-1), "req_expired"))
            conn.commit()
        signed = self._sign("req_expired")
        self.assertEqual(signed.status_code, 409)


if __name__ == "__main__":
    unittest.main()
