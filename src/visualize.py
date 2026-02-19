"""
visualize.py — Génération des graphiques matplotlib pour le rapport de pêche (V2).

Produit 4 graphiques PNG sauvegardés dans le dossier reports/ :
  1. score_14days.png   — Score de pêche journalier (barres colorées)
  2. wind_14days.png    — Vent moyen + rafales (en nœuds) + direction
  3. waves_14days.png   — Hauteur des vagues (axe gauche) + période (axe droit)
  4. temp_rain_14days.png — Température + précipitations
"""

import logging
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

logger = logging.getLogger(__name__)

SCORE_COLORS = {
    "Excellent":   "#2ecc71",
    "Favorable":   "#f1c40f",
    "Moyen":       "#e67e22",
    "Déconseillé": "#e74c3c",
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
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=8)


def chart_fishing_score(daily_summaries: list[dict], output_dir: Path) -> Path:
    """Graphique 1 : Score de pêche sur 14 jours (barres verticales colorées)."""
    dates = [s["date"] for s in daily_summaries]
    scores = [s["daily_score"] for s in daily_summaries]
    colors = [_score_to_color(s) for s in scores]

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#f8f9fa")

    bars = ax.bar(dates, scores, color=colors, width=0.7, zorder=3, edgecolor="white", linewidth=0.8)

    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{int(score)}",
            ha="center", va="bottom", fontsize=9, fontweight="bold",
            color="#2c3e50",
        )

    ax.axhline(50, color="#7f8c8d", linestyle="--", linewidth=1, zorder=2)
    ax.axhline(70, color="#27ae60", linestyle=":", linewidth=1, zorder=2)

    ax.set_ylim(0, 110)
    ax.set_ylabel("Score de pêche (/100)", fontsize=10)
    ax.set_title("Score de pêche kayak — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)
    ax.grid(axis="y", alpha=0.4, zorder=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=SCORE_COLORS["Excellent"],   label="Excellent (≥70)"),
        Patch(facecolor=SCORE_COLORS["Favorable"],   label="Favorable (≥50)"),
        Patch(facecolor=SCORE_COLORS["Moyen"],       label="Moyen (≥30)"),
        Patch(facecolor=SCORE_COLORS["Déconseillé"], label="Déconseillé (<30)"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8, framealpha=0.9)

    _setup_date_axis(ax, dates)
    plt.tight_layout()

    out = output_dir / "score_14days.png"
    plt.savefig(out, bbox_inches="tight")
    plt.close(fig)
    logger.info("Graphique score sauvegardé : %s", out)
    return out


def chart_wind(daily_summaries: list[dict], output_dir: Path) -> Path:
    """
    Graphique 2 : Vent moyen et rafales sur 14 jours (en nœuds).
    Affiche aussi la direction du vent sous chaque point.
    """
    dates = [s["date"] for s in daily_summaries]
    winds = [s.get("avg_wind_kts") or 0 for s in daily_summaries]
    gusts = [s.get("max_gust_kts") or 0 for s in daily_summaries]
    dirs  = [s.get("wind_dir_arrow", "") or "" for s in daily_summaries]

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#f8f9fa")

    ax.fill_between(dates, winds, gusts, alpha=0.2, color="#3498db", label="Zone vent→rafales")
    ax.plot(dates, winds, color="#2980b9", linewidth=2, marker="o", markersize=5,
            label="Vent moyen (kts)", zorder=3)
    ax.plot(dates, gusts, color="#e74c3c", linewidth=1.5, linestyle="--", marker="s", markersize=4,
            label="Rafales max (kts)", zorder=3)

    ax.axhline(15, color="#2ecc71", linestyle=":", linewidth=1.2, label="15 kts (idéal vent)")
    ax.axhline(17, color="#e67e22", linestyle=":", linewidth=1.2, label="17 kts (idéal rafales)")
    ax.axhline(25, color="#e74c3c", linestyle="--", linewidth=1.0, label="25 kts (seuil bloquant)")

    # Direction du vent sous les points vent moyen
    for d, w, arrow in zip(dates, winds, dirs):
        if arrow:
            ax.annotate(
                arrow,
                xy=(d, w),
                xytext=(0, -14),
                textcoords="offset points",
                ha="center", va="top", fontsize=10, color="#2c3e50",
            )

    ax.set_ylabel("Vitesse (nœuds)", fontsize=10)
    ax.set_title("Vent moyen et rafales — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)
    ax.legend(loc="upper right", fontsize=7, framealpha=0.9)
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
    Graphique 3 : Hauteur des vagues (axe gauche, vert) + période (axe droit, violet).
    """
    dates   = [s["date"] for s in daily_summaries]
    waves   = [s.get("avg_wave_m") for s in daily_summaries]
    periods = [s.get("avg_wave_period_s") for s in daily_summaries]

    has_waves   = not all(w is None for w in waves)
    has_periods = not all(p is None for p in periods)

    fig, ax1 = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax1.set_facecolor("#f8f9fa")

    if not has_waves and not has_periods:
        ax1.text(
            0.5, 0.5,
            "Données de vagues non disponibles\npour ce spot/modèle",
            transform=ax1.transAxes,
            ha="center", va="center", fontsize=14, color="#7f8c8d",
        )
    else:
        if has_waves:
            waves_filled = [w if w is not None else 0 for w in waves]
            ax1.fill_between(dates, waves_filled, alpha=0.30, color="#1abc9c")
            ax1.plot(dates, waves_filled, color="#16a085", linewidth=2, marker="o", markersize=5,
                     label="Hauteur vagues (m)", zorder=3)
            ax1.axhline(0.8, color="#e67e22", linestyle="--", linewidth=1.2, label="0.8m (attention)")
            ax1.axhline(1.2, color="#e74c3c", linestyle="--", linewidth=1.2, label="1.2m (seuil bloquant)")

        ax1.set_ylabel("Hauteur significative (m)", color="#16a085", fontsize=10)
        ax1.tick_params(axis="y", labelcolor="#16a085")

        if has_periods:
            ax2 = ax1.twinx()
            periods_filled = [p if p is not None else 0 for p in periods]
            ax2.plot(dates, periods_filled, color="#8e44ad", linewidth=2, linestyle="--",
                     marker="^", markersize=5, label="Période (s)", zorder=3)
            ax2.axhline(12, color="#9b59b6", linestyle=":", linewidth=1.2, label="12s (période idéale)")
            ax2.axhline(8, color="#d68910", linestyle=":", linewidth=1.0, label="8s (limite acceptable)")
            ax2.set_ylabel("Période (secondes)", color="#8e44ad", fontsize=10)
            ax2.tick_params(axis="y", labelcolor="#8e44ad")
            max_period = max((p for p in periods_filled if p), default=14)
            ax2.set_ylim(0, max(max_period * 1.3, 16))

            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8, framealpha=0.9)
        else:
            ax1.legend(loc="upper right", fontsize=8, framealpha=0.9)

    ax1.set_title("Vagues — Hauteur et période — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)
    ax1.grid(alpha=0.4)
    ax1.spines["top"].set_visible(False)

    _setup_date_axis(ax1, dates)
    plt.tight_layout()

    out = output_dir / "waves_14days.png"
    plt.savefig(out, bbox_inches="tight")
    plt.close(fig)
    logger.info("Graphique vagues sauvegardé : %s", out)
    return out


def chart_temp_rain(daily_summaries: list[dict], output_dir: Path) -> Path:
    """Graphique 4 : Température (courbe) + précipitations (barres) sur 14 jours."""
    dates = [s["date"] for s in daily_summaries]
    temps = [s.get("avg_temp_c") or 0 for s in daily_summaries]
    rains = [s.get("max_rain_mmh") or 0 for s in daily_summaries]

    fig, ax1 = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), dpi=FIGURE_DPI)
    fig.patch.set_facecolor("#f8f9fa")
    ax1.set_facecolor("#f8f9fa")

    ax1.axhspan(15, 25, alpha=0.08, color="#2ecc71", label="Zone idéale temp. (15–25°C)")
    ax1.plot(dates, temps, color="#e74c3c", linewidth=2.5, marker="o", markersize=5,
             label="Température (°C)", zorder=3)

    ax1.set_ylabel("Température (°C)", color="#e74c3c", fontsize=10)
    ax1.tick_params(axis="y", labelcolor="#e74c3c")

    ax2 = ax1.twinx()
    ax2.bar(dates, rains, color="#3498db", alpha=0.5, width=0.6, label="Précipitations max (mm/h)")
    ax2.set_ylabel("Précipitations (mm/h)", color="#3498db", fontsize=10)
    ax2.tick_params(axis="y", labelcolor="#3498db")

    ax1.set_title("Température et précipitations — La Couarde sur Mer", fontsize=12, fontweight="bold", pad=10)

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
        daily_summaries: Liste de résumés journaliers.
        output_dir:      Dossier de sortie (ex: "reports/").

    Returns:
        Dict avec clés 'score', 'wind', 'waves', 'temp_rain'.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    return {
        "score":     chart_fishing_score(daily_summaries, out),
        "wind":      chart_wind(daily_summaries, out),
        "waves":     chart_waves(daily_summaries, out),
        "temp_rain": chart_temp_rain(daily_summaries, out),
    }
