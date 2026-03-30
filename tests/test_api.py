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

    def test_create_and_sign_success(self):
        self.assertEqual(self._create("req_sign_ok", amount=1).status_code, 201)
        signed = self._sign("req_sign_ok")
        self.assertEqual(signed.status_code, 200)

    def test_rule_blocked_by_whitelist(self):
        resp = self._create("req_rule_block", payee="OtherVendor")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["reason_code"], "RULE_BLOCKED")

    def test_consumption_hash_recomputes(self):
        self.assertEqual(self._create("req_hash", amount=0.8).status_code, 201)
        signed = self._sign("req_hash")
        req = signed.get_json()["request"]
        cons = self.client.get("/api/consumptions", headers={"X-User-Token": "user-token"}).get_json()["consumptions"]
        one = [c for c in cons if c["request_id"] == "req_hash"][0]
        raw = f"req_hash|api_agent_001|DeepSeek|0.80|buy api calls|{req['executed_at']}"
        self.assertEqual(one["tx_hash"], hashlib.sha256(raw.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
