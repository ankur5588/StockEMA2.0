# ChartinkTrade

Automated Indian equity trading: route **Chartink webhook alerts** to **Kotak Neo**, and run **daily EMA10 stoploss** on your open positions.

Built on FastAPI + React + MongoDB. Emergent Google auth. Per-user Fernet-encrypted broker vault.

---

## ⚠️ SEBI Algo-Trading & Static IP

> Under SEBI's algorithmic-trading framework (effective 2025), retail algo orders placed via broker APIs must originate from a **registered, STATIC IP**. Your broker (Kotak Neo) whitelists this IP for your trading account.

The Emergent preview URL **does NOT provide a static outbound IP** — orders sent from the preview environment will eventually be rejected by the broker. You must self-host for production.

### Production deployment checklist

1. **Rent a VPS with a reserved static IP**:
   - DigitalOcean Droplet + **Reserved IP** (free)
   - AWS EC2 + **Elastic IP**
   - Linode / Akamai
   - Hetzner Cloud (EU / cheapest)
   - Minimum spec: 1 vCPU, 2 GB RAM, Ubuntu 22.04
2. **Install stack**:
   ```bash
   apt update && apt install -y python3.11 python3.11-venv nodejs mongodb nginx
   npm install -g yarn
   ```
3. **Save to GitHub** (from Emergent) → clone on the VPS.
4. **Backend**:
   ```bash
   cd /app/backend
   python3.11 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   pip install "git+https://github.com/Kotak-Neo/kotak-neo-api.git"
   pip install yfinance
   cp .env.example .env   # fill MONGO_URL, DB_NAME, FERNET_KEY, STATIC_IP_DEPLOYMENT=true
   ```
5. **Frontend**:
   ```bash
   cd /app/frontend
   yarn install
   # Point REACT_APP_BACKEND_URL to your API domain (https://api.yourdomain.com)
   yarn build
   ```
6. **Systemd service for backend** (`/etc/systemd/system/chartink-backend.service`):
   ```
   [Unit]
   Description=ChartinkTrade backend
   After=network.target mongodb.service
   [Service]
   WorkingDirectory=/opt/chartink/backend
   ExecStart=/opt/chartink/backend/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```
7. **Nginx reverse proxy** — terminate TLS, proxy `/api` → `127.0.0.1:8001`, serve `frontend/build` statically.
8. **Environment flag**: set `STATIC_IP_DEPLOYMENT=true` in backend `.env` so the dashboard's Compliance card shows green.
9. **Whitelist the VPS IP with Kotak Neo** — go to Neo app → Profile → Trade API → add IP.
10. **Register as algo with NSE/BSE** — per SEBI rules, once order volume crosses threshold your broker helps with exchange-level algo registration.

---

## How the app works

### Flow
```
Chartink alert fires
   ↓ (POST webhook)
/api/webhooks/chartink/{your_token}
   ↓
Match alert_name → Alert Config
   ↓
Place MKT order on Kotak Neo → log
```

```
You click "Run EMA10 SL Now"
   ↓
Fetch open positions from Kotak Neo
   ↓
For each long: yfinance daily close → EMA10
   ↓
Place SL-L order at EMA10 → log
```

### Environment variables (backend/.env)
| Var | Description |
|---|---|
| `MONGO_URL` | Mongo connection string |
| `DB_NAME` | Mongo database |
| `FERNET_KEY` | 32-byte urlsafe base64 Fernet key (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins |
| `STATIC_IP_DEPLOYMENT` | Set to `true` on your production VPS so the UI reflects compliance |
| `DEPLOYMENT_NAME` | Optional friendly label (e.g. `DO-Bangalore-1`) |

### Kotak Neo credentials needed
- **Consumer Key** & **Consumer Secret** — from Kotak Neo app → Profile → Trade API → API Dashboard → Create Application
- **Mobile number** (with `+91`), **password**, **MPIN** — your Kotak Neo login credentials

All five are stored **encrypted (Fernet)** in MongoDB, scoped to your user account.

---

## Development (on Emergent)

Backend and frontend are already wired. Make changes, hot-reload handles the rest. To run the backend tests:
```bash
cd /app/backend && pytest tests/backend_test.py -v
```

## License
Private / proprietary. Not financial advice. Use at your own risk.
