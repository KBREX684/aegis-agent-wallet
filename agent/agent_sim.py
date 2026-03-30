import argparse
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests


def make_request_payload(args: argparse.Namespace) -> dict:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=args.expire_minutes)
    issued_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    request_id = f"req_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return {
        "request_id": request_id,
        "agent_id": args.agent_id,
        "payee": args.payee,
        "amount": args.amount,
        "purpose": args.purpose,
        "expires_at": expires_at.replace(microsecond=0).isoformat(),
        "issued_at": issued_at,
        "nonce": f"nonce_{request_id}_{uuid.uuid4().hex[:8]}",
        "callback_url": args.callback_url or None,
    }


def send_request(args: argparse.Namespace) -> None:
    payload = make_request_payload(args)
    try:
        resp = requests.post(
            f"{args.server.rstrip('/')}/api/pay-requests",
            json=payload,
            headers={"X-Agent-Token": args.agent_token},
            timeout=5,
        )
        print(f"[AGENT] status={resp.status_code} request_id={payload['request_id']} response={resp.text}")
    except requests.RequestException as exc:
        print(f"[AGENT] failed to send request: {exc}")


def run_manual(args: argparse.Namespace) -> None:
    print("Manual mode started. Press ENTER to trigger a request. Ctrl+C to exit.")
    while True:
        input()
        send_request(args)


def run_interval(args: argparse.Namespace) -> None:
    print(f"Interval mode started. Every {args.interval}s trigger a request. Ctrl+C to exit.")
    while True:
        send_request(args)
        time.sleep(args.interval)


def run_balance_trigger(args: argparse.Namespace) -> None:
    balance = args.start_balance
    print(
        f"Balance mode started. balance={balance:.2f}, threshold={args.threshold:.2f}, "
        f"burn_per_tick={args.burn_per_tick:.2f}"
    )
    while True:
        burn = max(0.01, random.uniform(args.burn_per_tick * 0.8, args.burn_per_tick * 1.2))
        balance = max(0.0, balance - burn)
        print(f"[AGENT] current simulated balance={balance:.2f}")
        if balance < args.threshold:
            print(f"[AGENT] balance below threshold ({args.threshold:.2f}), creating pay request...")
            send_request(args)
            balance += args.topup_after_request
            print(f"[AGENT] simulated balance restored to {balance:.2f}")
        time.sleep(args.interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aegis MVP simulated agent")
    parser.add_argument("--server", default="http://127.0.0.1:5000", help="Aegis backend base URL")
    parser.add_argument("--agent-token", default="dev-agent-token", help="Agent auth token")
    parser.add_argument("--agent-id", default="api_agent_001")
    parser.add_argument("--payee", default="DeepSeek")
    parser.add_argument("--amount", type=float, default=0.05)
    parser.add_argument("--purpose", default="buy 100 api calls")
    parser.add_argument("--callback-url", default="", help="Optional callback URL")
    parser.add_argument("--expire-minutes", type=int, default=10)
    parser.add_argument("--mode", choices=["manual", "interval", "balance", "once"], default="manual")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between checks/triggers")
    parser.add_argument("--start-balance", type=float, default=2.0, help="Used in balance mode")
    parser.add_argument("--threshold", type=float, default=0.8, help="Used in balance mode")
    parser.add_argument("--burn-per-tick", type=float, default=0.3, help="Used in balance mode")
    parser.add_argument("--topup-after-request", type=float, default=1.5, help="Used in balance mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "once":
        send_request(args)
    elif args.mode == "manual":
        run_manual(args)
    elif args.mode == "interval":
        run_interval(args)
    else:
        run_balance_trigger(args)


if __name__ == "__main__":
    main()
