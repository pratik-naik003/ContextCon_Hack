<p align="center">
  <h1 align="center">PlaceMate</h1>
  <p align="center"><strong>Hire and get hired — without leaving your chat.</strong></p>
  <p align="center"><em>YC Hackathon 2026 — Crustdata Track</em></p>
</p>

<p align="center">
  <a href="#features">Features</a> |
  <a href="#architecture">Architecture</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="#security">Security</a> |
  <a href="#api-integration">API Integration</a> |
  <a href="#deployment">Deployment</a> |
  <a href="#revenue-model">Revenue Model</a>
</p>

<p align="center">
  <code>Status: Active Development</code>
</p>

---

## What is PlaceMate?

Most hiring tools ask you to download an app nobody uses.

We built PlaceMate — a placement officer that lives inside Telegram, the app students and recruiters already have open.

**Students** paste their resume once. PlaceMate watches 300+ companies in real time, and the moment a matching role opens it doesn't just notify you — it teaches you exactly what the job needs through a 3-minute micro-lesson, quizzes you to prove it, then hands you a personalized cold email drafted for that specific hiring manager. No app. No onboarding. No friction.

**Recruiters** get the same zero-friction experience. Type `/find React engineers at Razorpay` into Telegram and get back real verified profiles in seconds — pulled live from a 3.3M+ person index.

> **The insight:** The best product is the one that meets people where they already are. We didn't build another job board. We built the placement officer that lives in your pocket, in the app you're already using, ready the moment opportunity shows up.

---

## The Problem

**40 million college students. 50,000 placement cells. Still on Excel.**

Students miss hiring opportunities because they find out too late — after the application window closes, after the funding round that created 50 new roles, after the VP of Engineering joins from Google and starts building her team.

Meanwhile, [Crustdata](https://crustdata.com) has live signals on every hiring event in the world. We connected them — on Telegram.

## What PlaceMate Does

PlaceMate is an AI-powered Telegram bot that acts as a **personal placement officer** for every student. It watches 300+ companies in real time via Crustdata's API and pings students the *moment* an opportunity matches their profile — not a day later, not a week later, the moment it happens.

When a signal fires, students don't just get a notification. They get a **3-day crash course** on the exact skills the JD requires, a **mastery quiz** to prove they're ready, and a **GPT-drafted cold email** personalized to the hiring manager — referencing the specific company event that created the opening.

Recruiters get a **reverse search engine** for verified, skill-tested candidates.

## Features

### For Students
- **Real-time signal detection** — funding rounds, hiring surges, exec joins, new JDs
- **AI-powered skill matching** — GPT extracts skills from resumes and matches against JD requirements
- **Micro-learning engine** — bite-sized lessons + quizzes for missing skills
- **Mastery verification** — scored quizzes that unlock the "apply" action
- **Cold email generator** — personalized outreach referencing specific company events
- **Hiring manager intelligence** — name, title, background, and connection points via Crustdata

### For Recruiters
- **Natural language search** — `/find 10 3rd-year CS students with React + Node at tier-1 colleges`
- **Verified skill scores** — not self-reported, quiz-verified mastery percentages
- **Direct messaging** — reach candidates through PlaceMate's trusted channel

### For Placement Cells
- **Dashboard analytics** — placement rates, company engagement, skill gap reports
- **Bulk student onboarding** — import rosters, auto-assign target companies
- **Event calendar integration** — sync with campus recruitment schedules

## Architecture

```
                            PlaceMate System Architecture
    
    +------------------+        +-------------------+        +------------------+
    |                  |        |                   |        |                  |
    |    Telegram      | <----> |   PlaceMate Bot   | <----> |   Crustdata API  |
    |    (Students &   |  Bot   |   (Python 3.11+)  |  HTTPS |   - Company      |
    |     Recruiters)  |  API   |                   |        |   - Person       |
    |                  |        |   +-------------+ |        |   - Job Listings |
    +------------------+        |   | Handlers    | |        |   - Watcher      |
                                |   |  - Onboard  | |        +------------------+
                                |   |  - Signal   | |
                                |   |  - Tutor    | |        +------------------+
                                |   |  - Apply    | |        |                  |
                                |   |  - Recruit  | |        |   OpenAI API     |
                                |   +-------------+ | <----> |   (GPT-4o-mini)  |
                                |                   |  HTTPS |   - Skill extract |
                                |   +-------------+ |        |   - Signal compose|
                                |   | Workers     | |        |   - Email draft  |
                                |   |  - Watcher  | |        |   - Query parse  |
                                |   |  - Dispatch | |        +------------------+
                                |   +-------------+ |
                                |                   |
                                |   +-------------+ |        +------------------+
                                |   | Data Layer  | |        |                  |
                                |   |  - SQLite   | | -----> |   Railway        |
                                |   |  - Encrypt  | |  Deploy|   (Production)   |
                                |   |  - Cache    | |        |                  |
                                |   +-------------+ |        +------------------+
                                +-------------------+
```

### Data Flow

```
  WATCHER LOOP (every 60s)                    STUDENT FLOW
  ========================                    ============

  Crustdata API                               /start
       |                                         |
       v                                         v
  Poll companies ──> Diff against            Onboard flow
  (jobs, funding,    last snapshot            (name, college,
   exec changes)         |                    resume, role)
       |                 v                        |
       |           New event?                     v
       |              |   |                  GPT extracts
       |           No |   | Yes              skills from
       |              |   |                  resume text
       v              v   v                       |
    Sleep(60s)   Insert event                     v
                      |                      Seed watched
                      v                      companies via
                 Match students              Crustdata search
                 (skills, roles,                  |
                  target companies)               v
                      |                      "Watching 300+
                      v                       companies for you"
                 Compose signal
                 message (GPT)
                      |
                      v
            +--------------------+
            | Signal Notification|
            | "Company X just    |
            |  posted a role..." |
            +--------------------+
                   |    |    |
            +------+    |    +--------+
            |           |             |
            v           v             v
       "Get me      "Apply        "Skip"
        ready"      anyway"
            |           |
            v           v
       Lesson +     Cold email
       Quiz flow    generator
            |        (GPT + HM
            v         data from
       Mastery?      Crustdata)
       >= 80%
            |
            v
       Unlock
       cold email
```

### Recruiter Flow

```
  Recruiter                PlaceMate              Database
  =========                =========              ========

  /recruiter ──────────>  Verify email  ────────> Check via
                          via Crustdata            reverse_lookup
                               |
                          Verified? ──> Yes ──>  Mark verified
                               |
                          /find "10 CS           
                           students with         
                           React + Node" ──────> GPT parses query
                               |                      |
                               v                      v
                          SQL + semantic         Ranked student
                          ranking                cards with
                               |                 mastery scores
                               v
                          Return top N
                          with inline
                          "Message via
                           PlaceMate" button
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Runtime** | Python 3.11+ | Async-first, type-hinted |
| **Bot Framework** | python-telegram-bot 21.6 | Telegram Bot API wrapper |
| **AI** | OpenAI GPT-4o-mini | Skill extraction, signal composition, email drafting |
| **Data Intelligence** | Crustdata API | Company search, person search, job listings, event detection |
| **Database** | aiosqlite (SQLite) | Async database with encryption at rest |
| **Validation** | Pydantic v2 | Input/output schema enforcement |
| **HTTP** | httpx | Async HTTP client for API calls |
| **Deployment** | Railway | Long-running Python process hosting |
| **Security** | cryptography (Fernet) | PII encryption at rest |

## Project Structure

```
placemate/
├── .env.example                  # Environment variable template
├── .gitignore                    # Security-conscious gitignore
├── requirements.txt              # Pinned dependencies
├── README.md                     # This file
├── main.py                       # Application entry point
├── config.py                     # Environment loading + validation
├── db.py                         # Database schema + encrypted CRUD helpers
├── crustdata.py                  # Crustdata API client (with cache + fallback)
├── llm.py                        # OpenAI wrapper + prompt templates
├── security.py                   # Encryption, rate limiting, audit logging
├── handlers/
│   ├── __init__.py
│   ├── student_onboard.py        # /start → profile capture state machine
│   ├── student_signal.py         # Push notifications on Watcher events
│   ├── tutor.py                  # Lesson delivery + quiz + mastery scoring
│   ├── apply.py                  # Cold email generator via GPT + Crustdata
│   ├── recruiter.py              # /recruiter verification + /find search
│   └── demo.py                   # /demo scripted flow (offline-safe)
├── workers/
│   ├── watcher_poll.py           # Background Crustdata polling loop
│   └── event_dispatcher.py       # Event → eligible student matching
├── models/
│   ├── __init__.py
│   ├── student.py                # Pydantic models for student data
│   ├── event.py                  # Pydantic models for Crustdata events
│   └── recruiter.py              # Pydantic models for recruiter data
├── tests/
│   ├── test_crustdata.py         # API client tests
│   ├── test_db.py                # Database operation tests
│   ├── test_handlers.py          # Handler logic tests
│   └── test_security.py          # Security module tests
└── assets/
    ├── lessons/                  # Skill lessons + quiz JSON
    │   ├── postgres_indexing.json
    │   ├── redis_caching.json
    │   └── system_design_basics.json
    ├── demo_students.json        # Pre-staged demo data
    └── demo_events.json          # Pre-staged Crustdata-shaped events
```

## Quick Start

### Prerequisites

- Python 3.11+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Crustdata API Key ([crustdata.com](https://crustdata.com))
- OpenAI API Key ([platform.openai.com](https://platform.openai.com))

### Setup

```bash
# Clone the repository
git clone https://github.com/pratik-naik003/ContextCon_Hack.git
cd ContextCon_Hack

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Generate encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add the output to ENCRYPTION_KEY in .env

# Run the bot
python main.py
```

### Verify Crustdata Connection

```bash
# Test company search
curl -X POST 'https://api.crustdata.com/screener/company/search' \
  -H 'Authorization: Token YOUR_CRUSTDATA_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"filters":[{"filter_type":"COMPANY_HEADCOUNT","type":"in","value":["201-500"]}],"page":1}'

# Test person search
curl -X POST 'https://api.crustdata.com/screener/person/search' \
  -H 'Authorization: Token YOUR_CRUSTDATA_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"filters":[{"filter_type":"CURRENT_TITLE","type":"in","value":["VP Engineering"]}],"page":1}'
```

## Security

PlaceMate implements production-grade security from day one:

- **Encryption at rest** — Student PII (names, colleges, resume text, skills) encrypted using Fernet (AES-128-CBC + HMAC-SHA256) before SQLite storage via application-level encrypt-before-store
- **Secrets management** — All API keys stored in environment variables, never committed to code; `.env` in `.gitignore`
- **Transport security** — All external API calls (Crustdata, OpenAI, Telegram) enforce HTTPS/TLS
- **Input validation** — Pydantic models validate all user inputs at system boundaries before processing
- **SQL injection prevention** — Parameterized queries only; zero string concatenation in SQL statements
- **Rate limiting** — Per-user command throttling prevents abuse and API cost runaway
- **Audit logging** — Sensitive operations (data access, API calls, state changes) logged with timestamps and user context
- **Secure session state** — In-memory onboarding state with TTL expiry; no sensitive data persisted unnecessarily
- **Error sanitization** — User-facing errors reveal no stack traces, internal paths, or sensitive details
- **Least privilege** — Bot runs with minimal filesystem and network permissions
- **Dependency scanning** — `pip-audit` integrated for vulnerable package detection

## API Integration

### Crustdata Endpoints Used

| Endpoint | Purpose | Feature |
|----------|---------|---------|
| `POST /screener/company/search` | Find companies by headcount, industry, funding stage, region | Student company watchlist seeding |
| `POST /screener/person/search` | Find people by title, company | Hiring manager intelligence |
| `GET /data_lab/job_listings/` | Get active job listings for a company | New JD signal detection |
| `POST /screener/person/enrich` | Reverse lookup by email | Recruiter verification |

### Resilience Strategy

Every Crustdata call is wrapped with:
1. **5-minute response cache** — identical queries served from cache
2. **Automatic retry** — 3 attempts with exponential backoff
3. **Graceful fallback** — pre-staged demo data served if API is unreachable
4. **Rate limit awareness** — request throttling to stay within API limits

This means the bot **never shows an error** during a live demo, even if the API is down.

## Deployment

### Railway (Recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and link
railway login
railway link

# Deploy
railway up
```

### Environment Variables on Railway

Set these in the Railway dashboard:
- `TELEGRAM_BOT_TOKEN`
- `CRUSTDATA_API_KEY`
- `OPENAI_API_KEY`
- `ENCRYPTION_KEY`
- `DATABASE_URL=sqlite:///placemate.db`
- `WATCHER_POLL_SECONDS=60`
- `DEMO_MODE=false`
- `LOG_LEVEL=INFO`

### Health Check

The bot logs a heartbeat every 60 seconds. Monitor via Railway logs:
```
INFO: Watcher poll complete — 0 new events, 47 companies checked
INFO: Watcher poll complete — 2 new events, 47 companies checked
```

## Revenue Model

| Stream | Who Pays | Price | Phase |
|--------|----------|-------|-------|
| **SaaS** | Placement cells | INR 2-10L/year | Post-hackathon |
| **Marketplace** | Course platforms (NPTEL, Coursera) | 30% affiliate commission | Phase 2 |
| **Recruiter Premium** | Recruiters | INR 50K/month | Phase 2 |

### The Wedge

Current Crustdata ICP: sales teams, recruiting firms, VCs.

**New ICP: college placement cells.** PlaceMate is the wedge into EdTech — every placement cell becomes a Crustdata customer without knowing it.

## Demo

Run `/demo` in the Telegram bot for a scripted 90-second walkthrough that works offline:

1. Simulated Crustdata signal (funding round at a target company)
2. Signal notification with skill match analysis
3. "Get me ready" → micro-lesson → quiz
4. Mastery unlock → cold email draft to hiring manager

All with typing indicators and realistic pacing. Uses pre-staged data from `assets/demo_events.json`.

## Team

Built for the YC Hackathon (Crustdata Track) by:
- **Pratik Naik** — [GitHub](https://github.com/pratik-naik003)
- **Rushiikesh Chandanshiv** — [GitHub](https://github.com/rushiikeshchandanshiv)

## License

MIT

---

<p align="center">
  <strong>PlaceMate</strong> — Because the best time to apply is the moment the opportunity is created.
</p>
