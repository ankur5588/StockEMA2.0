# ChartinkTrade — Product Requirements Document

## Problem Statement
Build an application which can login into stock broker Kotak Neo, receive signals from Chartink via webhook, place orders automatically, compute EMA10 on open positions, and place EMA10-based stoploss orders.

## User Choices (captured)
- Broker: **Kotak Neo API** (via `neo_api_client` SDK)
- Signals: **Chartink Webhook** (inbound POST)
- Auth: **Emergent Google Social Login**
- EMA10 rule: **Pull open positions daily → compute daily EMA10 → place SL order**

## Architecture
- Backend: FastAPI + MongoDB (motor)
- Frontend: React + Tailwind + shadcn/ui
- Encryption: Fernet (cryptography) for stored Kotak credentials
- Market data: yfinance (NSE/BSE daily candles for EMA10)

## Core Modules Implemented (May 2026)
1. **Auth (Emergent Google)** — `/api/auth/session`, `/api/auth/me`, `/api/auth/logout` + httpOnly cookie + Bearer fallback
2. **Kotak credentials vault** — `POST/DELETE /api/kotak/credentials` (Fernet-encrypted, per-user), `GET /api/kotak/status`
3. **Kotak 2-step login** — `POST /api/kotak/login` → OTP challenge, `POST /api/kotak/verify-otp` → session in memory
4. **Positions** — `GET /api/kotak/positions`, `GET /api/kotak/holdings` (normalised shape)
5. **Alert configs CRUD** — `GET/POST/DELETE /api/alerts` (alert_name, side, qty, product, segment)
6. **Chartink webhook** — `POST /api/webhooks/chartink/{token}` (public, token-scoped). Accepts JSON + form-urlencoded. Matches alert_name → config → places MKT order via Kotak
7. **EMA10 stoploss run** — `POST /api/ema-sl/run` pulls positions, yfinance daily EMA10, places SL order at EMA10 trigger
8. **Logs** — `GET /api/webhooks/logs`, `/api/trades/logs`, `/api/ema-sl/logs`

## Frontend
- Login page (split-screen, Emergent Google button)
- Dashboard: Connection (Kotak status + login/setup dialogs), Webhook URL card (copy), EMA10 Stoploss panel (confirm-then-run), Positions table, Alert Configs, Webhook feed, Trade log
- Live Trading warning banner (amber)
- Dark terminal aesthetic (JetBrains Mono for numbers, IBM Plex Sans for UI)

## Test Status (as of May 2026)
- Backend: **18/18 passing** via pytest (`/app/backend/tests/backend_test.py`)
- Frontend: manual smoke tested via screenshots (login & dashboard render correctly)

## Backlog
### P1 — Next features
- Scheduled cron for daily EMA10 SL run (currently manual only)
- Store Kotak session token in Mongo so login survives backend restart (currently in-memory)
- Live quote streaming via Kotak Neo websocket for positions table LTP/PnL
- Per-alert filters: max daily trades, cooldown, position sizing

### P2 — Nice to have
- Chartink webhook signature verification
- Multi-worker deployment support for sessions
- Export trade logs CSV
- Dry-run / paper-trade toggle

## Known Limitations
- Kotak Neo SDK pins older `requests` version which conflicts with other packages (mitigated by installing outside requirements.txt)
- No real Kotak credentials in test environment → Kotak-dependent flows validated via 400 error paths only

## Update — May 2026: SEBI / Static IP Compliance
- Added `GET /api/deployment/info` endpoint that detects outbound IP + platform
- Added **Compliance card** on dashboard showing outbound IP, platform, POOLED vs STATIC badge, and SEBI algo-trading notice
- Added `STATIC_IP_DEPLOYMENT` env flag to toggle the compliance badge to green on production VPS
- Added `/app/README.md` with full self-host instructions for a VPS with reserved static IP (DigitalOcean Reserved IP, AWS Elastic IP, Linode, Hetzner)

**Clarified with user**: user has both Kotak consumer key and secret. No code change needed for credentials form.

**Important**: The app CANNOT make the IP static from code. Static IP is a property of hosting infrastructure. On Emergent preview the outbound IP is pooled/shared and will eventually change. For production SEBI-regulated trading the user must deploy to a VPS with a reserved static IP per the README.

## Update — May 2026: Multi-broker support (Dhan + Alice Blue)
- Added **DhanHQ** integration (`dhanhq` v2.2 SDK, uses `DhanContext` wrapper). Flow: save client_id + access_token → connect → place orders / fetch positions
- Added **Alice Blue ANT API** integration (`pya3` SDK). Flow: save user_id + api_key → connect (SHA256 session handshake) → orders
- New collections: `dhan_credentials`, `alice_credentials`, `user_webhooks`
- Alert config now has `broker` field (kotak_neo | dhan | alice_blue)
- Chartink webhook router picks broker per-alert
- EMA10 stoploss now iterates across all authenticated brokers
- New endpoint `GET /api/brokers/status` returns unified state + user-level webhook URL
- New endpoint `GET /api/positions/all` aggregates positions across all authenticated brokers
- Frontend: 3 broker cards in one row (Kotak, Dhan, Alice Blue), alert form has broker dropdown, positions table shows broker column

Test status: 26/26 new multi-broker backend tests passing (100%). Existing Kotak + auth + webhook + logs tests also passing from iteration 1.

## Kotak login fix
Root cause was Kotak's OAuth rejecting user's consumer_key/secret (HTTP 401). Our error messages now clearly guide the user to: activate the app, use Trade API keys (not Data API), remove whitespace, regenerate the key+secret pair. User needs to resolve on Kotak's dashboard side - code is correct.
