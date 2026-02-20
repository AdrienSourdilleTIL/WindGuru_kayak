# WindGuru Kayak — Fishing Forecast System

Automated daily weather and sea condition forecast tailored for kayak fishing at **La Couarde sur Mer, Île de Ré (France)**. Every morning at 3 AM UTC, the system fetches weather and wave data, computes a fishing suitability score, and emails a rich HTML report.

---

## What It Does

1. **Fetches forecast data** from two sources:
   - [Windguru](https://www.windguru.cz/) (wind speed, gusts, direction, temperature, rain) for spot #48552
   - [Open-Meteo Marine API](https://marine-api.open-meteo.com/) (wave height, period, direction, swell)

2. **Scores each hour** from 0 to 100 using a weighted algorithm that models kayak fishing conditions:

   | Factor | Weight | Ideal | Dangerous |
   |---|---|---|---|
   | Wind speed | 25% | < 15 kts | > 30 kts |
   | Wind gusts | 20% | < 17 kts | > 30 kts |
   | Wave period | 20% | ≥ 12 s | < 6 s |
   | Wave height | 15% | < 0.5 m | > 2.0 m |
   | Rain | 10% | 0 mm | — |
   | Temperature | 10% | 15–25 °C | — |

   A **blocking malus** caps the score at 20/100 if any hard limit is exceeded (wind > 25 kts, gusts > 30 kts, waves > 2.0 m, or wave steepness H/T > 0.18 — detecting short choppy swells even at moderate height).

3. **Generates four charts**: fishing score over 14 days, wind & gusts, wave height & period, temperature & rain.

4. **Builds an HTML report** structured in three reading levels:
   - Today's hourly breakdown (color-coded table)
   - Next 3 days in 3-hour windows
   - Full 14-day daily overview with verdicts and recommendations

5. **Sends the report by email** (Gmail SMTP) with charts embedded inline.

---

## Project Structure

```
WindGuru_kayak/
├── main.py                    # Pipeline orchestrator
├── config/
│   └── config.yaml            # Spot, scoring weights, email settings
├── src/
│   ├── fetch_data.py          # Windguru data fetcher & parser
│   ├── fetch_waves.py         # Open-Meteo Marine API fetcher
│   ├── process_data.py        # Data normalization & merging
│   ├── scoring.py             # Fishing score algorithm
│   ├── visualize.py           # Matplotlib chart generation
│   ├── report.py              # Jinja2 HTML report builder
│   └── email_sender.py        # Gmail SMTP sender
├── templates/
│   └── report.html            # Jinja2 HTML template
├── data/
│   ├── raw/                   # Cached API responses (JSON/CSV)
│   └── processed/             # Normalized daily CSVs
├── reports/                   # Output HTML reports & PNG charts
└── .github/workflows/
    └── daily_report.yml       # GitHub Actions automation (3 AM UTC)
```

---

## Setup

### Requirements

- Python 3.11+
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled

### Installation

```bash
git clone https://github.com/your-username/WindGuru_kayak.git
cd WindGuru_kayak
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file (or set secrets in GitHub Actions):

```
GMAIL_USER=your.email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
```

---

## Usage

```bash
# Full run: fetch data, generate report, send email
python main.py

# Generate report without sending an email
python main.py --no-email

# Use cached data (no API calls)
python main.py --no-fetch
```

Reports are saved to `reports/YYYY-MM-DD.html` alongside the four PNG charts.

---

## Automation

The workflow runs automatically via GitHub Actions (`.github/workflows/daily_report.yml`):

- **Schedule**: every day at 3:00 AM UTC (4 AM CET / 5 AM CEST)
- **Manual trigger**: available via `workflow_dispatch`
- **Artifacts**: the `reports/` folder is uploaded and retained for 7 days

Required GitHub Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`.

---

## Configuration

Edit `config/config.yaml` to change the spot, forecast horizon, scoring weights, or verdict thresholds:

```yaml
spot:
  id: 48552
  name: "La Couarde sur Mer"
  lat: 46.19
  lon: -1.42

fishing:
  hours_start: 6        # Forecast filtered to 6 AM – 8 PM
  hours_end: 20
  forecast_days: 14

scoring:
  weights:
    wind: 0.25
    gust: 0.20
    wave_period: 0.20
    wave_height: 0.15
    rain: 0.10
    temperature: 0.10
  verdicts:
    excellent: 70
    favorable: 50
    moyen: 30
```

---

## Tech Stack

| Purpose | Library |
|---|---|
| HTTP requests | requests |
| HTML parsing | beautifulsoup4 + lxml |
| Data processing | pandas |
| Charts | matplotlib |
| HTML templating | Jinja2 |
| Config parsing | PyYAML |
| Timezone handling | pytz |
| Env variables | python-dotenv |
