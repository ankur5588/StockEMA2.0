# ChartinkTrade — PRD

## Original problem statement
Build an application which can log into a stock broker like Kotak Neo, receive
signals from Chartink, place the order, compute EMA10, and place a stoploss
order. Must support multiple brokers and SEBI Static IP algo-trading rules.

## Personas
- Retail Indian trader using Chartink + a broker (Kotak Neo, Dhan, Alice Blue)
- Trader requiring SEBI-compliant static IP for algo trading

## Core requirements
1. Multi-user web app with auth (Google + email/password)
2. Connect multiple stock brokers: Kotak Neo, Dhan, Alice Blue (INDmoney scaffolded)
3. Receive Chartink webhooks → route to the user's chosen broker
4. Daily EMA10 calculation → place stoploss for open long positions
5. SEBI Static IP guidance + one-click VPS deployment script
6. CSV bulk upload for Chartink-symbol → NSE-symbol mapping (qty OR amount)
7. Auto-detect BUY/SELL from Chartink alert name
8. Manual order placement with AMO + auto EMA10 stoploss

## What has been implemented (latest = top)

### 2026-05-17 — Bug fixes batch
- ✅ Symbol Mappings CSV-template download: switched fetch `credentials: "omit"` (was `"include"`) — preview ingress' ACAO:* + Allow-Credentials:true combo silently broke it. Added `appendChild` + remove of the temp anchor and success toast.
- ✅ Manual Order API: response now uses `HTTPException(400)` on broker error, returns clear `{status:"skipped"|"success", message, ema_sl}`. **Auto-EMA10 SL is now correctly skipped (with reason) when AMO=true or order_type=L** — avoids placing a SL before the entry has filled. Frontend shows toast.error (instead of warning) for skipped/error, plus inline result block.
- ✅ Trade Log + Webhook Feed: added floating scroll-to-bottom button (`ArrowDownToLine` icon, bottom-right of card) that smoothly scrolls the list. Appears only when there are >5 rows.

### 2026-05-15 — Manual Order + EMA10 SL
- Bug fix: `POST /api/symbol-mappings` no longer throws `TypeError` (duplicate kwarg).
- New endpoint `POST /api/orders/manual` — broker, symbol, side, qty, order_type
  (MKT/L), price, product (CNC/MIS/NRML), exchange, **AMO** toggle,
  **auto_ema_sl** toggle (BUY only).
- New endpoint `GET /api/ema-preview/{symbol}` — returns EMA10 + SL trigger/limit.
- AMO support added to `kotak_client.place_order`, `dhan_client.place_order`,
  `alice_client.place_order`.
- Frontend `ManualOrderCard.jsx` — full form, broker dropdown shows online/offline
  state, Preview-EMA10 button, AMO toggle, Auto-SL toggle (auto-disabled for SELL).
- 16 backend tests in `/app/backend/tests/test_manual_order_and_mappings.py` — 100% pass.

### 2026-05-15 — Email/Password Auth
- `auth_service.py` with bcrypt + JWT (7-day token), brute-force lockout
  (5 attempts → 15 min), `users.email` unique index, `login_attempts` index.
- New endpoints: `POST /api/auth/register`, `POST /api/auth/login`.
- Login.jsx redesigned with Sign in / Sign up tabs + Google fallback button.
- Admin seeded on startup: `admin@chartink.local / admin123`.

### Pre-existing
- Emergent Google OAuth (Strict-Mode race fix + Bearer token fallback).
- Kotak Neo, Dhan, Alice Blue broker clients (live order + positions).
- Chartink webhook ingress with symbol mapping + auto BUY/SELL detect.
- CSV upload for symbol mappings.
- Daily EMA10 SL run across all connected brokers.
- VPS deploy script + SEBI static IP compliance card.

## Backlog / Roadmap

### 🔴 P0
- Finish INDmoney broker integration (frontend card + brokers/status hook
  + webhook router + EMA SL + AlertsConfig dropdown).

### 🟡 P1
- Cron / APScheduler for automatic daily EMA10 run.
- Dhan token auto-refresh / unlimited token registration UI.
- Auto-detect Intraday (MIS) vs Delivery (CNC) from Chartink alert names.
- Defensive backend check: reject `order_type='L'` when `price<=0` (currently FE-only).
- Add `require_user` dependency to `/api/ema-preview/{symbol}` for consistency.

### 🟢 P2
- "Test webhook" button on dashboard for 1-click pipeline verification.
- MongoDB → S3 daily backup for trade logs & configs.
- Forgot-password / password-reset flow (already scaffolded in playbook).
- Refactor `server.py` (~1450 lines) into `routers/{auth,brokers,webhooks,
  ema_sl,orders,symbol_mappings}.py`.

## Tech stack
- Backend: FastAPI, Motor (async MongoDB), bcrypt, PyJWT, yfinance, pandas,
  kotak-neo-api, dhanhq, pya3 (Alice Blue), Fernet.
- Frontend: React 19 + Vite-style CRA, axios, shadcn/ui, lucide-react, sonner.
- Hosting: SEBI-compliant VPS (`deploy.sh` script). Preview env via Emergent.
