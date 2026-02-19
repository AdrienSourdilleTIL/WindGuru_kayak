"""
scoring.py — Algorithme "Fishing Suitability Score" pour le kayak pêche.

Calcule un score 0-100 par créneau horaire, puis un score journalier agrégé.
Les seuils et pondérations sont configurables via config.yaml.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fonctions de scoring unitaires (piecewise linear, retournent 0–100)
# ---------------------------------------------------------------------------

def _piecewise_linear(value: float, breakpoints: list[tuple[float, float]]) -> float:
    """
    Interpolation linéaire par morceaux entre des points de contrôle (x, y).

    Args:
        value:       Valeur d'entrée.
        breakpoints: Liste de tuples (x, score) triés par x croissant.

    Returns:
        Score interpolé entre 0 et 100.
    """
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]
    if value >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= value <= x1:
            t = (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)

    return breakpoints[-1][1]


def score_wind(wind_kmh: Optional[float]) -> float:
    """Score vent moyen en km/h. Idéal : < 14 km/h. Rédhibitoire : > 40 km/h."""
    if wind_kmh is None:
        return 50.0
    return _piecewise_linear(wind_kmh, [
        (0,  100),
        (14, 100),
        (22,  80),
        (30,  40),
        (40,  10),
        (50,   0),
    ])


def score_gust(gust_kmh: Optional[float]) -> float:
    """Score rafales en km/h. Idéal : < 20 km/h. Rédhibitoire : > 55 km/h."""
    if gust_kmh is None:
        return 50.0
    return _piecewise_linear(gust_kmh, [
        (0,  100),
        (20, 100),
        (30,  70),
        (40,  30),
        (55,   5),
        (65,   0),
    ])


def score_wave(wave_m: Optional[float]) -> float:
    """Score hauteur vagues en mètres. Idéal : < 0.5m. Rédhibitoire : > 1.2m."""
    if wave_m is None:
        return 50.0  # Neutre si données manquantes
    return _piecewise_linear(wave_m, [
        (0.0, 100),
        (0.5, 100),
        (0.8,  70),
        (1.0,  40),
        (1.2,  10),
        (1.5,   0),
    ])


def score_rain(rain_mmh: Optional[float]) -> float:
    """Score précipitations en mm/h. Idéal : 0. Rédhibitoire : > 6 mm/h."""
    if rain_mmh is None:
        return 80.0
    return _piecewise_linear(rain_mmh, [
        (0,   100),
        (1,    85),
        (3,    50),
        (6,    15),
        (10,    0),
    ])


def score_temp(temp_c: Optional[float]) -> float:
    """Score température en °C. Zone idéale : 15–25°C."""
    if temp_c is None:
        return 70.0
    return _piecewise_linear(temp_c, [
        (-5,   0),
        (5,   30),
        (10,  60),
        (15,  90),
        (20, 100),
        (25, 100),
        (30,  70),
        (35,  40),
    ])


# ---------------------------------------------------------------------------
# Score composite horaire
# ---------------------------------------------------------------------------

def compute_hourly_score(row: pd.Series, weights: dict) -> float:
    """
    Calcule le score composite pour une ligne horaire.

    Args:
        row:     Ligne du DataFrame (wind_kmh, gust_kmh, wave_height_m, rain_mmh, temp_c).
        weights: Dict {'wind': 0.30, 'gust': 0.20, 'wave': 0.30, 'rain': 0.10, 'temperature': 0.10}

    Returns:
        Score entre 0 et 100.
    """
    s_wind  = score_wind(row.get("wind_kmh"))
    s_gust  = score_gust(row.get("gust_kmh"))
    s_wave  = score_wave(row.get("wave_height_m"))
    s_rain  = score_rain(row.get("rain_mmh"))
    s_temp  = score_temp(row.get("temp_c"))

    total = (
        s_wind  * weights.get("wind", 0.30)
        + s_gust  * weights.get("gust", 0.20)
        + s_wave  * weights.get("wave", 0.30)
        + s_rain  * weights.get("rain", 0.10)
        + s_temp  * weights.get("temperature", 0.10)
    )
    return round(total, 1)


# ---------------------------------------------------------------------------
# Score journalier et verdict
# ---------------------------------------------------------------------------

def get_verdict(score: float, thresholds: dict) -> str:
    """
    Retourne le verdict textuel en fonction du score et des seuils configurés.

    Args:
        score:      Score journalier 0-100.
        thresholds: Dict {'excellent': 70, 'favorable': 50, 'moyen': 30}

    Returns:
        Chaîne descriptive du verdict.
    """
    if score >= thresholds.get("excellent", 70):
        return "Excellent"
    if score >= thresholds.get("favorable", 50):
        return "Favorable"
    if score >= thresholds.get("moyen", 30):
        return "Moyen"
    return "Déconseillé"


def _find_best_window(df_day: pd.DataFrame, score_col: str = "fishing_score") -> str:
    """Trouve le créneau de 3 heures consécutives avec le meilleur score moyen."""
    if len(df_day) < 2:
        return "–"

    best_score = -1
    best_label = "–"

    for i in range(len(df_day) - 1):
        window = df_day.iloc[i : i + 3]
        avg = window[score_col].mean()
        if avg > best_score:
            best_score = avg
            start_h = window.iloc[0]["datetime"].hour
            end_h = window.iloc[-1]["datetime"].hour
            best_label = f"{start_h:02d}h–{end_h:02d}h"

    return best_label


def _main_limiting_factor(df_day: pd.DataFrame, weights: dict) -> str:
    """Identifie le principal facteur limitant du jour."""
    candidates = {
        "vent fort": df_day["wind_kmh"].mean() if "wind_kmh" in df_day else None,
        "rafales": df_day["gust_kmh"].mean() if "gust_kmh" in df_day else None,
        "vagues": df_day["wave_height_m"].mean() if "wave_height_m" in df_day else None,
        "pluie": df_day["rain_mmh"].mean() if "rain_mmh" in df_day else None,
    }

    scores_by_factor = {
        "vent fort": score_wind(candidates["vent fort"]),
        "rafales": score_gust(candidates["rafales"]),
        "vagues": score_wave(candidates["vagues"]),
        "pluie": score_rain(candidates["pluie"]),
    }

    worst = min(scores_by_factor, key=lambda k: scores_by_factor[k] if scores_by_factor[k] is not None else 100)
    return worst


# ---------------------------------------------------------------------------
# Fonction principale : scoring complet du DataFrame
# ---------------------------------------------------------------------------

def compute_scores(df: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, list[dict]]:
    """
    Calcule les scores horaires et le résumé journalier.

    Args:
        df:     DataFrame normalisé (depuis process_data.process_data()).
        config: Configuration chargée depuis config.yaml.

    Returns:
        Tuple (df_scored, daily_summaries) :
        - df_scored : DataFrame avec colonne 'fishing_score' ajoutée.
        - daily_summaries : liste de dicts résumant chaque jour.
    """
    weights = config["scoring"]["weights"]
    thresholds = config["scoring"]["verdicts"]

    # Score horaire
    df = df.copy()
    df["fishing_score"] = df.apply(
        lambda row: compute_hourly_score(row, weights), axis=1
    )

    # Résumé journalier
    daily_summaries = []
    df["date"] = df["datetime"].apply(lambda dt: dt.date())

    for day, df_day in df.groupby("date"):
        daily_score = round(df_day["fishing_score"].mean(), 1)
        verdict = get_verdict(daily_score, thresholds)
        best_window = _find_best_window(df_day)
        limiting = _main_limiting_factor(df_day, weights)

        summary = {
            "date": day,
            "daily_score": daily_score,
            "verdict": verdict,
            "best_window": best_window,
            "limiting_factor": limiting,
            "avg_wind_kmh": round(df_day["wind_kmh"].mean(), 1) if df_day["wind_kmh"].notna().any() else None,
            "max_gust_kmh": round(df_day["gust_kmh"].max(), 1) if df_day["gust_kmh"].notna().any() else None,
            "avg_wave_m": round(df_day["wave_height_m"].mean(), 2) if df_day["wave_height_m"].notna().any() else None,
            "max_rain_mmh": round(df_day["rain_mmh"].max(), 1) if df_day["rain_mmh"].notna().any() else None,
            "avg_temp_c": round(df_day["temp_c"].mean(), 1) if df_day["temp_c"].notna().any() else None,
        }
        daily_summaries.append(summary)

    daily_summaries.sort(key=lambda x: x["date"])

    logger.info(
        "Scoring terminé : %d jours. Scores : %s",
        len(daily_summaries),
        [f"{s['date']} → {s['daily_score']}" for s in daily_summaries],
    )

    return df.drop(columns=["date"]), daily_summaries
