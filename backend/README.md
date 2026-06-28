# CycleStats

Self-hosted cycling and health analytics dashboard. Aggregates data from **Strava** and **Garmin** into a unified view with AI coaching, power curves, fitness trends, training load analysis, and gear tracking.

## Features

- **Strava OAuth** — one-click import of rides with full stream data (power, HR, cadence, GPS)
- **Garmin sync** — daily health checkins (RHR, HRV, sleep, weight, body fat %)
- **AI Coach** — daily coaching notes via DeepSeek, plus per-activity AI insights with cardiac drift, efficiency factor, and decoupling analysis
- **Performance Management Chart (PMC)** — CTL, ATL, TSB with 42/7-day exponential moving averages
- **Power Curve** — best efforts across durations with FTP reference lines
- **Power Profile** — 5s, 1m, 5m, 20m, 60m bar chart
- **Power Training Zones** — Coggan 7-zone model with time-in-zone bar chart
- **Training Calendar** — GitHub-style 365-day TSS heatmap
- **Activity Insights** — stat badges, AI-generated text, and colour-coded HR metrics (drift, EF, decouple)
- **Activity Notes & Tags** — free-text notes + 13 emoji tags per activity
- **Gear Tracking** — mileage tracking with replacement alerts (shoes, chain, cassette, tyres, bike)
- **CSV/JSON Export** — download all activities with full metadata
- **Search & Filter** — name search, sport filter, date range on activities
- **Segments** — auto-detected local segments + Strava starred segments
- **Stream Charts** — power, HR, cadence, speed, altitude overlays with Chart.js
- **GPS Map** — Leaflet route map per activity
- **Dark/Light Theme** — persistent user preference
- **Login Page** — session-based authentication

## Quick Start

```bash
# Clone the repo
git clone https://github.com/gurudc/CycleStats.git
cd CycleStats/backend

# Install dependencies
pip install -r requirements.txt

# Set up PostgreSQL
createdb cyclestats
psql cyclestats < schema.sql

# Configure environment
cp .env.example .env
# Edit .env with your Strava client ID/secret, Garmin credentials, DeepSeek API key

# Run
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Configuration

Set these environment variables (or copy `.env.example` to `.env`):

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `STRAVA_CLIENT_ID` | Yes | Strava API client ID |
| `STRAVA_CLIENT_SECRET` | Yes | Strava API client secret |
| `DEEPSEEK_API_KEY` | No | DeepSeek API key for AI coaching |
| `GARMIN_EMAIL` | No | Garmin Connect email |
| `GARMIN_PASSWORD` | No | Garmin Connect password |

## API Overview

| Endpoint | Description |
|----------|-------------|
| `GET /api/activities/` | List activities (paginated, filterable) |
| `GET /api/activities/{id}` | Activity detail with streams, insights, gear |
| `POST /api/activities/upload` | Upload .fit/.gpx/.tcx file |
| `PATCH /api/activities/{id}/notes` | Update activity notes |
| `GET /api/activities/export/csv` | Download all activities as CSV |
| `GET /api/training/pmc` | CTL/ATL/TSB time series |
| `GET /api/training/power-curve` | Best power durations |
| `GET /api/training/power-profile` | Power profile by duration |
| `GET /api/training/zones` | Power zones with time-in-zone |
| `GET /api/training/calendar` | Daily TSS for heatmap |
| `GET /api/training/insights` | Training insights summary |
| `GET /api/health/checkins` | Health checkin history |
| `GET /api/strava/status` | Strava connection status |
| `GET /api/strava/me` | Strava athlete profile |
| `POST /api/strava/import-activities` | Import from Strava |
| `GET /api/gear/` | List tracked gear |
| `POST /api/gear/` | Add gear item |
| `PATCH /api/gear/{id}` | Update gear |
| `DELETE /api/gear/{id}` | Delete gear |
| `PATCH /api/gear/activity/{id}/gear` | Assign gear to activity |
| `GET /api/coach/latest` | Latest AI coach note |
| `POST /api/auth/login` | Login with password |

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend:** Vanilla JavaScript, Chart.js, Leaflet
- **AI:** DeepSeek Chat API for coaching notes & activity insights
- **Infrastructure:** nginx, Cloudflare tunnel, Let's Encrypt (DNS-01), systemd

## Architecture

```
User → Cloudflare → Cloudflare Tunnel → nginx → FastAPI → PostgreSQL
                                                          ↓
                                                    Strava API
                                                    Garmin API
                                                    DeepSeek API
```

## License

MIT
