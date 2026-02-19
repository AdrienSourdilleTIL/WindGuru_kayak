"""
main.py — Orchestrateur du système Kayak Fishing Forecast.

Enchaîne les étapes :
  1. Chargement de la configuration
  2. Récupération des données Windguru
  3. Normalisation des données
  4. Calcul des scores de pêche
  5. Génération des graphiques
  6. Génération du rapport HTML
  7. Envoi de l'email quotidien

Usage :
  python main.py               # Exécution complète
  python main.py --no-email    # Sans envoi d'email (test local)
  python main.py --no-fetch    # Utilise les données brutes déjà en cache
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import yaml

# Charger .env si présent (utile en développement local)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optionnel en production (GitHub Actions utilise les Secrets)

from src.fetch_data import (
    WindguruFetchError,
    fetch_windguru_forecast,
    load_raw_data,
    save_raw_data,
)
from src.process_data import process_data, save_processed_data
from src.scoring import compute_scores
from src.visualize import generate_all_charts
from src.report import generate_report, save_report
from src.email_sender import send_report_email


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(config_path: str = "config/config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(no_email: bool = False, no_fetch: bool = False) -> int:
    """
    Exécute le pipeline complet.

    Returns:
        Code de sortie (0 = succès, 1 = erreur).
    """
    setup_logging()
    logger = logging.getLogger("main")
    today = date.today()

    logger.info("=== Kayak Fishing Forecast — %s ===", today.isoformat())

    # 1. Configuration
    config = load_config()
    spot = config["spot"]
    logger.info("Spot : %s (ID %s, modèle %s)", spot["name"], spot["id"], spot["model"])

    # 2. Récupération des données Windguru
    raw_dir = "data/raw"
    if no_fetch:
        logger.info("Mode --no-fetch : chargement depuis le cache.")
        try:
            raw_data = load_raw_data(raw_dir)
        except FileNotFoundError as e:
            logger.error("Cache introuvable : %s", e)
            return 1
    else:
        try:
            raw_data = fetch_windguru_forecast(
                spot_id=spot["id"],
                model=spot["model"],
                variables=spot["variables"],
            )
            save_raw_data(raw_data, raw_dir, today)
        except WindguruFetchError as e:
            logger.error("Échec récupération Windguru : %s", e)
            if no_email:
                return 1
            # En production, on pourrait envoyer un email d'alerte ici
            logger.error("Le rapport ne sera pas envoyé.")
            return 1

    # 3. Normalisation
    df = process_data(raw_data, config)
    if df.empty:
        logger.error("Aucune donnée après normalisation. Arrêt.")
        return 1
    save_processed_data(df, "data/processed", today)

    # 4. Scoring
    df_scored, daily_summaries = compute_scores(df, config)

    if not daily_summaries:
        logger.error("Aucun résumé journalier produit. Arrêt.")
        return 1

    # Score du jour
    today_summary = next((s for s in daily_summaries if s["date"] == today), None)
    if today_summary:
        logger.info(
            "Score aujourd'hui : %s/100 — %s",
            today_summary["daily_score"],
            today_summary["verdict"],
        )

    # 5. Graphiques
    chart_paths = generate_all_charts(df_scored, daily_summaries, "reports")

    # 6. Rapport HTML
    html = generate_report(df_scored, daily_summaries, chart_paths, config)
    save_report(html, "reports", today)

    # 7. Envoi email
    if no_email:
        logger.info("Mode --no-email : envoi ignoré. Rapport disponible dans reports/")
        return 0

    try:
        send_report_email(html, config, daily_summaries)
        logger.info("Pipeline terminé avec succès.")
        return 0
    except RuntimeError as e:
        logger.error("Erreur envoi email : %s", e)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kayak Fishing Forecast — La Couarde sur Mer")
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Génère le rapport sans l'envoyer par email (test local).",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Utilise les données en cache (data/raw/) sans appeler Windguru.",
    )
    args = parser.parse_args()

    sys.exit(main(no_email=args.no_email, no_fetch=args.no_fetch))
