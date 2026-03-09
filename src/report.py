"""
report.py — Génération du rapport HTML via le template Jinja2 (V4).
"""

import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pytz
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS_FR  = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
            "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

VERDICT_CSS = {
    "Excellent":   "excellent",
    "Favorable":   "favorable",
    "Moyen":       "moyen",
    "Déconseillé": "deconseille",
}

VERDICT_COLOR = {
    "Excellent":   "#276749",
    "Favorable":   "#744210",
    "Moyen":       "#7b341e",
    "Déconseillé": "#742a2a",
}


def _date_to_long_fr(d: date) -> str:
    jour = JOURS_FR[d.weekday()]
    mois = MOIS_FR[d.month]
    return f"{jour} {d.day} {mois} {d.year}"


def _date_to_short_fr(d: date) -> str:
    return f"{JOURS_FR[d.weekday()][:3]}. {d.day:02d}/{d.month:02d}"


def _group_windows_by_day(windows_3h: list[dict]) -> list[dict]:
    """
    Regroupe les créneaux 3h par jour et retourne une liste ordonnée de dicts :
    [{ date, day_long, day_short, windows: [...] }, ...]
    """
    grouped: dict = defaultdict(list)
    for w in windows_3h:
        grouped[w["date"]].append(w)

    result = []
    for day in sorted(grouped.keys()):
        result.append({
            "date":      day,
            "day_long":  _date_to_long_fr(day),
            "day_short": _date_to_short_fr(day),
            "windows":   grouped[day],
        })
    return result


def _generate_recommendation(daily_summaries: list[dict]) -> str:
    today = date.today()
    next_7 = [s for s in daily_summaries if s["date"] > today][:7]

    if not next_7:
        return "Données insuffisantes pour établir des recommandations pour les prochains jours."

    excellent = [s for s in next_7 if s["verdict"] == "Excellent"]
    favorable = [s for s in next_7 if s["verdict"] == "Favorable"]
    bad       = [s for s in next_7 if s["verdict"] == "Déconseillé"]

    lines = []

    good_days = excellent + favorable
    if good_days:
        names = [_date_to_short_fr(s["date"]) for s in good_days[:3]]
        if len(names) == 1:
            lines.append(f"✅ Sortie recommandée : <strong>{names[0]}</strong>.")
        else:
            lines.append(f"✅ Sorties recommandées : <strong>{', '.join(names[:-1])}</strong> et <strong>{names[-1]}</strong>.")
    else:
        lines.append("⚠️ Aucune journée particulièrement favorable cette semaine.")

    if excellent:
        best = max(excellent, key=lambda s: s["daily_score"])
        lines.append(
            f"🎣 Meilleure journée : <strong>{_date_to_short_fr(best['date'])}</strong> "
            f"(score {int(best['daily_score'])}/100"
            + (f", créneau idéal {best['best_window']}" if best.get("best_window") and best["best_window"] != "–" else "")
            + ")."
        )

    if bad:
        names = [_date_to_short_fr(s["date"]) for s in bad[:2]]
        factors = list({s["limiting_factor"] for s in bad[:2]})
        raison = factors[0] if factors else "conditions difficiles"
        lines.append(f"❌ À éviter : <strong>{', '.join(names)}</strong> ({raison}).")

    return "<br>".join(lines)


def _build_template_context(
    daily_summaries: list[dict],
    config: dict,
    today_hourly: list[dict] | None = None,
    windows_3h: list[dict] | None = None,
    tides: list[dict] | None = None,
) -> dict:
    tz = pytz.timezone(config["fishing"]["timezone"])
    now_local = datetime.now(tz)
    today = now_local.date()

    today_summary_raw = next((s for s in daily_summaries if s["date"] == today), None)
    today_css = VERDICT_CSS.get(today_summary_raw["verdict"] if today_summary_raw else "", "moyen")
    today_tide = {t["date"]: t for t in (tides or {})}.get(today)
    today_summary = enrich(today_summary_raw) if today_summary_raw else None
    if today_summary and today_tide:
        today_summary["coeff"]       = today_tide["coeff"]
        today_summary["coeff_label"] = today_tide["coeff_label"]
        today_summary["tides"]       = today_tide["tides"]

    future = [s for s in daily_summaries if s["date"] > today]
    top_days = sorted(future, key=lambda s: s["daily_score"], reverse=True)[:3]
    bad_days = [s for s in future if s["verdict"] == "Déconseillé"][:3]

    def enrich(s: dict) -> dict:
        s = dict(s)
        s["day_long"]  = _date_to_long_fr(s["date"])
        s["day_short"] = _date_to_short_fr(s["date"])
        s["css_class"] = VERDICT_CSS.get(s["verdict"], "moyen")
        s["color"]     = VERDICT_COLOR.get(s["verdict"], "#2d3748")
        return s

    # Index des marées par date pour accès O(1) dans le template
    tides_by_date: dict = {t["date"]: t for t in (tides or [])}

    # Enrichir les résumés journaliers avec les données de marées
    def enrich_with_tides(s: dict) -> dict:
        tide = tides_by_date.get(s["date"])
        if tide:
            s["coeff"]       = tide["coeff"]
            s["coeff_label"] = tide["coeff_label"]
            s["tides"]       = tide["tides"]
        else:
            s["coeff"]       = None
            s["coeff_label"] = None
            s["tides"]       = []
        return s

    # Résumé 14 jours enrichi (tous les jours, y compris aujourd'hui)
    all_days = [enrich_with_tides(enrich(s)) for s in daily_summaries]

    # Grouper les créneaux 3h par jour
    windows_by_day = _group_windows_by_day(windows_3h or [])

    # Score max du jour pour mettre en valeur les meilleures heures
    best_hourly_score = max((h["score"] for h in (today_hourly or [])), default=0)

    return {
        "spot_name":          config["spot"]["name"],
        "spot_id":            config["spot"]["id"],
        "model":              config["spot"]["model"],
        "today_str":          today.isoformat(),
        "today_long":         _date_to_long_fr(today),
        "generated_at":       now_local.strftime("%H:%M"),
        "today_summary":      today_summary,
        "today_css":          today_css,
        "today_hourly":       today_hourly or [],
        "best_hourly_score":  best_hourly_score,
        "windows_by_day":     windows_by_day,
        "all_days":           all_days,
        "top_days":           [enrich(s) for s in top_days],
        "bad_days":           [enrich(s) for s in bad_days],
        "recommendation":     _generate_recommendation(daily_summaries),
    }


def generate_report(
    df_scored,
    daily_summaries: list[dict],
    config: dict,
    today_hourly: list[dict] | None = None,
    windows_3h: list[dict] | None = None,
    tides: list[dict] | None = None,
    history_ctx: dict | None = None,
    templates_dir: str = "templates",
) -> str:
    """
    Génère le rapport HTML complet.

    Args:
        df_scored:       DataFrame scoré.
        daily_summaries: Liste de résumés journaliers.
        config:          Configuration chargée depuis config.yaml.
        today_hourly:    Liste de dicts horaires pour aujourd'hui.
        windows_3h:      Liste de dicts créneaux 3h pour les 3 prochains jours.
        templates_dir:   Dossier contenant report.html.

    Returns:
        Chaîne HTML complète.
    """
    ctx = _build_template_context(
        daily_summaries, config,
        today_hourly=today_hourly,
        windows_3h=windows_3h,
        tides=tides,
    )
    if history_ctx:
        ctx.update(history_ctx)

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")
    html = template.render(**ctx)

    logger.info("Rapport HTML généré (%d caractères).", len(html))
    return html


def save_report(html: str, output_dir: str, run_date: date | None = None) -> Path:
    """Sauvegarde le rapport HTML dans reports/YYYY-MM-DD.html."""
    if run_date is None:
        run_date = date.today()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filepath = out / f"{run_date.isoformat()}.html"
    filepath.write_text(html, encoding="utf-8")
    logger.info("Rapport HTML sauvegardé : %s", filepath)
    return filepath
