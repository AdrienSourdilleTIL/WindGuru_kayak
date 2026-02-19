"""
fetch_data.py — Récupération des prévisions Windguru via micro.windguru.cz

L'endpoint retourne un tableau texte brut (<pre>), pas du JSON.
Ce module parse ce format et retourne un dict structuré.
"""

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

WINDGURU_WIDGET_URL = "http://micro.windguru.cz/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.windguru.cz/",
}


class WindguruFetchError(Exception):
    """Levée quand la récupération des données Windguru échoue définitivement."""


def _parse_value(s: str):
    """Convertit une valeur texte : '-' → None, nombre → float, texte → str."""
    if s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return s  # ex: "WNW", "NW"


def _parse_pre_response(html: str) -> dict:
    """
    Parse le contenu <pre> plain-text retourné par micro.windguru.cz.

    Format attendu :
        Windguru forecast

        France - La Couarde,  lat: 46.19, lon: -1.42, alt: 1, SST: 11 C

        GFS 13 km (init: 2026-02-19 06 UTC)

                Date    WSPD    GUST   WDIRN     TMP   APCP1
             (UTC+1)   knots   knots    dir.       C   mm/1h

         Thu 19. 07h      34      43     WNW      11       -
         Thu 19. 08h      34      43       W      11       0
         ...
    """
    # Extraire le contenu de la balise <pre>
    pre_match = re.search(r"<pre>(.*?)</pre>", html, re.DOTALL)
    if not pre_match:
        raise WindguruFetchError("Pas de balise <pre> dans la réponse Windguru.")

    pre_text = pre_match.group(1)
    lines = pre_text.split("\n")

    # --- Extraire la date d'initialisation ---
    init_match = re.search(r"init:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2})\s*UTC", pre_text)
    if not init_match:
        raise WindguruFetchError("Impossible de trouver la date d'initialisation du modèle.")
    init_date = datetime.strptime(init_match.group(1), "%Y-%m-%d").date()

    # --- Extraire le décalage UTC ---
    tz_match = re.search(r"\(UTC([+-]\d+)\)", pre_text)
    tz_offset = int(tz_match.group(1)) if tz_match else 1

    # --- Extraire les colonnes depuis l'en-tête ---
    columns = []
    header_found = False
    for line in lines:
        if "Date" in line and "WSPD" in line:
            columns = [c for c in line.split() if c != "Date"]
            header_found = True
            break

    if not header_found or not columns:
        raise WindguruFetchError("Impossible de trouver l'en-tête des colonnes.")

    logger.info("Colonnes disponibles : %s", columns)
    for wave_var in ("HTSGW", "PERPW"):
        if wave_var not in columns:
            logger.warning(
                "Variable %s absente du modèle pour ce spot — score vagues sera neutre.",
                wave_var,
            )

    # --- Parser les lignes de données ---
    # Format : " Thu 19. 07h      34      43     WNW      11       -"
    #      ou  "  Sun 1. 07h      12      21..."
    row_pattern = re.compile(r"^\s+\w{3}\s+(\d{1,2})\.\s+(\d{2})h\s+(.+)$")

    rows = []
    current_month = init_date.month
    current_year = init_date.year
    last_day = 0  # démarre à 0 pour détecter le premier jour correctement

    for line in lines:
        m = row_pattern.match(line)
        if not m:
            continue

        day_num = int(m.group(1))
        hour = int(m.group(2))
        values_raw = m.group(3).split()

        # Détection des transitions de mois : le numéro de jour diminue
        if last_day > 0 and day_num < last_day:
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        last_day = day_num

        # Construire le datetime local naïf
        try:
            dt_local = datetime(current_year, current_month, day_num, hour, 0, 0)
        except ValueError:
            logger.warning("Date invalide ignorée : %d/%d/%d %dh", day_num, current_month, current_year, hour)
            continue

        # Parser les valeurs et associer aux colonnes
        row = {
            "datetime_local": dt_local.isoformat(),
            "tz_offset": tz_offset,
        }
        for col, val_str in zip(columns, values_raw):
            row[col] = _parse_value(val_str)

        # S'assurer que les colonnes manquantes sont présentes avec None
        for col in ("WSPD", "GUST", "WDIRN", "HTSGW", "PERPW", "TMP", "APCP1"):
            if col not in row:
                row[col] = None

        rows.append(row)

    if not rows:
        raise WindguruFetchError("Aucune ligne de données trouvée dans la réponse Windguru.")

    unique_days = len({r["datetime_local"][:10] for r in rows})
    logger.info("Données Windguru parsées : %d créneaux sur %d jours.", len(rows), unique_days)

    return {
        "init_d": init_date.isoformat(),
        "tz_offset": tz_offset,
        "columns": columns,
        "rows": rows,
    }


def fetch_windguru_forecast(spot_id: int, model: str, variables: list) -> dict:
    """
    Récupère et parse les prévisions Windguru pour un spot donné.

    Args:
        spot_id:   Identifiant numérique du spot (ex: 48552).
        model:     Modèle météo (ex: "gfs").
        variables: Variables demandées (ex: ["WSPD", "GUST", "TMP"]).

    Returns:
        dict avec clés : init_d, tz_offset, columns, rows.

    Raises:
        WindguruFetchError: Si la récupération échoue après 3 tentatives.
    """
    params = {
        "s": spot_id,
        "m": model,
        "v": ",".join(variables),
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            logger.info("Tentative %d/3 — Windguru spot %d, modèle %s", attempt, spot_id, model)
            response = requests.get(
                WINDGURU_WIDGET_URL,
                params=params,
                headers=HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            return _parse_pre_response(response.text)

        except (requests.RequestException, WindguruFetchError) as e:
            last_error = e
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("Erreur (tentative %d/3) : %s. Retry dans %ds.", attempt, e, wait)
                time.sleep(wait)

    raise WindguruFetchError(
        f"Échec après 3 tentatives pour le spot {spot_id}. Dernière erreur : {last_error}"
    )


def save_raw_data(data: dict, output_dir: str, run_date: date | None = None) -> Path:
    """Sauvegarde le dict parsé en JSON dans data/raw/YYYY-MM-DD.json."""
    if run_date is None:
        run_date = date.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / f"{run_date.isoformat()}.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Données brutes sauvegardées : %s", filepath)
    return filepath


def load_raw_data(raw_dir: str, run_date: date | None = None) -> dict:
    """Charge les données depuis data/raw/YYYY-MM-DD.json."""
    if run_date is None:
        run_date = date.today()

    filepath = Path(raw_dir) / f"{run_date.isoformat()}.json"
    if not filepath.exists():
        raise FileNotFoundError(
            f"Données brutes introuvables pour {run_date.isoformat()} dans {raw_dir}"
        )

    data = json.loads(filepath.read_text(encoding="utf-8"))
    logger.info(
        "Données brutes chargées : %s (%d créneaux)", filepath, len(data.get("rows", []))
    )
    return data
