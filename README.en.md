# Moly Daigou

[中文](README.md) | **English**

A lightweight personal shopping/daigou system: products with variants & inventory, cart & orders, payment proof upload & shipping flow, chat, admin panel, and warehouse insights. Uses SQLite by default and supports one-command Docker setup.

## Features

### Storefront
- Product browsing (multiple images, multiple variants, variant stock & price linkage)
- Sign up / login (email verification code), shipping addresses
- Cart, checkout, cancel order, upload payment proof
- Order details, shipping notification (with tracking number)
- Light/dark theme, image zoom

### Admin
- Admin login (credentials via environment variables)
- **Product management**: images, variants (name / selling price / cost / stock / variant image), pin to top, delete
- **Order management**: filter, create, mark as paid, change status, export shipping list
- **Shipping list**: group pending shipments by batch (same date + same user), enter tracking number to mark shipped, shipped list, email notification
- **User management**: create user, ban/unban, edit, delete
- **Warehouse dashboard**: inventory by product/variant; **Trends**: top-10 sales in last 1/7/30 days + bar chart
- **Database**: read tables; after password verification, double-click cells to edit
- Dashboard, basic settings, version management

### Others
- **Chat**: two-way user/admin chat (text, images, files)
- **Scheduled jobs**: auto-cancel unpaid orders, clean expired verification codes
- **RFID ingest API**: `POST /api/rfid/ingest`, supports `productId;variantId;qty` or `productId;L:localVariantId;qty` for hardware/simulator stock-in

## Tech Stack

Flask + SQLAlchemy + Flask-Login + Flask-Migrate + Bootstrap 5 + SQLite (default)

## Project Structure

```
moly_daigou/
├── app.py                 # app entry
├── wsgi.py                # Gunicorn entry
├── gunicorn.conf.py       # Gunicorn config
├── core/                  # core: extensions, models, utilities
├── blueprints/            # routes: frontend, admin_bp, chat, api_rfid
├── services/              # mail, scheduled tasks
├── templates/             # Jinja2 templates
├── migrations/            # Flask-Migrate migrations
├── simulate_hardware/     # RFID simulator & docs
├── deploy/                # deployment examples (e.g. nginx.conf.example)
├── scripts/               # optional scripts
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
├── README.en.md
└── DEPLOYMENT.md
```

## Quick Start

### Option A: Docker (Recommended)

```bash
# 1) Clone
git clone https://github.com/yourusername/moly_daigou.git
cd moly_daigou

# 2) Env vars
cp .env.example .env
# Edit .env, at minimum: SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD

# 3) Build & run
docker compose up -d --build

# 4) Apply migrations (first run)
docker compose exec moly_daigou flask db upgrade
```

Visit: storefront `http://localhost:5000`, admin `http://localhost:5000/admin`

### Option B: Local Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD

flask db upgrade
python app.py
```

## Environment Variables

Create `.env` in the project root (see `.env.example`, which contains full inline notes):

| Variable | Required | Description |
|---|---:|---|
| `SECRET_KEY` | Yes | Session signing key; use a strong random string in production |
| `ADMIN_USERNAME` | Yes | Admin login username |
| `ADMIN_PASSWORD` | Yes | Admin login password (stored as hash) |
| `DATABASE_URL` | No | DB URL, default `sqlite:///daigou.db` |
| `FLASK_ENV` | No | `development` / `production` |
| `FLASK_DEBUG` | No | Debug mode (`True` in development) |
| `SMTP_SERVER` | No | SMTP server host |
| `SMTP_PORT` | No | SMTP port (465=SSL, 587=TLS) |
| `SENDER_EMAIL` | No | Sender email |
| `SENDER_PASSWORD` | No | Sender app password (not login password) |
| `DEFAULT_RECEIVER_EMAIL` | No | Default receiver (testing/system notifications) |
| `MAX_CONTENT_LENGTH` | No | Upload size limit (bytes), default ~50MB |
| `UPLOAD_FOLDER` | No | Upload directory, default `static/uploads` |
| `TIMEZONE` | No | Timezone, default `Asia/Shanghai` |
| `RFID_API_KEY` | No | RFID ingest API key; if not set, the endpoint returns 401 |
| `DATABASE_PASSWORD` | No | Database edit-mode password for admin UI |

Notes: Admin access is limited to the account matching `ADMIN_USERNAME`. RFID auth supports header `X-API-Key` or query `api_key`.

## Data & Directories

- **Database**: default `instance/daigou.db` (SQLite)
- **Uploads**: `static/uploads/` (product images, payment proofs, chat files, covers, QR codes, etc.)

## Database Migrations

```bash
flask db upgrade
flask db migrate -m "message"
```

Docker: `docker compose exec moly_daigou flask db upgrade`

## Warehouse & RFID Stock-in

- **Admin UI**: warehouse page shows inventory & sales trends; variants have a per-product **local variant id** starting from 1.
- **API**: `POST /api/rfid/ingest`, example body `{"data":"2;L:1;3"}` means product 2, local variant 1, increase stock by 3. See `simulate_hardware/README.md`.

## Production Deployment

- **Server**: use Gunicorn (see `wsgi.py`, `gunicorn.conf.py`) behind Nginx.
- **Scheduler**: in production, enable via `RUN_SCHEDULER=1` with a single worker, or disable and run via system cron.
- **Security**: always use HTTPS; never commit secrets; use strong `SECRET_KEY` and admin password.

See `DEPLOYMENT.md` for operations notes (Gunicorn/Nginx/systemd/Docker).

