# CycleStats

Self-hosted cycling and health analytics dashboard. Aggregates data from **Strava**, **Garmin**, and **Wahoo** into a unified view with power curves, fitness trends, training load analysis, and gear tracking.

## Architecture

```
FastAPI + SQLite (or PostgreSQL) + nginx
Cloudflare tunnel → cyclestats.colahan.cc
```

## Tech Stack

- **Backend:** Python / FastAPI
- **Database:** SQLite (default) or PostgreSQL
- **Auth:** Session-based with bcrypt password hashing
- **Integrations:** Strava API, Garmin, Wahoo
- **Frontend:** Vanilla JS HTML dashboard
- **Infrastructure:** Proxmox LXC, nginx reverse proxy, Cloudflare Tunnel

## Endpoints

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login with username/password |
| GET | `/api/auth/check` | Check session validity |
| POST | `/api/auth/logout` | Destroy session |

### Activities
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/activities` | List all activities |
| GET | `/api/activities/{id}` | Activity detail with streams |
| GET | `/api/activities/{id}/streams` | Raw time-series data |

### Analysis
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/analysis/power-curve` | Best power outputs over duration |
| GET | `/api/analysis/power-profile` | Power distribution by zone |
| GET | `/api/analysis/fitness` | CTL/ATL/Form model |
| GET | `/api/analysis/training-load` | Training load breakdown |
| GET | `/api/analysis/activity-types` | Stats by activity type |

### Integrations
| Method | Path | Provider |
|--------|------|----------|
| GET | `/api/strava/auth` | Start Strava OAuth flow |
| GET | `/api/strava/callback` | Strava OAuth callback |
| POST | `/api/strava/import` | Import activities from Strava |
| GET | `/api/wahoo/auth` | Start Wahoo OAuth flow |
| GET | `/api/wahoo/callback` | Wahoo OAuth callback |
| POST | `/api/garmin/upload` | Upload Garmin FIT files |

### Health & Gear
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | System health check |
| GET | `/api/health/readiness` | Readiness probe |
| GET | `/api/health/metrics` | Health metrics overview |
| GET | `/api/gear` | List bikes and gear |
| GET | `/api/segments` | Stored segment data |

### Coaching
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/coach/plan` | Training plan suggestions |

## Setup

```bash
# Clone
git clone https://github.com/gurudc/CycleStats.git
cd CycleStats/backend

# Install deps
pip install -r requirements.txt

# Database auto-creates on first run
python main.py
```

### Environment

Create `backend/.env`:

```
STRAVA_CLIENT_ID=your_id
STRAVA_CLIENT_SECRET=your_secret
WAHOO_CLIENT_ID=your_id
WAHOO_CLIENT_SECRET=your_secret
GARMIN_EMAIL=your_email
GARMIN_PASSWORD=your_password
```

## Default Login

Default credentials are set in `.env` or `data/auth_password.txt`:

```
Username: cm
Password: (set during initial setup)
```

## Deployment

The app runs behind nginx reverse proxy with Cloudflare tunnel. See `services/ssl_config.py` and `services/tunnel.py` for infra helpers.
