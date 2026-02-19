"""
process_data.py — Normalisation et nettoyage des données Windguru brutes.

Transforme le JSON brut en DataFrame pandas avec des colonnes standardisées,
des unités SI cohérentes et les heures filtrées sur la fenêtre de pêche.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import pytz

logger = logging.getLogger(__name__)

KNOTS_TO_KMH = 1.852


def process_data(raw_data: dict, config: dict) -> pd.DataFrame:
    """
    Transforme les données brutes Windguru en DataFrame normalisé.

    Args:
        raw_data: Dictionnaire brut retourné par fetch_data.fetch_windguru_forecast()
        config:   Configuration chargée depuis config.yaml

    Returns:
        DataFrame avec colonnes standardisées, filtré sur les heures de pêche.
        Colonnes : datetime, wind_kmh, gust_kmh, wind_dir, wave_height_m,
                   wave_period_s, temp_c, rain_mmh
    """
    fishing_cfg = config["fishing"]
    tz = pytz.timezone(fishing_cfg["timezone"])
    hours_start = fishing_cfg["hours_start"]
    hours_end = fishing_cfg["hours_end"]

    # --- Reconstruction des timestamps absolus ---
    init_d_str = raw_data.get("init_d") or raw_data.get("initd") or raw_data.get("init_date")
    if not init_d_str:
        # Fallback : chercher dans d'autres clés connues
        for key in ("model_init_date", "date"):
            if key in raw_data:
                init_d_str = raw_data[key]
                break

    if not init_d_str:
        raise ValueError("Impossible de trouver la date d'initialisation dans les données Windguru.")

    # Windguru peut retourner "2025-02-18" ou "2025-02-18 00:00"
    init_date = datetime.strptime(init_d_str[:10], "%Y-%m-%d")
    init_date = pytz.utc.localize(init_date)

    hours_offsets = raw_data["hrs"]
    fcst = raw_data.get("fcst", {})

    # --- Construction du DataFrame brut ---
    records = []
    for i, h in enumerate(hours_offsets):
        dt_utc = init_date + timedelta(hours=int(h))
        dt_local = dt_utc.astimezone(tz)

        record = {"datetime": dt_local}

        # Vent moyen (knots → km/h)
        wspd_raw = _get_value(fcst, "WSPD", i)
        record["wind_kmh"] = round(wspd_raw * KNOTS_TO_KMH, 1) if wspd_raw is not None else None

        # Rafales (knots → km/h)
        gust_raw = _get_value(fcst, "GUST", i)
        record["gust_kmh"] = round(gust_raw * KNOTS_TO_KMH, 1) if gust_raw is not None else None

        # Direction vent (texte)
        record["wind_dir"] = _get_value(fcst, "WDIRN", i)

        # Hauteur vagues (mètres, déjà en mètres)
        record["wave_height_m"] = _get_value(fcst, "HTSGW", i)

        # Période vagues (secondes)
        record["wave_period_s"] = _get_value(fcst, "PERPW", i)

        # Température (°C)
        record["temp_c"] = _get_value(fcst, "TMP", i)

        # Précipitations (mm/h)
        record["rain_mmh"] = _get_value(fcst, "APCP1", i)

        records.append(record)

    df = pd.DataFrame(records)

    # --- Filtrage sur les heures de pêche ---
    df["hour"] = df["datetime"].apply(lambda dt: dt.hour)
    df = df[(df["hour"] >= hours_start) & (df["hour"] <= hours_end)].copy()
    df = df.drop(columns=["hour"])
    df = df.reset_index(drop=True)

    # --- Limiter aux forecast_days jours ---
    forecast_days = fishing_cfg.get("forecast_days", 14)
    cutoff = init_date.astimezone(tz) + timedelta(days=forecast_days)
    df = df[df["datetime"] <= cutoff].copy()

    logger.info(
        "Données normalisées : %d créneaux sur %d jours (vent, vagues, temp, pluie).",
        len(df),
        df["datetime"].apply(lambda dt: dt.date()).nunique() if len(df) > 0 else 0,
    )

    # Statistiques de couverture
    for col in ("wave_height_m", "wave_period_s"):
        missing = df[col].isna().sum()
        if missing > 0:
            logger.warning("Colonne '%s' : %d valeurs manquantes (NaN).", col, missing)

    return df


def save_processed_data(df: pd.DataFrame, output_dir: str, run_date=None) -> str:
    """
    Sauvegarde le DataFrame normalisé en CSV.

    Args:
        df:         DataFrame normalisé.
        output_dir: Dossier de destination (ex: "data/processed").
        run_date:   Date d'exécution (défaut : date du premier enregistrement).

    Returns:
        Chemin du fichier CSV créé.
    """
    from pathlib import Path
    from datetime import date

    if run_date is None:
        if len(df) > 0:
            run_date = df["datetime"].iloc[0].date()
        else:
            run_date = date.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / f"{run_date.isoformat()}.csv"
    df.to_csv(filepath, index=False)
    logger.info("Données normalisées sauvegardées : %s", filepath)
    return str(filepath)


def _get_value(fcst: dict, key: str, index: int):
    """Retourne fcst[key][index] ou None si absent/invalide."""
    values = fcst.get(key)
    if values is None:
        return None
    if index >= len(values):
        return None
    val = values[index]
    # Windguru utilise parfois 9999 ou -9999 pour les valeurs manquantes
    if isinstance(val, (int, float)) and abs(val) >= 9999:
        return None
    return val
