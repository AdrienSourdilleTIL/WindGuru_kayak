"""
email_sender.py — Envoi du rapport HTML par Gmail SMTP (V2).

Utilise STARTTLS sur le port 587. Les credentials sont lus depuis les
variables d'environnement GMAIL_USER et GMAIL_APP_PASSWORD.

Les graphiques sont attachés comme pièces MIME inline (Content-ID / CID),
ce qui garantit leur affichage dans Gmail et la plupart des clients email
(contrairement aux data: URIs base64 qui sont souvent bloquées).

Structure MIME :
  multipart/mixed
    └─ multipart/related
         ├─ multipart/alternative
         │    ├─ text/plain  (fallback)
         │    └─ text/html   (rapport avec <img src="cid:...">)
         ├─ image/png  (score chart,     Content-ID: chart_score@kayak)
         ├─ image/png  (wind chart,      Content-ID: chart_wind@kayak)
         ├─ image/png  (waves chart,     Content-ID: chart_waves@kayak)
         └─ image/png  (temp_rain chart, Content-ID: chart_temprain@kayak)
"""

import logging
import os
import smtplib
from datetime import date
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from src.report import CHART_CIDS

logger = logging.getLogger(__name__)


def _build_subject(config: dict, daily_summaries: list[dict]) -> str:
    today = date.today()
    today_summary = next((s for s in daily_summaries if s["date"] == today), None)

    spot = config["spot"]["name"]
    if today_summary:
        score = int(today_summary["daily_score"])
        verdict = today_summary["verdict"]
        emoji = {"Excellent": "🎣", "Favorable": "✅", "Moyen": "⚠️", "Déconseillé": "❌"}.get(verdict, "📊")
        return f"{emoji} Pêche Kayak — {spot} — {today.strftime('%d/%m')} — Score: {score}/100 — {verdict}"

    return f"📊 Pêche Kayak — {spot} — {today.strftime('%d/%m/%Y')}"


def send_report_email(
    html_content: str,
    config: dict,
    daily_summaries: list[dict],
    chart_paths: dict | None = None,
) -> None:
    """
    Envoie le rapport HTML par Gmail SMTP avec les graphiques en pièces CID inline.

    Args:
        html_content:    Contenu HTML du rapport (avec src="cid:..." pour les images).
        config:          Configuration chargée depuis config.yaml.
        daily_summaries: Liste de résumés journaliers (pour construire le sujet).
        chart_paths:     Dict {'score': Path, 'wind': Path, 'waves': Path, 'temp_rain': Path}.
                         Si None, les images ne sont pas attachées (mode dégradé).

    Raises:
        RuntimeError: Si les variables d'environnement GMAIL_USER ou
                      GMAIL_APP_PASSWORD sont absentes.
        smtplib.SMTPException: Si l'envoi SMTP échoue.
    """
    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not gmail_user:
        raise RuntimeError("Variable d'environnement GMAIL_USER manquante.")
    if not gmail_password:
        raise RuntimeError("Variable d'environnement GMAIL_APP_PASSWORD manquante.")

    smtp_host = config["email"]["smtp_host"]
    smtp_port = config["email"]["smtp_port"]
    subject = _build_subject(config, daily_summaries)

    # --- Construction de la structure MIME ---

    # Texte brut (fallback)
    today = date.today()
    today_summary = next((s for s in daily_summaries if s["date"] == today), None)
    text_body = (
        f"Rapport Pêche Kayak — {config['spot']['name']}\n"
        f"Date : {today.strftime('%d/%m/%Y')}\n"
    )
    if today_summary:
        text_body += (
            f"Score : {int(today_summary['daily_score'])}/100\n"
            f"Verdict : {today_summary['verdict']}\n"
        )
    text_body += "\nOuvrez ce message dans un client compatible HTML pour voir le rapport complet."

    # multipart/alternative : texte + HTML
    msg_alternative = MIMEMultipart("alternative")
    msg_alternative.attach(MIMEText(text_body, "plain", "utf-8"))
    msg_alternative.attach(MIMEText(html_content, "html", "utf-8"))

    if chart_paths:
        # multipart/related : contient alternative + images CID
        msg_related = MIMEMultipart("related")
        msg_related.attach(msg_alternative)

        for key, cid in CHART_CIDS.items():
            path = chart_paths.get(key)
            if path and Path(path).exists():
                img_data = Path(path).read_bytes()
                img = MIMEImage(img_data, _subtype="png")
                img.add_header("Content-ID", f"<{cid}>")
                img.add_header("Content-Disposition", "inline", filename=Path(path).name)
                msg_related.attach(img)
                logger.debug("Image attachée : %s (CID: %s)", path, cid)
            else:
                logger.warning("Image manquante pour CID %s : %s", cid, path)

        # multipart/mixed : enveloppe finale
        msg = MIMEMultipart("mixed")
        msg.attach(msg_related)
    else:
        # Mode dégradé sans images
        msg = MIMEMultipart("mixed")
        msg.attach(msg_alternative)

    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = gmail_user

    # --- Envoi via Gmail SMTP ---
    logger.info("Connexion SMTP à %s:%d …", smtp_host, smtp_port)
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, gmail_user, msg.as_string())

        logger.info("Email envoyé avec succès à %s (sujet : %s)", gmail_user, subject)

    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(
            "Échec d'authentification Gmail. Vérifiez GMAIL_USER et GMAIL_APP_PASSWORD. "
            "L'App Password doit être créé sur https://myaccount.google.com/apppasswords"
        ) from e
    except smtplib.SMTPException as e:
        raise RuntimeError(f"Erreur SMTP lors de l'envoi : {e}") from e
