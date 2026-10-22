"""Outils communs aux pages : lecture des formulaires, enregistrement, filtre année / projet."""
from datetime import date, datetime

from flask import flash, request, session
from sqlalchemy.exc import IntegrityError

from models import db


def champ(nom):
    v = request.form.get(nom, "").strip()
    return v or None


def champ_entier(nom):
    v = champ(nom)
    return int(v) if v else None


def champ_montant(nom):
    """Nombre saisi à la française : « 1 500,50 », « 0,5 », « 24000 € »."""
    v = champ(nom)
    return float(v.replace(" ", "").replace(" ", "").replace("€", "").replace(",", ".")) if v else None


def champ_date(nom):
    v = champ(nom)
    return datetime.strptime(v, "%Y-%m-%d").date() if v else None


def enregistrer(message_ok, message_doublon):
    try:
        db.session.commit()
        flash(message_ok, "success")
        return True
    except IntegrityError:
        db.session.rollback()
        flash(message_doublon, "danger")
        return False


def valeurs_distinctes(colonne):
    """Valeurs déjà saisies, proposées en suggestion dans les formulaires."""
    return [v for (v,) in db.session.query(colonne).distinct().order_by(colonne) if v]


def filtre_courant():
    """(année, projet) choisis dans le bandeau de filtre : année en cours par défaut,
    None = toutes les années ; "" = tous les projets."""
    return session.get("annee", date.today().year), session.get("projet", "")
