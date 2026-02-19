"""
process_data.py — Normalisation et nettoyage des données Windguru brutes.

Transforme le dict parsé (clé "rows") en DataFrame pandas avec des colonnes
standardisées. Le vent est conservé en nœuds (unité native Windguru).
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz

logger = logging.getLogger(__name__)


def process_data(raw_data: dict, config: dict) -> pd.DataFrame:
    """
    Transforme les données brutes Windguru en DataFrame normalisé.

    Args:
        raw_data: Dict retourné par fetch_data.fetch_windguru_forecast()
                  (clés : init_d, tz_offset, columns, rows)
        config:   Configuration chargée depuis config.yaml.

    Returns:
        DataFrame avec colonnes standardisées, filtré sur les heures de pêche.
        Colonnes : datetime, wind_kts, gust_kts, wind_dir, wave_height_m,
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
            "wind_kts": round(wspd, 1) if wspd is not None else None,
            "gust_kts": round(gust, 1) if gust is not None else None,
            "wind_dir": row.get("WDIRN"),
            "wave_height_m": row.get("HTSGW"),
            "wave_period_s": row.get("PERPW"),
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
        "Données normalisées : %d créneaux sur %d jours (vent en kts, vagues, temp, pluie).",
        len(df),
        unique_days,
    )

    # Info vagues Windguru (souvent absentes — complétées par Open-Meteo Marine ensuite)
    for col in ("wave_height_m", "wave_period_s"):
        if col in df.columns:
            missing = df[col].isna().sum()
            if missing == len(df):
                logger.info(
                    "Colonne '%s' absente du modèle Windguru — sera alimentée par Open-Meteo.", col
                )
            elif missing > 0:
                logger.info("Colonne '%s' : %d valeurs manquantes (Windguru).", col, missing)

    return df


def merge_wave_data(df_wind: pd.DataFrame, df_waves: pd.DataFrame) -> pd.DataFrame:
    """
    Fusionne les données de vagues Open-Meteo avec le DataFrame vent Windguru.

    La fusion est faite sur l'heure exacte (truncate à l'heure).
    Les colonnes wave_height_m et wave_period_s issues de Windguru (toutes None)
    sont remplacées par les valeurs réelles d'Open-Meteo.
    Les colonnes supplémentaires (direction, houle) sont ajoutées.

    Args:
        df_wind:  DataFrame Windguru normalisé (depuis process_data()).
        df_waves: DataFrame Open-Meteo (depuis fetch_waves.fetch_wave_forecast()).

    Returns:
        DataFrame fusionné avec données de vagues réelles.
    """
    df = df_wind.copy()

    # Clé de fusion : datetime tronqué à l'heure (sans minutes ni secondes)
    # On utilise une colonne intermédiaire en UTC pour éviter les problèmes DST
    df["_merge_key"] = df["datetime"].apply(
        lambda dt: dt.replace(minute=0, second=0, microsecond=0).astimezone(pytz.utc)
    )

    df_w = df_waves.copy()
    df_w["_merge_key"] = df_w["datetime"].apply(
        lambda dt: dt.replace(minute=0, second=0, microsecond=0).astimezone(pytz.utc)
    )

    wave_cols = [
        "_merge_key", "wave_height_m", "wave_period_s",
        "wave_direction_deg", "wave_direction_cardinal",
        "swell_height_m", "swell_period_s",
    ]
    # Ne garder que les colonnes qui existent dans df_waves
    wave_cols = [c for c in wave_cols if c in df_w.columns]
    df_w_slim = df_w[wave_cols].drop_duplicates(subset=["_merge_key"])

    # Supprimer les colonnes vagues Windguru (toutes None) avant fusion
    drop_cols = [c for c in ("wave_height_m", "wave_period_s") if c in df.columns]
    df = df.drop(columns=drop_cols)

    df = df.merge(df_w_slim, on="_merge_key", how="left")
    df = df.drop(columns=["_merge_key"])

    matched = df["wave_height_m"].notna().sum()
    logger.info(
        "Fusion vagues Open-Meteo : %d/%d créneaux avec données réelles.",
        matched, len(df),
    )
    if matched == 0:
        logger.warning(
            "Aucun créneau vent n'a pu être associé à des données de vagues. "
            "Vérifiez que les fuseaux horaires sont cohérents."
        )

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
