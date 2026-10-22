"""Outils communs aux pages : lecture des formulaires et des fichiers importés, enregistrement,
filtre année / projet."""
import csv
import io
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


def decoder_texte(contenu):
    """Texte d'un fichier importé : UTF-16 (« Texte Unicode » d'Excel), UTF-8 ou Windows-1252."""
    if contenu.startswith((b"\xff\xfe", b"\xfe\xff")):
        return contenu.decode("utf-16")
    if b"\x00" in contenu[:200]:  # UTF-16 sans marque d'ordre des octets
        return contenu.decode("utf-16-le" if contenu[1:2] == b"\x00" else "utf-16-be")
    for codage in ("utf-8-sig", "cp1252"):
        try:
            return contenu.decode(codage)
        except UnicodeDecodeError:
            pass
    raise ValueError("encodage du fichier non reconnu")


def lignes_csv(contenu):
    """Lignes d'un fichier CSV / texte tabulé ; le séparateur (tabulation, « ; » ou « , ») est
    celui qui revient le plus dans la ligne d'en-tête. Les cellules entre guillemets peuvent
    contenir des retours à la ligne."""
    texte = decoder_texte(contenu)
    entete = texte.lstrip().split("\n", 1)[0]
    separateur = max(["\t", ";", ","], key=entete.count)
    return list(csv.reader(io.StringIO(texte, newline=""), delimiter=separateur))
