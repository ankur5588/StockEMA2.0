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

### 2026-05-17 — Portfolio Risk dashboard
- ✅ New `GET /api/portfolio/risk` endpoint — aggregates LONG positions across
  all connected brokers, computes EMA10 SL value per position, and rolls up:
  `current_value`, `sl_value`, `invested`, `risk_amount`, `risk_pct`,
  `pnl_amount`, `pnl_pct`, `open_positions`. Returns per-position breakdown +
  positions where EMA10 is unavailable.
- ✅ New `PortfolioRiskCard.jsx` — 4 KPI tiles + animated risk meter (green ≤2%,
  amber ≤5%, red >5%) + sortable per-position breakdown table. Empty state
  when no broker connected.

### 2026-05-17 — INDmoney integration + CSV download fix
- ✅ INDmoney is now a fully wired 4th broker:
  - Backend: 6 new endpoints under `/api/indmoney/*` (credentials CRUD, status, connect, disconnect, positions).
  - `/api/brokers/status`, `/api/positions/all`, `_route_order`, `_place_ema_sl_for`,
    `/api/ema-sl/run`, `/api/orders/manual`, and CSV upload validation all extended.
  - Frontend: new `INDmoneyCard.jsx` with setup dialog + helper note about
    static IP whitelisting & no-US-stocks limitation.
  - INDmoney option added to AlertsConfig + ManualOrderCard + SymbolMappings.
  - Dashboard broker grid now `lg:grid-cols-4`.
- ✅ Symbol Mappings CSV-template download now generated 100% client-side via
  `Blob` — no API call. Bypasses the preview ingress' broken CORS combo that
  silently blocked the previous fetch-based download.
- ✅ Iteration 5 tests: 15/15 backend pass, 6/6 frontend flows verified.

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

### 🟡 P1
- Cron / APScheduler for automatic daily EMA10 run.
- Dhan token auto-refresh / unlimited token registration UI.
- Auto-detect Intraday (MIS) vs Delivery (CNC) from Chartink alert names.
- Move broker session state from in-memory dicts to Mongo-backed sessions
  (so multi-worker / pod restarts don't drop active broker auth).
- Defensive backend check: reject `order_type='L'` when `price<=0` (currently FE-only).
- Add `require_user` dependency to `/api/ema-preview/{symbol}` for consistency.
- Surface the INDmoney "no US stocks" disclaimer in ManualOrderCard / AlertsConfig
  when the user selects `indmoney`.

### 🟢 P2
- Order **basket** (paste multiple symbols + 1-click AMO/SL) — extension of
  /api/orders/manual.
- "Test webhook" button on dashboard for 1-click pipeline verification.
- MongoDB → S3 daily backup for trade logs & configs.
- Forgot-password / password-reset flow.
- Realtime fill-watcher to auto-place EMA10 SL the moment AMO/limit entries fill.
- Multipart `UploadFile` support for `/api/symbol-mappings/upload` (raw text/csv only today).
- Refactor `server.py` (~1569 lines) into modular APIRouters under
  `routers/{auth,kotak,dhan,alice,indmoney,brokers,webhooks,orders,symbol_mappings,ema_sl}.py`.

## Tech stack
- Backend: FastAPI, Motor (async MongoDB), bcrypt, PyJWT, yfinance, pandas,
  kotak-neo-api, dhanhq, pya3 (Alice Blue), Fernet.
- Frontend: React 19 + Vite-style CRA, axios, shadcn/ui, lucide-react, sonner.
- Hosting: SEBI-compliant VPS (`deploy.sh` script). Preview env via Emergent.
