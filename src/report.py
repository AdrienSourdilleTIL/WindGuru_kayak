"""
report.py — Génération du rapport HTML via le template Jinja2 (V3).

Deux modes de rendu :
- mode "local"  : images encodées base64 inline (pour sauvegarde HTML standalone).
- mode "email"  : images référencées par CID (Content-ID) pour email multipart/related.
                  Les CID sont passés au template ; les pièces MIME sont gérées par email_sender.
"""

import base64
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

# CID fixes pour les 4 graphiques (utilisés en mode email)
CHART_CIDS = {
    "score":     "chart_score@kayak",
    "wind":      "chart_wind@kayak",
    "waves":     "chart_waves@kayak",
    "temp_rain": "chart_temprain@kayak",
}


def _date_to_long_fr(d: date) -> str:
    jour = JOURS_FR[d.weekday()]
    mois = MOIS_FR[d.month]
    return f"{jour} {d.day} {mois} {d.year}"


def _date_to_short_fr(d: date) -> str:
    return f"{JOURS_FR[d.weekday()][:3]}. {d.day:02d}/{d.month:02d}"


def _encode_image(path: Path) -> str:
    """Encode un fichier PNG en base64 pour intégration inline dans HTML."""
    return base64.b64encode(path.read_bytes()).decode("utf-8")


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
    charts_rendered: dict,
    today_hourly: list[dict] | None = None,
    windows_3h: list[dict] | None = None,
) -> dict:
    """
    Construit le contexte Jinja2 commun aux deux modes de rendu.

    Args:
        charts_rendered: Dict {'score': <src string>, 'wind': ..., ...}
                         En mode local : "data:image/png;base64,..."
                         En mode email : "cid:chart_score@kayak"
        today_hourly:    Liste de dicts horaires pour aujourd'hui (depuis get_today_hourly).
        windows_3h:      Liste de dicts créneaux 3h pour les 3 prochains jours.
    """
    tz = pytz.timezone(config["fishing"]["timezone"])
    now_local = datetime.now(tz)
    today = now_local.date()

    today_summary = next((s for s in daily_summaries if s["date"] == today), None)
    today_css = VERDICT_CSS.get(today_summary["verdict"] if today_summary else "", "moyen")

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

    # Résumé 14 jours enrichi (tous les jours, y compris aujourd'hui)
    all_days = [enrich(s) for s in daily_summaries]

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
        "today_summary":      enrich(today_summary) if today_summary else None,
        "today_css":          today_css,
        "today_hourly":       today_hourly or [],
        "best_hourly_score":  best_hourly_score,
        "windows_by_day":     windows_by_day,
        "all_days":           all_days,
        "top_days":           [enrich(s) for s in top_days],
        "bad_days":           [enrich(s) for s in bad_days],
        "recommendation":     _generate_recommendation(daily_summaries),
        "charts":             charts_rendered,
    }


def generate_report(
    df_scored,
    daily_summaries: list[dict],
    chart_paths: dict,
    config: dict,
    today_hourly: list[dict] | None = None,
    windows_3h: list[dict] | None = None,
    templates_dir: str = "templates",
    email_mode: bool = False,
) -> str:
    """
    Génère le rapport HTML complet.

    Args:
        df_scored:       DataFrame scoré.
        daily_summaries: Liste de résumés journaliers.
        chart_paths:     Dict {'score': Path, 'wind': Path, 'waves': Path, 'temp_rain': Path}.
        config:          Configuration chargée depuis config.yaml.
        today_hourly:    Liste de dicts horaires pour aujourd'hui.
        windows_3h:      Liste de dicts créneaux 3h pour les 3 prochains jours.
        templates_dir:   Dossier contenant report.html.
        email_mode:      Si True, utilise des CID pour les images (pour email multipart/related).
                         Si False, encode les images en base64 inline (HTML standalone).

    Returns:
        Chaîne HTML complète.
    """
    if email_mode:
        # Mode email : les images sont référencées par CID, attachées séparément par email_sender
        charts_rendered = {key: f"cid:{cid}" for key, cid in CHART_CIDS.items()}
    else:
        # Mode local : images base64 inline
        charts_rendered = {
            key: f"data:image/png;base64,{_encode_image(path)}"
            for key, path in chart_paths.items()
        }

    ctx = _build_template_context(
        daily_summaries, config, charts_rendered,
        today_hourly=today_hourly,
        windows_3h=windows_3h,
    )

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("report.html")
    html = template.render(**ctx)

    logger.info("Rapport HTML généré (%d caractères, mode=%s).", len(html), "email" if email_mode else "local")
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
