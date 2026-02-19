"""
visualize.py — Génération des graphiques matplotlib pour le rapport de pêche.

Produit 4 graphiques PNG sauvegardés dans le dossier reports/ :
  1. score_14days.png  — Score de pêche journalier (barres colorées)
  2. wind_14days.png   — Vent moyen + rafales
  3. waves_14days.png  — Hauteur des vagues
  4. temp_rain_14days.png — Température + précipitations
"""

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Backend non-interactif pour GitHub Actions / serveurs

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

logger = logging.getLogger(__name__)

# Palette de couleurs par verdict
SCORE_COLORS = {
    "Excellent":    "#2ecc71",  # vert
    "Favorable":    "#f1c40f",  # jaune
    "Moyen":        "#e67e22",  # orange
    "Déconseillé":  "#e74c3c",  # rouge
}

FIGURE_DPI = 150
FIGURE_WIDTH = 12
FIGURE_HEIGHT = 4


def _score_to_color(score: float) -> str:
    if score >= 70:
        return SCORE_COLORS["Excellent"]
    if score >= 50:
        return SCORE_COLORS["Favorable"]
    if score >= 30:
        return SCORE_COLORS["Moyen"]
    return SCORE_COLORS["Déconseillé"]


def _setup_date_axis(ax, dates: list[date]) -> None:
    """Configure l'axe X avec des étiquettes de dates lisibles."""
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=8)


def chart_fishing_score(daily_summaries: list[dict], output_dir: Path) -> Path:
    """
    Graphique 1 : Score de pêche sur 14 jours (barres verticales colorées).
    """
    dates = [s["date"] for s in daily_summaries]
    scores = [s["daily_score"] for s in daily_summaries]
    colors = [_score_to_color(s) for s in scores]

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#f8f9fa")

    bars = ax.bar(dates, scores, color=colors, width=0.7, zorder=3, edgecolor="white", linewidth=0.8)

    # Étiquettes sur chaque barre
    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{int(score)}",
            ha="center", va="bottom", fontsize=9, fontweight="bold",
            color="#2c3e50",
        )

    # Ligne seuil "Favorable"
    ax.axhline(50, color="#7f8c8d", linestyle="--", linewidth=1, zorder=2, label="Seuil Favorable (50)")
    ax.axhline(70, color="#27ae60", linestyle=":", linewidth=1, zorder=2, label="Seuil Excellent (70)")

    ax.set_ylim(0, 110)
    ax.set_ylabel("Score de pêche (/100)", fontsize=10)
    ax.set_title("Score de pêche kayak — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.4, zorder=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    _setup_date_axis(ax, dates)

    # Légende des couleurs
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=SCORE_COLORS["Excellent"],   label="Excellent (≥70)"),
        Patch(facecolor=SCORE_COLORS["Favorable"],   label="Favorable (≥50)"),
        Patch(facecolor=SCORE_COLORS["Moyen"],       label="Moyen (≥30)"),
        Patch(facecolor=SCORE_COLORS["Déconseillé"], label="Déconseillé (<30)"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8, framealpha=0.9)

    plt.tight_layout()
    out = output_dir / "score_14days.png"
    plt.savefig(out, bbox_inches="tight")
    plt.close(fig)
    logger.info("Graphique score sauvegardé : %s", out)
    return out


def chart_wind(daily_summaries: list[dict], output_dir: Path) -> Path:
    """
    Graphique 2 : Vent moyen et rafales sur 14 jours.
    """
    dates = [s["date"] for s in daily_summaries]
    winds = [s.get("avg_wind_kmh") or 0 for s in daily_summaries]
    gusts = [s.get("max_gust_kmh") or 0 for s in daily_summaries]

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#f8f9fa")

    ax.fill_between(dates, winds, gusts, alpha=0.2, color="#3498db", label="Zone vent→rafales")
    ax.plot(dates, winds, color="#2980b9", linewidth=2, marker="o", markersize=5, label="Vent moyen (km/h)", zorder=3)
    ax.plot(dates, gusts, color="#e74c3c", linewidth=1.5, linestyle="--", marker="s", markersize=4, label="Rafales max (km/h)", zorder=3)

    ax.axhline(20, color="#2ecc71", linestyle=":", linewidth=1.2, label="20 km/h (limite idéale)")
    ax.axhline(30, color="#e67e22", linestyle=":", linewidth=1.2, label="30 km/h (limite acceptable)")

    ax.set_ylabel("Vitesse (km/h)", fontsize=10)
    ax.set_title("Vent moyen et rafales — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    _setup_date_axis(ax, dates)
    plt.tight_layout()

    out = output_dir / "wind_14days.png"
    plt.savefig(out, bbox_inches="tight")
    plt.close(fig)
    logger.info("Graphique vent sauvegardé : %s", out)
    return out


def chart_waves(daily_summaries: list[dict], output_dir: Path) -> Path:
    """
    Graphique 3 : Hauteur des vagues sur 14 jours.
    """
    dates = [s["date"] for s in daily_summaries]
    waves = [s.get("avg_wave_m") for s in daily_summaries]

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#f8f9fa")

    if all(w is None for w in waves):
        ax.text(
            0.5, 0.5,
            "Données de vagues non disponibles\npour ce spot/modèle",
            transform=ax.transAxes,
            ha="center", va="center", fontsize=14, color="#7f8c8d",
        )
    else:
        waves_filled = [w if w is not None else 0 for w in waves]
        ax.fill_between(dates, waves_filled, alpha=0.35, color="#1abc9c")
        ax.plot(dates, waves_filled, color="#16a085", linewidth=2, marker="o", markersize=5, label="Hauteur vagues (m)", zorder=3)

        ax.axhline(0.8, color="#e67e22", linestyle="--", linewidth=1.2, label="0.8m (limite idéale)")
        ax.axhline(1.2, color="#e74c3c", linestyle="--", linewidth=1.2, label="1.2m (limite acceptable)")

        ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    ax.set_ylabel("Hauteur significative (m)", fontsize=10)
    ax.set_title("Hauteur des vagues — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)
    ax.grid(alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    _setup_date_axis(ax, dates)
    plt.tight_layout()

    out = output_dir / "waves_14days.png"
    plt.savefig(out, bbox_inches="tight")
    plt.close(fig)
    logger.info("Graphique vagues sauvegardé : %s", out)
    return out


def chart_temp_rain(daily_summaries: list[dict], output_dir: Path) -> Path:
    """
    Graphique 4 : Température (courbe) + précipitations (barres) sur 14 jours.
    """
    dates = [s["date"] for s in daily_summaries]
    temps = [s.get("avg_temp_c") or 0 for s in daily_summaries]
    rains = [s.get("max_rain_mmh") or 0 for s in daily_summaries]

    fig, ax1 = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax1.set_facecolor("#f8f9fa")

    # Zone idéale température (15-25°C)
    ax1.axhspan(15, 25, alpha=0.08, color="#2ecc71", label="Zone idéale temp. (15–25°C)")
    ax1.plot(dates, temps, color="#e74c3c", linewidth=2.5, marker="o", markersize=5, label="Température (°C)", zorder=3)

    ax1.set_ylabel("Température (°C)", color="#e74c3c", fontsize=10)
    ax1.tick_params(axis="y", labelcolor="#e74c3c")

    # Axe secondaire : précipitations
    ax2 = ax1.twinx()
    ax2.bar(dates, rains, color="#3498db", alpha=0.5, width=0.6, label="Précipitations max (mm/h)")
    ax2.set_ylabel("Précipitations (mm/h)", color="#3498db", fontsize=10)
    ax2.tick_params(axis="y", labelcolor="#3498db")

    ax1.set_title("Température et précipitations — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)

    # Légendes combinées
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8, framealpha=0.9)

    ax1.grid(alpha=0.3)
    ax1.spines["top"].set_visible(False)

    _setup_date_axis(ax1, dates)
    plt.tight_layout()

    out = output_dir / "temp_rain_14days.png"
    plt.savefig(out, bbox_inches="tight")
    plt.close(fig)
    logger.info("Graphique temp/pluie sauvegardé : %s", out)
    return out


def generate_all_charts(
    df_scored: pd.DataFrame,
    daily_summaries: list[dict],
    output_dir: str,
) -> dict[str, Path]:
    """
    Génère les 4 graphiques et retourne un dict {nom: chemin_png}.

    Args:
        df_scored:       DataFrame avec colonne fishing_score.
        daily_summaries: Liste de résumés journaliers (depuis scoring.compute_scores).
        output_dir:      Dossier de sortie (ex: "reports/").

    Returns:
        Dict avec clés 'score', 'wind', 'waves', 'temp_rain'.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    return {
        "score":    chart_fishing_score(daily_summaries, out),
        "wind":     chart_wind(daily_summaries, out),
        "waves":    chart_waves(daily_summaries, out),
        "temp_rain": chart_temp_rain(daily_summaries, out),
    }
