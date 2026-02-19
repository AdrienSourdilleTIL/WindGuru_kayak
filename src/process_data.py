"""
process_data.py — Normalisation et nettoyage des données Windguru brutes.

Transforme le dict parsé (clé "rows") en DataFrame pandas avec des colonnes
standardisées, des unités cohérentes et les heures filtrées sur la fenêtre de pêche.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz

logger = logging.getLogger(__name__)

KNOTS_TO_KMH = 1.852


def process_data(raw_data: dict, config: dict) -> pd.DataFrame:
    """
    Transforme les données brutes Windguru en DataFrame normalisé.

    Args:
        raw_data: Dict retourné par fetch_data.fetch_windguru_forecast()
                  (clés : init_d, tz_offset, columns, rows)
        config:   Configuration chargée depuis config.yaml.

    Returns:
        DataFrame avec colonnes standardisées, filtré sur les heures de pêche.
        Colonnes : datetime, wind_kmh, gust_kmh, wind_dir, wave_height_m,
                   wave_period_s, temp_c, rain_mmh
    """
    fishing_cfg = config["fishing"]
    tz = pytz.timezone(fishing_cfg["timezone"])
    hours_start = fishing_cfg["hours_start"]
    hours_end = fishing_cfg["hours_end"]
    forecast_days = fishing_cfg.get("forecast_days", 14)

    rows = raw_data.get("rows", [])
    tz_offset = raw_data.get("tz_offset", 1)

    if not rows:
        raise ValueError("Aucune ligne de données dans les données brutes.")

    # Fuseau horaire fixe correspondant à l'offset affiché par Windguru
    # (ex: UTC+1 en hiver pour la France)
    fixed_tz = pytz.FixedOffset(tz_offset * 60)

    records = []
    for row in rows:
        # Reconstruire le datetime timezone-aware
        dt_local_str = row.get("datetime_local")
        if not dt_local_str:
            continue
        dt_naive = datetime.fromisoformat(dt_local_str)
        dt_fixed = fixed_tz.localize(dt_naive)
        dt_paris = dt_fixed.astimezone(tz)

        wspd = row.get("WSPD")
        gust = row.get("GUST")

        record = {
            "datetime": dt_paris,
            "wind_kmh": round(wspd * KNOTS_TO_KMH, 1) if wspd is not None else None,
            "gust_kmh": round(gust * KNOTS_TO_KMH, 1) if gust is not None else None,
            "wind_dir": row.get("WDIRN"),
            "wave_height_m": row.get("HTSGW"),   # None si absent du modèle
            "wave_period_s": row.get("PERPW"),   # None si absent du modèle
            "temp_c": row.get("TMP"),
            "rain_mmh": row.get("APCP1"),
        }
        records.append(record)

    df = pd.DataFrame(records)

    if df.empty:
        logger.error("DataFrame vide après normalisation.")
        return df

    # --- Filtrage sur les heures de pêche (heure locale) ---
    df["hour"] = df["datetime"].apply(lambda dt: dt.hour)
    df = df[(df["hour"] >= hours_start) & (df["hour"] <= hours_end)].copy()
    df = df.drop(columns=["hour"])
    df = df.reset_index(drop=True)

    # --- Limiter aux forecast_days jours ---
    if len(df) > 0:
        first_dt = df["datetime"].iloc[0]
        cutoff = first_dt + timedelta(days=forecast_days)
        df = df[df["datetime"] <= cutoff].copy()
        df = df.reset_index(drop=True)

    unique_days = df["datetime"].apply(lambda dt: dt.date()).nunique() if len(df) > 0 else 0
    logger.info(
        "Données normalisées : %d créneaux sur %d jours (vent, vagues, temp, pluie).",
        len(df),
        unique_days,
    )

    # Avertissements sur les données manquantes
    for col in ("wave_height_m", "wave_period_s"):
        if col in df.columns:
            missing = df[col].isna().sum()
            if missing == len(df):
                logger.warning("Colonne '%s' : données non disponibles pour ce spot/modèle.", col)
            elif missing > 0:
                logger.warning("Colonne '%s' : %d valeurs manquantes.", col, missing)

    return df


def save_processed_data(df: pd.DataFrame, output_dir: str, run_date=None) -> str:
    """Sauvegarde le DataFrame normalisé en CSV."""
    from datetime import date as date_type

    if run_date is None:
        if len(df) > 0:
            run_date = df["datetime"].iloc[0].date()
        else:
            run_date = date_type.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / f"{run_date.isoformat()}.csv"
    df.to_csv(filepath, index=False)
    logger.info("Données normalisées sauvegardées : %s", filepath)
    return str(filepath)
