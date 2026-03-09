"""
fetch_tides.py — Récupération des coefficients et horaires de marées via WorldTides API.

API gratuite (10 000 req/mois) : https://www.worldtides.info/
Nécessite une clé API stockée dans la variable d'environnement WORLDTIDES_API_KEY.

Pour La Couarde sur Mer, Île de Ré : station de référence = La Pallice / Saint-Martin.

Le coefficient de marée (0–120 en système français) est calculé à partir de l'amplitude
des pleines mers : coeff ≈ (amplitude / amplitude_vive_eau_max) × 120.
Ici on l'approche via le rapport entre le marnage observé et un marnage de référence de 4.3 m
(vive-eau équinoxiale à La Pallice).
"""

import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

WORLDTIDES_URL = "https://www.worldtides.info/api/v3"
# Marnage de vive-eau équinoxiale à La Pallice (référence pour coeff 120)
_REF_MARNAGE_M = 4.3


class TideFetchError(Exception):
    """Levée quand la récupération des données de marées échoue."""


def _coeff_from_amplitude(amplitude_m: float) -> int:
    """
    Convertit une amplitude (hauteur PM - hauteur BM) en coefficient français (0–120).
    Référence : 4.3 m → coeff 120 (vive-eau équinoxiale La Pallice).
    """
    coeff = round((amplitude_m / _REF_MARNAGE_M) * 120)
    return max(0, min(120, coeff))


def fetch_tides(lat: float, lon: float, api_key: str, forecast_days: int = 14) -> list[dict]:
    """
    Récupère les horaires de marées et calcule les coefficients journaliers.

    Args:
        lat:          Latitude du spot.
        lon:          Longitude du spot.
        api_key:      Clé WorldTides API (variable WORLDTIDES_API_KEY).
        forecast_days: Nombre de jours (max 14 sur le tier gratuit).

    Returns:
        Liste de dicts, un par jour :
        {
            "date":        date,
            "coeff":       int (0–120),
            "coeff_label": str ("morte-eau" / "moyenne" / "vive-eau"),
            "tides":       [{"time": str "HHhMM", "height_m": float, "type": "PM"|"BM"}, ...]
        }

    Raises:
        TideFetchError: Si l'API échoue ou la clé est manquante.
    """
    if not api_key:
        raise TideFetchError(
            "Clé WorldTides manquante. Définissez WORLDTIDES_API_KEY dans les variables "
            "d'environnement ou dans le fichier .env."
        )

    params = {
        "heights": "",
        "extremes": "",
        "lat": lat,
        "lon": lon,
        "key": api_key,
        "days": min(forecast_days, 14),
        "tz": "Europe/Paris",
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            logger.info("Tentative %d/3 — WorldTides API (%.2f, %.2f)", attempt, lat, lon)
            r = requests.get(WORLDTIDES_URL, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as e:
            last_error = e
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("Erreur WorldTides (tentative %d/3) : %s. Retry dans %ds.", attempt, e, wait)
                time.sleep(wait)
    else:
        raise TideFetchError(f"Échec WorldTides après 3 tentatives : {last_error}")

    if "status" in data and data["status"] != 200:
        raise TideFetchError(f"Erreur WorldTides API : {data.get('error', data)}")

    extremes = data.get("extremes", [])
    if not extremes:
        raise TideFetchError("Réponse WorldTides vide : pas d'extrêmes de marée.")

    tz = ZoneInfo("Europe/Paris")
    by_day: dict[date, list[dict]] = {}

    for ex in extremes:
        dt = datetime.fromtimestamp(ex["dt"], tz=tz)
        day = dt.date()
        tide_type = "PM" if ex["type"] == "High" else "BM"
        entry = {
            "time":     dt.strftime("%Hh%M"),
            "height_m": round(ex["height"], 2),
            "type":     tide_type,
        }
        by_day.setdefault(day, []).append(entry)

    result = []
    for day in sorted(by_day.keys()):
        day_tides = by_day[day]
        highs = [t["height_m"] for t in day_tides if t["type"] == "PM"]
        lows  = [t["height_m"] for t in day_tides if t["type"] == "BM"]

        if highs and lows:
            amplitude = max(highs) - min(lows)
            coeff = _coeff_from_amplitude(amplitude)
        else:
            coeff = 70  # valeur neutre si données incomplètes

        if coeff >= 95:
            label = "vive-eau"
        elif coeff >= 70:
            label = "moyenne"
        else:
            label = "morte-eau"

        result.append({
            "date":        day,
            "coeff":       coeff,
            "coeff_label": label,
            "tides":       day_tides,
        })

    logger.info("Marées récupérées : %d jours, coefficients : %s",
                len(result), [f"{r['date']} → {r['coeff']}" for r in result[:3]])
    return result


def load_tide_data(raw_dir: str, run_date: date | None = None) -> list[dict] | None:
    """
    Charge les données de marées depuis data/raw/tides_YYYY-MM-DD.json.
    Retourne None si le fichier n'existe pas.
    """
    import json

    if run_date is None:
        run_date = date.today()

    filepath = Path(raw_dir) / f"tides_{run_date.isoformat()}.json"
    if not filepath.exists():
        return None

    with open(filepath, encoding="utf-8") as f:
        raw = json.load(f)

    # Désérialiser les dates
    for entry in raw:
        entry["date"] = date.fromisoformat(entry["date"])
    logger.info("Données marées chargées depuis cache : %s", filepath)
    return raw


def save_tide_data(tides: list[dict], output_dir: str, run_date: date | None = None) -> Path:
    """Sauvegarde les données de marées en JSON dans data/raw/tides_YYYY-MM-DD.json."""
    import json

    if run_date is None:
        run_date = date.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / f"tides_{run_date.isoformat()}.json"

    serialisable = [{**t, "date": t["date"].isoformat()} for t in tides]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serialisable, f, ensure_ascii=False, indent=2)

    logger.info("Données marées sauvegardées : %s", filepath)
    return filepath
