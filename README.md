# Aegis Agent Wallet

Aegis is a **non-custodial, human-in-the-loop payment approval layer** for AI Agents.

It allows Agents to initiate structured payment requests, while ensuring every real execution is controlled by natural-person approval (or explicit preauthorization windows set by that person).

## Why Aegis
- Human final approval by default
- Agent has no payment private key
- Three-layer control: protected balance, available quota, policy rules
- Full auditability with reason codes and verifiable transaction hashes
- Connector-based binding flow for third-party Agents

## MVP Capabilities
- Agent request intake (`/api/pay-requests`)
- Approval flow (`/api/pending-requests`, `/api/sign`)
- Quota model (`protected_balance` / `available_quota`)
- Policy engine (whitelist, single-limit, daily-limit, allowed hours)
- Preauthorization window support
- Connector install and bind flow
- Consumption ledger + audit event stream
- Mobile-friendly web dashboard

## Architecture
- **Agent Layer**: SDK/Connector sends signed, structured requests
- **Aegis Gateway**: validation, routing, policy/quota checks, execution orchestration, callbacks, audit logs
- **User Client (Web/App)**: approval signing, quota controls, policy setup, monitoring

## Quick Start
```powershell
cd "D:\agent wallet\simulation_mvp"
python -m pip install -r requirements.txt
python backend\app.py
```

Optional:
```powershell
python agent\callback_server.py
python agent\agent_sim.py --mode balance --interval 5 --callback-url "http://127.0.0.1:7001/callback"
```

Visit:
- Local: `http://127.0.0.1:5000/`
- LAN: `http://<your-pc-ip>:5000/`
- Default demo user token: `dev-user-token`

## Test
```powershell
python -m unittest tests\test_api.py -v
powershell -ExecutionPolicy Bypass -File tests\smoke_e2e.ps1
```

## Main Docs
- `README_CN.md`: Chinese setup + API overview
- `Aegis_Project_Framework.md`: General project framework
- `MVP_ACCEPTANCE_GUIDE.md`: Demo acceptance checklist
- `AUDIT_REPORT.md`: Security/code-audit notes

## Compliance Positioning
Aegis is designed as an **approval/information intermediary** rather than a fund custodian:
- No fund custody
- No private key custody for e-CNY payment signing
- Focus on authorization, policy control, and audit

## Disclaimer
Current repository implementation is a simulation MVP for product validation and demo. It does not directly execute real e-CNY settlement in production.
