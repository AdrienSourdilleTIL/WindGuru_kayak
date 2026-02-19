"""
fetch_waves.py — Récupération des données de vagues via Open-Meteo Marine API.

API gratuite, sans authentification, résolution horaire, jusqu'à 16 jours de prévision.
Fournit hauteur significative, période dominante, direction, et composante de houle.

Doc : https://open-meteo.com/en/docs/marine-weather-api
"""

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytz
import requests

logger = logging.getLogger(__name__)

MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"

# Conversion degrés → direction cardinale (vagues venant DE cette direction)
_DEGREE_TO_CARDINAL = [
    (22.5,  "N"),  (67.5,  "NE"), (112.5, "E"),  (157.5, "SE"),
    (202.5, "S"),  (247.5, "SW"), (292.5, "W"),  (337.5, "NW"), (360.0, "N"),
]


class WaveFetchError(Exception):
    """Levée quand la récupération des données de vagues échoue."""


def degrees_to_cardinal(deg: float | None) -> str | None:
    """Convertit un angle en degrés en direction cardinale (ex: 270 → 'W')."""
    if deg is None:
        return None
    deg = deg % 360
    for threshold, card in _DEGREE_TO_CARDINAL:
        if deg < threshold:
            return card
    return "N"


def fetch_wave_forecast(lat: float, lon: float, forecast_days: int = 14) -> pd.DataFrame:
    """
    Récupère les prévisions de vagues depuis Open-Meteo Marine API.

    Variables récupérées :
    - wave_height     : hauteur significative totale (m) — vent + houle combinés
    - wave_period     : période dominante (s) — période la plus énergétique
    - wave_direction  : direction d'où viennent les vagues (degrés, 0=N)
    - swell_wave_height  : hauteur de la composante houle (m)
    - swell_wave_period  : période de la houle (s) — souvent > période totale

    Args:
        lat:          Latitude du spot.
        lon:          Longitude du spot.
        forecast_days: Nombre de jours (max 16 ; Open-Meteo gratuit couvre ~7 jours
                       avec bonne précision, jusqu'à 16 jours en prévision étendue).

    Returns:
        DataFrame horaire (timezone Europe/Paris) avec colonnes :
        datetime, wave_height_m, wave_period_s, wave_direction_deg,
        wave_direction_cardinal, swell_height_m, swell_period_s.

    Raises:
        WaveFetchError: Si l'API est inaccessible ou retourne une erreur.
    """
    forecast_days = min(max(forecast_days, 1), 16)

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height",
            "wave_period",
            "wave_direction",
            "swell_wave_height",
            "swell_wave_period",
        ]),
        "timezone": "Europe/Paris",
        "forecast_days": forecast_days,
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            logger.info(
                "Tentative %d/3 — Open-Meteo Marine (%.2f, %.2f, %d jours)",
                attempt, lat, lon, forecast_days,
            )
            r = requests.get(MARINE_API_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as e:
            last_error = e
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("Erreur (tentative %d/3) : %s. Retry dans %ds.", attempt, e, wait)
                time.sleep(wait)
    else:
        raise WaveFetchError(
            f"Échec après 3 tentatives Open-Meteo Marine. Dernière erreur : {last_error}"
        )

    hourly = data.get("hourly", {})
    if not hourly or "time" not in hourly:
        raise WaveFetchError("Réponse Open-Meteo invalide : pas de clé 'hourly'.")

    times = hourly["time"]
    n = len(times)

    def _col(key: str) -> list:
        return hourly.get(key, [None] * n)

    tz = pytz.timezone("Europe/Paris")
    records = []
    for i, time_str in enumerate(times):
        # Les timestamps retournés sont déjà en heure locale (Europe/Paris)
        dt_naive = datetime.fromisoformat(time_str)
        try:
            dt_aware = tz.localize(dt_naive, is_dst=None)
        except pytz.exceptions.AmbiguousTimeError:
            dt_aware = tz.localize(dt_naive, is_dst=False)
        except pytz.exceptions.NonExistentTimeError:
            dt_aware = tz.localize(dt_naive, is_dst=True)

        wave_dir_deg = _col("wave_direction")[i]
        records.append({
            "datetime": dt_aware,
            "wave_height_m": _col("wave_height")[i],
            "wave_period_s": _col("wave_period")[i],
            "wave_direction_deg": wave_dir_deg,
            "wave_direction_cardinal": degrees_to_cardinal(wave_dir_deg),
            "swell_height_m": _col("swell_wave_height")[i],
            "swell_period_s": _col("swell_wave_period")[i],
        })

    df = pd.DataFrame(records)

    # Log résumé
    non_null = df["wave_height_m"].notna().sum()
    logger.info(
        "Données vagues Open-Meteo : %d créneaux horaires, %d avec wave_height.",
        len(df), non_null,
    )
    if non_null > 0:
        logger.info(
            "Vagues : hauteur moy=%.2fm, période moy=%.1fs",
            df["wave_height_m"].mean(),
            df["wave_period_s"].mean() if df["wave_period_s"].notna().any() else 0,
        )

    return df


def save_wave_data(df: pd.DataFrame, output_dir: str, run_date: date | None = None) -> Path:
    """Sauvegarde les données de vagues en CSV dans data/raw/waves_YYYY-MM-DD.csv."""
    if run_date is None:
        run_date = date.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / f"waves_{run_date.isoformat()}.csv"
    df.to_csv(filepath, index=False)
    logger.info("Données vagues sauvegardées : %s", filepath)
    return filepath


def load_wave_data(raw_dir: str, run_date: date | None = None) -> pd.DataFrame:
    """Charge les données de vagues depuis data/raw/waves_YYYY-MM-DD.csv."""
    if run_date is None:
        run_date = date.today()

    filepath = Path(raw_dir) / f"waves_{run_date.isoformat()}.csv"
    if not filepath.exists():
        raise FileNotFoundError(
            f"Données vagues introuvables pour {run_date.isoformat()} dans {raw_dir}"
        )

    df = pd.read_csv(filepath, parse_dates=["datetime"])

    # Restaurer la timezone après lecture CSV
    tz = pytz.timezone("Europe/Paris")
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    else:
        df["datetime"] = df["datetime"].dt.tz_convert(tz)

    logger.info("Données vagues chargées : %s (%d créneaux)", filepath, len(df))
    return df
