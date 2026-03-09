"""
history.py — Suivi historique des scores journaliers.

Après chaque exécution, les scores du jour sont ajoutés à data/history.csv.
Ce fichier croît d'un enregistrement par jour et permet de :
- Afficher les "meilleures sorties récentes" dans le rapport.
- Comparer les scores actuels à une moyenne historique.
- Identifier la meilleure journée des 7 prochains jours vs historique.
"""

import csv
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("data/history.csv")
HISTORY_FIELDS = ["date", "score", "verdict", "avg_wind_kts", "max_gust_kts",
                  "avg_wave_m", "avg_wave_period_s", "max_rain_mmh", "avg_temp_c",
                  "best_window", "limiting_factor"]


def append_to_history(daily_summaries: list[dict], history_file: Path = HISTORY_FILE) -> None:
    """
    Ajoute les résumés journaliers qui n'existent pas encore dans l'historique.

    Idempotent : si une date est déjà présente, elle n'est pas dupliquée.

    Args:
        daily_summaries: Liste de résumés journaliers (sortie de compute_scores).
        history_file:    Chemin vers le fichier CSV d'historique.
    """
    history_file.parent.mkdir(parents=True, exist_ok=True)

    # Charger les dates déjà présentes
    existing_dates: set[str] = set()
    if history_file.exists():
        with open(history_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row["date"])

    new_rows = []
    for s in daily_summaries:
        date_str = s["date"].isoformat()
        if date_str not in existing_dates:
            new_rows.append({
                "date":             date_str,
                "score":            s.get("daily_score", ""),
                "verdict":          s.get("verdict", ""),
                "avg_wind_kts":     s.get("avg_wind_kts", ""),
                "max_gust_kts":     s.get("max_gust_kts", ""),
                "avg_wave_m":       s.get("avg_wave_m", ""),
                "avg_wave_period_s": s.get("avg_wave_period_s", ""),
                "max_rain_mmh":     s.get("max_rain_mmh", ""),
                "avg_temp_c":       s.get("avg_temp_c", ""),
                "best_window":      s.get("best_window", ""),
                "limiting_factor":  s.get("limiting_factor", ""),
            })

    if not new_rows:
        logger.info("Historique : aucune nouvelle date à ajouter.")
        return

    write_header = not history_file.exists() or history_file.stat().st_size == 0
    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    logger.info("Historique : %d nouvelle(s) date(s) ajoutée(s) dans %s.", len(new_rows), history_file)


def load_history(history_file: Path = HISTORY_FILE) -> list[dict]:
    """
    Charge l'historique complet depuis le CSV.

    Returns:
        Liste de dicts triés par date, avec "date" comme objet date Python
        et "score" comme float.
    """
    if not history_file.exists():
        return []

    records = []
    with open(history_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                records.append({
                    "date":  date.fromisoformat(row["date"]),
                    "score": float(row["score"]) if row["score"] else None,
                    "verdict": row.get("verdict", ""),
                })
            except (ValueError, KeyError):
                continue

    records.sort(key=lambda r: r["date"])
    return records


def build_history_context(history: list[dict], forecast_summaries: list[dict]) -> dict:
    """
    Construit le contexte historique pour le template :
    - best_day_next7 : meilleure journée parmi les 7 prochains jours (depuis forecast)
    - recent_good_days : les 3 meilleures journées passées (score ≥ 50) des 90 derniers jours
    - history_avg_score : score moyen sur les 90 derniers jours disponibles

    Args:
        history:            Liste de dicts historiques (depuis load_history).
        forecast_summaries: Liste de résumés journaliers de la prévision actuelle.

    Returns:
        Dict injecté dans le contexte Jinja2.
    """
    today = date.today()

    # Meilleure journée dans les 7 prochains jours (depuis la prévision)
    next7 = [s for s in forecast_summaries if today < s["date"] <= today + timedelta(days=7)]
    best_next7 = max(next7, key=lambda s: s["daily_score"], default=None)

    # Historique récent (90 jours)
    cutoff = today - timedelta(days=90)
    recent = [h for h in history if cutoff <= h["date"] < today and h["score"] is not None]

    recent_good = sorted(
        [h for h in recent if h["score"] is not None and h["score"] >= 50],
        key=lambda h: h["score"],
        reverse=True,
    )[:3]

    scores = [h["score"] for h in recent if h["score"] is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    return {
        "best_day_next7":    best_next7,
        "recent_good_days":  recent_good,
        "history_avg_score": avg_score,
        "history_days_count": len(recent),
    }
