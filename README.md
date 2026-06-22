# 🎤 Karaoke Reservation & Operations System

A full-stack web application built to manage karaoke room reservations for a real family-owned restaurant in Madison, WI. This project replaces a manual sticky-note workflow with a centralized, real-time booking system that enforces scheduling rules, calculates pricing, and provides role-based staff controls.

**[🔴 Live Demo](https://karaoke-reservation-system.onrender.com/)** — Log in as a guest to view room availability, or use staff credentials to manage reservations.

> **Demo credentials** — Username: `staff` · Password: `demo`
>
> *(Read-only guest view requires no login. Staff login enables full reservation management.)*

---

## ✨ Features

- **Real-Time Availability Calendar** — Visual day/week view of all karaoke room bookings powered by FullCalendar.
- **Role-Based Access Control** — Unauthenticated users can view the calendar; only authenticated staff can create, edit, or cancel reservations.
- **Conflict & Capacity Validation** — Server-side checks reject overlapping timeslots, over-capacity bookings, and requests outside business hours before any record is written.
- **Dynamic Pricing Engine** — Automatically computes reservation cost using early-bird and peak-hour rates, with configurable tax applied at checkout.
- **Overnight Business Hours** — Custom time normalization handles the restaurant's 11 AM – 1 AM operating window, including after-midnight end times.
- **Walk-In Queue (Idle Area)** — Reservations can be temporarily parked outside the room timeline and reassigned later without losing their data.
- **Audit Log & Reservation History** — Every create, edit, and cancel action is recorded with a snapshot for full traceability.
- **Dual Database Support** — SQLite for local development; PostgreSQL (Neon) for production, switched automatically via `DATABASE_URL`.
- **Automated Migrations** — A lightweight Python migration runner applies schema changes on startup without third-party tooling.

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3, Flask |
| **Database** | PostgreSQL (Neon, production) · SQLite (local) |
| **Frontend** | Vanilla JavaScript · Bootstrap 5 · FullCalendar |
| **Deployment** | Render · Docker |
| **Testing** | Pytest (60+ tests) |
| **Tooling** | Black · Flake8 · rcssmin/rjsmin (asset minification) |

---

## 💡 Origin

While bartending at my family's restaurant, I was solely responsible for managing karaoke reservations through a fragmented workflow: customers submitted requests online, and I manually copied them onto sticky notes per room, then compared the notes to check availability — all while making drinks. Scheduling mistakes were easy to make.

This system replaces that process with a centralized schedule that enforces availability rules automatically, calculates pricing without manual math, and gives staff a clear overview of the day.

---

## ⚙️ Local Setup

### Prerequisites
- Python 3.11+
- pip

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/jimmyhe05/karaoke-reservation-system.git
cd karaoke-reservation-system

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env — set SECRET_KEY, ADMIN_PASSWORD, STAFF_PASSWORD at minimum

# 5. Initialize the database
python -m flask init-db

# 6. (Optional) Seed sample reservations for today
python -m flask seed-sample

# 7. Run the development server
python -m flask run
```

Open **http://127.0.0.1:5000** in your browser.

### Docker

```bash
docker build -t karaoke-reservation .
docker run -p 5000:5000 -v karaoke_data:/data \
  --env DATABASE=/data/karaoke.db \
  karaoke-reservation
```

---

## 🗄️ Production Database (PostgreSQL)

Set `DATABASE_URL` to switch from SQLite to PostgreSQL:

```bash
DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require
APP_ENV=production
SESSION_COOKIE_SECURE=true
```

Then run:
```bash
python -m flask init-db
```

The app detects `DATABASE_URL` automatically and applies the PostgreSQL schema. Migrations are tracked in a `schema_migrations` table and applied on each startup.

---

## 🏗️ Project Structure

```
karaoke-reservation-system/
├── app.py                   # Flask app, routes, auth
├── config.py                # Central configuration
├── schema.sql               # SQLite schema
├── schema_postgres.sql      # PostgreSQL schema
├── routes/
│   └── api.py               # REST API blueprint
├── services/
│   ├── db.py                # Database adapter (SQLite ↔ PostgreSQL)
│   ├── reservations.py      # Core reservation logic
│   ├── validation.py        # Conflict, capacity, blackout checks
│   ├── pricing.py           # Dynamic pricing engine
│   └── blackout.py          # Blackout window rules
├── migrations/
│   └── runner.py            # Lightweight migration runner
├── scripts/
│   ├── backup_db.sh         # SQLite backup utility
│   └── build_assets.py      # CSS/JS minification
├── templates/               # Jinja2 HTML templates
├── static/                  # CSS, JS, minified assets
├── tests/                   # Pytest test suite (60+ tests)
└── docs/
    └── database.md          # Schema reference
```

---

## 🔒 Security Notes

- Staff credentials are environment-variable-only — never hardcoded.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- All mutating operations require an authenticated staff or admin session.
- Weak credentials (`"admin"`, `"password"`, etc.) are rejected at startup.

---

## 🔗 Connect

- **GitHub:** [jimmyhe05](https://github.com/jimmyhe05)
- **LinkedIn:** [jimmy-he-badger](https://www.linkedin.com/in/jimmy-he-badger/)
- **Email:** jimmyhe05@gmail.com
