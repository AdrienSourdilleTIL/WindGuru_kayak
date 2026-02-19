"""
fetch_data.py — Récupération des prévisions Windguru via micro.windguru.cz

Utilise l'endpoint widget public (pas d'authentification requise pour un spot connu).
Extrait le JSON embarqué dans le HTML retourné par le serveur.
"""

import json
import logging
import re
import time
from datetime import date
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

# Patterns possibles pour le JSON embarqué dans la réponse Windguru
_JSON_PATTERNS = [
    r"var\s+wg_fcst_tab_data\s*=\s*(\{.*?\})\s*;",
    r"wg_fcst_tab_data\s*=\s*(\{.*?\})\s*;",
]


class WindguruFetchError(Exception):
    """Levée quand la récupération des données Windguru échoue définitivement."""


def _extract_json_from_html(html: str) -> dict:
    """Extrait le bloc JSON wg_fcst_tab_data depuis le HTML retourné."""
    for pattern in _JSON_PATTERNS:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                logger.warning("JSON extrait invalide avec le pattern '%s': %s", pattern, e)

    # Si les patterns échouent, tenter une extraction plus large
    match = re.search(r"\{[\"']hrs[\"']\s*:\s*\[", html)
    if match:
        start = match.start()
        # Compter les accolades pour trouver la fin du bloc JSON
        depth = 0
        for i, char in enumerate(html[start:]):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start : start + i + 1])
                    except json.JSONDecodeError:
                        break

    raise WindguruFetchError(
        "Impossible d'extraire wg_fcst_tab_data depuis le HTML Windguru. "
        "La structure de la page a peut-être changé."
    )


def fetch_windguru_forecast(spot_id: int, model: str, variables: list[str]) -> dict:
    """
    Récupère les prévisions Windguru pour un spot donné.

    Args:
        spot_id: Identifiant numérique du spot Windguru (ex: 48552)
        model:   Modèle météo à utiliser (ex: "gfs")
        variables: Liste des variables à demander (ex: ["WSPD", "GUST", "TMP"])

    Returns:
        dict contenant les données brutes Windguru (hrs, fcst, init_d, etc.)

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
            logger.info(
                "Tentative %d/3 — Windguru spot %d, modèle %s", attempt, spot_id, model
            )
            response = requests.get(
                WINDGURU_WIDGET_URL,
                params=params,
                headers=HEADERS,
                timeout=30,
            )
            response.raise_for_status()

            data = _extract_json_from_html(response.text)

            # Vérification minimale de la structure
            if "hrs" not in data:
                raise WindguruFetchError("Clé 'hrs' absente des données récupérées.")

            # Avertissement si variables de vagues absentes
            fcst = data.get("fcst", {})
            for wave_var in ("HTSGW", "PERPW"):
                if wave_var not in fcst:
                    logger.warning(
                        "Variable %s absente des données — score vagues sera neutre.", wave_var
                    )

            logger.info("Données Windguru récupérées : %d créneaux horaires.", len(data["hrs"]))
            return data

        except (requests.RequestException, WindguruFetchError) as e:
            last_error = e
            if attempt < 3:
                wait = 2**attempt  # 2s, 4s, 8s
                logger.warning("Erreur (tentative %d/3) : %s. Retry dans %ds.", attempt, e, wait)
                time.sleep(wait)

    raise WindguruFetchError(
        f"Échec après 3 tentatives pour le spot {spot_id}. Dernière erreur : {last_error}"
    )


def save_raw_data(data: dict, output_dir: str, run_date: date | None = None) -> Path:
    """
    Sauvegarde les données brutes JSON dans data/raw/YYYY-MM-DD.json.

    Args:
        data:       Dictionnaire de données brutes Windguru.
        output_dir: Dossier de destination (ex: "data/raw").
        run_date:   Date d'exécution (défaut : aujourd'hui).

    Returns:
        Path vers le fichier JSON créé.
    """
    if run_date is None:
        run_date = date.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / f"{run_date.isoformat()}.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Données brutes sauvegardées : %s", filepath)
    return filepath


def load_raw_data(raw_dir: str, run_date: date | None = None) -> dict:
    """
    Charge les données brutes JSON depuis data/raw/YYYY-MM-DD.json.
    Utile pour rejouer le pipeline sans refaire un appel réseau.

    Args:
        raw_dir:  Dossier source (ex: "data/raw").
        run_date: Date à charger (défaut : aujourd'hui).

    Returns:
        dict des données brutes Windguru.

    Raises:
        FileNotFoundError: Si le fichier du jour n'existe pas.
    """
    if run_date is None:
        run_date = date.today()

    filepath = Path(raw_dir) / f"{run_date.isoformat()}.json"
    if not filepath.exists():
        raise FileNotFoundError(
            f"Données brutes introuvables pour {run_date.isoformat()} dans {raw_dir}"
        )

    data = json.loads(filepath.read_text(encoding="utf-8"))
    logger.info("Données brutes chargées : %s (%d créneaux)", filepath, len(data.get("hrs", [])))
    return data
