"""
scoring.py — Algorithme "Fishing Suitability Score" pour le kayak pêche (V3).

Calcule un score 0-100 par créneau horaire, puis un score journalier agrégé.
Le vent est en nœuds. La période des vagues interagit avec la hauteur via
un critère de raideur (H/T) dans le malus bloquant.
Un malus bloquant plafonne le score à 20 si les conditions sont rédhibitoires.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import pytz

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Direction du vent : flèche et texte lisible
# ---------------------------------------------------------------------------

_DIR_ARROWS = {
    "N":   "↓",  # vent vient du Nord → souffle vers le Sud
    "NNE": "↙", "NE": "↙", "ENE": "←",
    "E":   "←",
    "ESE": "↖", "SE": "↖", "SSE": "↑",
    "S":   "↑",
    "SSW": "↗", "SW": "↗", "WSW": "→",
    "W":   "→",
    "WNW": "↘", "NW": "↘", "NNW": "↓",
}

_DIR_FR = {
    "N": "Nord", "NNE": "Nord-Nord-Est", "NE": "Nord-Est", "ENE": "Est-Nord-Est",
    "E": "Est", "ESE": "Est-Sud-Est", "SE": "Sud-Est", "SSE": "Sud-Sud-Est",
    "S": "Sud", "SSW": "Sud-Sud-Ouest", "SW": "Sud-Ouest", "WSW": "Ouest-Sud-Ouest",
    "W": "Ouest", "WNW": "Ouest-Nord-Ouest", "NW": "Nord-Ouest", "NNW": "Nord-Nord-Ouest",
}


def wind_dir_arrow(direction: Optional[str]) -> str:
    """Retourne la flèche Unicode correspondant à la direction du vent."""
    if not direction:
        return "?"
    return _DIR_ARROWS.get(direction.upper(), direction)


def wind_dir_fr(direction: Optional[str]) -> str:
    """Retourne le nom français de la direction du vent."""
    if not direction:
        return "–"
    return _DIR_FR.get(direction.upper(), direction)


def _dominant_direction(series: pd.Series) -> Optional[str]:
    """Retourne la direction la plus fréquente d'une série (ignore None/NaN)."""
    clean = series.dropna()
    if clean.empty:
        return None
    return clean.mode().iloc[0]


def _verdict_css(verdict: str) -> str:
    return {
        "Excellent":   "excellent",
        "Favorable":   "favorable",
        "Moyen":       "moyen",
        "Déconseillé": "deconseille",
    }.get(verdict, "moyen")


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


def score_wind(wind_kts: Optional[float]) -> float:
    """Score vent moyen en nœuds. Idéal : < 15 kts. Rédhibitoire : > 30 kts."""
    if wind_kts is None:
        return 50.0
    return _piecewise_linear(wind_kts, [
        (0,  100),
        (10, 100),
        (15,  90),
        (20,  60),
        (25,  25),
        (30,   5),
        (35,   0),
    ])


def score_gust(gust_kts: Optional[float]) -> float:
    """Score rafales en nœuds. Idéal : < 17 kts. Rédhibitoire : > 25 kts."""
    if gust_kts is None:
        return 50.0
    return _piecewise_linear(gust_kts, [
        (0,  100),
        (12, 100),
        (17,  85),
        (20,  55),
        (25,  15),
        (30,   0),
    ])


def score_wave_height(wave_m: Optional[float]) -> float:
    """
    Score hauteur vagues en mètres.
    Courbe assouplie par rapport à V2 : la période complète désormais le scoring
    via le critère de raideur dans le malus bloquant.
    Idéal : < 0.5m. Limite absolue : > 2.0m.
    """
    if wave_m is None:
        return 50.0
    return _piecewise_linear(wave_m, [
        (0.0, 100),
        (0.5, 100),
        (0.8,  75),
        (1.2,  40),
        (1.5,  10),
        (2.0,   0),
    ])


def score_wave_period(period_s: Optional[float]) -> float:
    """
    Score période des vagues en secondes.
    Longue période = houle douce, facile à pagayer.
    Courte période = mer hachée, inconfortable et dangereuse.
    Idéal : >= 12s. Mauvais : < 6s.
    """
    if period_s is None:
        return 50.0
    return _piecewise_linear(period_s, [
        (3,    0),
        (6,   20),
        (8,   55),
        (10,  80),
        (12, 100),
        (20, 100),
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
# Malus bloquant : conditions rédhibitoires
# ---------------------------------------------------------------------------

def _blocking_malus(wind_kts: Optional[float], gust_kts: Optional[float],
                    wave_m: Optional[float], period_s: Optional[float] = None) -> bool:
    """
    Retourne True si les conditions sont rédhibitoires pour le kayak.
    Dans ce cas, le score sera plafonné à 20/100.

    Critères bloquants :
    - Vent moyen > 25 kts  (force 6 Beaufort)
    - Rafales > 30 kts
    - Vagues > 2.0m  (limite absolue)
    - Raideur H/T > 0.18  (mer hachée/cassante — ex: 1m/5s = 0.20 → bloqué)
    - Si période inconnue : hauteur > 1.4m (conservateur)

    La raideur H/T permet de différencier :
      1m / 5s  → steepness 0.20 → bloqué   (vague courte et cassante)
      1.5m / 14s → steepness 0.107 → libre  (houle longue gérable)
    """
    if wind_kts is not None and wind_kts > 25:
        return True
    if gust_kts is not None and gust_kts > 30:
        return True
    if wave_m is not None:
        if wave_m > 2.0:
            return True
        if period_s is not None and period_s > 0:
            steepness = wave_m / period_s
            if steepness > 0.18:
                return True
        else:
            # Période inconnue : critère hauteur conservateur
            if wave_m > 1.4:
                return True
    return False


# ---------------------------------------------------------------------------
# Score composite horaire
# ---------------------------------------------------------------------------

def compute_hourly_score(row: pd.Series, weights: dict) -> float:
    """
    Calcule le score composite pour une ligne horaire.

    Args:
        row:     Ligne du DataFrame (wind_kts, gust_kts, wave_height_m,
                 wave_period_s, rain_mmh, temp_c).
        weights: Dict de pondérations depuis config.yaml.

    Returns:
        Score entre 0 et 100 (plafonné à 20 si conditions bloquantes).
    """
    wind_kts = row.get("wind_kts")
    gust_kts = row.get("gust_kts")
    wave_m   = row.get("wave_height_m")
    period_s = row.get("wave_period_s")

    s_wind   = score_wind(wind_kts)
    s_gust   = score_gust(gust_kts)
    s_wave_h = score_wave_height(wave_m)
    s_wave_p = score_wave_period(period_s)
    s_rain   = score_rain(row.get("rain_mmh"))
    s_temp   = score_temp(row.get("temp_c"))

    total = (
        s_wind   * weights.get("wind", 0.25)
        + s_gust   * weights.get("gust", 0.20)
        + s_wave_h * weights.get("wave_height", 0.15)
        + s_wave_p * weights.get("wave_period", 0.20)
        + s_rain   * weights.get("rain", 0.10)
        + s_temp   * weights.get("temperature", 0.10)
    )

    # Malus bloquant : plafonner à 20 si conditions rédhibitoires
    if _blocking_malus(wind_kts, gust_kts, wave_m, period_s):
        total = min(total, 20.0)

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
        "vent fort":      df_day["wind_kts"].mean() if "wind_kts" in df_day else None,
        "rafales":        df_day["gust_kts"].mean() if "gust_kts" in df_day else None,
        "vagues":         df_day["wave_height_m"].mean() if "wave_height_m" in df_day else None,
        "houle courte":   df_day["wave_period_s"].mean() if "wave_period_s" in df_day else None,
        "pluie":          df_day["rain_mmh"].mean() if "rain_mmh" in df_day else None,
    }

    scores_by_factor = {
        "vent fort":    score_wind(candidates["vent fort"]),
        "rafales":      score_gust(candidates["rafales"]),
        "vagues":       score_wave_height(candidates["vagues"]),
        "houle courte": score_wave_period(candidates["houle courte"]),
        "pluie":        score_rain(candidates["pluie"]),
    }

    worst = min(
        scores_by_factor,
        key=lambda k: scores_by_factor[k] if scores_by_factor[k] is not None else 100,
    )
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

    df = df.copy()
    df["fishing_score"] = df.apply(
        lambda row: compute_hourly_score(row, weights), axis=1
    )

    daily_summaries = []
    df["date"] = df["datetime"].apply(lambda dt: dt.date())

    for day, df_day in df.groupby("date"):
        daily_score = round(df_day["fishing_score"].mean(), 1)
        verdict = get_verdict(daily_score, thresholds)
        best_window = _find_best_window(df_day)
        limiting = _main_limiting_factor(df_day, weights)
        dominant_dir = _dominant_direction(df_day["wind_dir"]) if "wind_dir" in df_day else None

        summary = {
            "date": day,
            "daily_score": daily_score,
            "verdict": verdict,
            "best_window": best_window,
            "limiting_factor": limiting,
            "avg_wind_kts": round(df_day["wind_kts"].mean(), 1) if df_day["wind_kts"].notna().any() else None,
            "max_gust_kts": round(df_day["gust_kts"].max(), 1) if df_day["gust_kts"].notna().any() else None,
            "wind_dir": dominant_dir,
            "wind_dir_arrow": wind_dir_arrow(dominant_dir),
            "wind_dir_fr": wind_dir_fr(dominant_dir),
            "avg_wave_m": round(df_day["wave_height_m"].mean(), 2) if df_day["wave_height_m"].notna().any() else None,
            "avg_wave_period_s": round(df_day["wave_period_s"].mean(), 1) if "wave_period_s" in df_day and df_day["wave_period_s"].notna().any() else None,
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


# ---------------------------------------------------------------------------
# Données horaires aujourd'hui
# ---------------------------------------------------------------------------

def get_today_hourly(df_scored: pd.DataFrame, config: dict) -> list[dict]:
    """
    Retourne la liste des scores horaires pour aujourd'hui.

    Args:
        df_scored: DataFrame scoré (avec colonne 'fishing_score').
        config:    Configuration chargée depuis config.yaml.

    Returns:
        Liste de dicts horaires triés par heure, avec score, conditions et verdict.
    """
    tz = pytz.timezone(config["fishing"]["timezone"])
    today = pd.Timestamp.now(tz=tz).date()
    thresholds = config["scoring"]["verdicts"]

    df_today = df_scored[df_scored["datetime"].apply(lambda dt: dt.date()) == today].copy()
    df_today = df_today.sort_values("datetime")

    rows = []
    for _, row in df_today.iterrows():
        score = float(row.get("fishing_score", 0))
        verdict = get_verdict(score, thresholds)

        wind = row.get("wind_kts")
        gust = row.get("gust_kts")
        wave = row.get("wave_height_m")
        period = row.get("wave_period_s")
        rain = row.get("rain_mmh")
        temp = row.get("temp_c")

        rows.append({
            "hour":         row["datetime"].hour,
            "time_str":     f"{row['datetime'].hour:02d}h",
            "score":        score,
            "verdict":      verdict,
            "css_class":    _verdict_css(verdict),
            "wind_kts":     round(wind, 1) if wind is not None and pd.notna(wind) else None,
            "gust_kts":     round(gust, 1) if gust is not None and pd.notna(gust) else None,
            "wave_height_m": round(wave, 2) if wave is not None and pd.notna(wave) else None,
            "wave_period_s": round(period, 1) if period is not None and pd.notna(period) else None,
            "rain_mmh":     round(rain, 1) if rain is not None and pd.notna(rain) else None,
            "temp_c":       round(temp, 1) if temp is not None and pd.notna(temp) else None,
        })

    return rows


# ---------------------------------------------------------------------------
# Créneaux de 3 heures pour les prochains jours
# ---------------------------------------------------------------------------

def compute_3h_windows(df_scored: pd.DataFrame, config: dict, n_days: int = 3) -> list[dict]:
    """
    Calcule les résumés par créneaux de 3h pour les n_days prochains jours.

    Args:
        df_scored: DataFrame scoré (avec colonne 'fishing_score').
        config:    Configuration chargée depuis config.yaml.
        n_days:    Nombre de jours à partir de demain (défaut : 3).

    Returns:
        Liste de dicts, un par créneau, avec date, slot horaire, score, conditions.
    """
    tz = pytz.timezone(config["fishing"]["timezone"])
    today = pd.Timestamp.now(tz=tz).date()
    thresholds = config["scoring"]["verdicts"]
    hours_start = config["fishing"].get("hours_start", 6)

    df = df_scored.copy()
    df["_date"] = df["datetime"].apply(lambda dt: dt.date())

    windows = []

    for i in range(1, n_days + 1):
        day = today + timedelta(days=i)
        df_day = df[df["_date"] == day].sort_values("datetime")

        if df_day.empty:
            continue

        # Grouper par tranches de 3h depuis hours_start
        df_day = df_day.copy()
        df_day["_slot"] = df_day["datetime"].apply(
            lambda dt: (dt.hour - hours_start) // 3
        )

        for _, slot_df in df_day.groupby("_slot"):
            start_h = slot_df.iloc[0]["datetime"].hour
            end_h   = slot_df.iloc[-1]["datetime"].hour

            score   = round(float(slot_df["fishing_score"].mean()), 1)
            verdict = get_verdict(score, thresholds)

            avg_wind   = round(slot_df["wind_kts"].mean(), 1) if slot_df["wind_kts"].notna().any() else None
            max_gust   = round(slot_df["gust_kts"].max(), 1)  if slot_df["gust_kts"].notna().any() else None
            avg_wave   = round(slot_df["wave_height_m"].mean(), 2) if slot_df["wave_height_m"].notna().any() else None
            avg_period = round(slot_df["wave_period_s"].mean(), 1) if "wave_period_s" in slot_df and slot_df["wave_period_s"].notna().any() else None
            max_rain   = round(slot_df["rain_mmh"].max(), 1)  if slot_df["rain_mmh"].notna().any() else None
            dominant_dir = _dominant_direction(slot_df["wind_dir"]) if "wind_dir" in slot_df else None

            windows.append({
                "date":          day,
                "slot":          f"{start_h:02d}h–{end_h:02d}h",
                "score":         score,
                "verdict":       verdict,
                "css_class":     _verdict_css(verdict),
                "avg_wind_kts":  avg_wind,
                "max_gust_kts":  max_gust,
                "wind_dir":      dominant_dir,
                "wind_dir_arrow": wind_dir_arrow(dominant_dir),
                "avg_wave_m":    avg_wave,
                "avg_period_s":  avg_period,
                "max_rain_mmh":  max_rain,
            })

    return windows
