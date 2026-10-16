"""Règles de mise en couleur des lignes.

Chaque fonction reçoit un poste et renvoie une classe CSS Bootstrap
("table-success", "table-warning", "table-danger", "table-info"...) ou "".
Ce sont des exemples provisoires, à remplacer par vos règles Excel.
"""
from datetime import date


def couleur_poste_da(poste):
    postes_cmd = poste.postes_commande
    if not postes_cmd:
        # DA pas encore commandée et livraison dépassée
        if poste.date_livraison and poste.date_livraison < date.today():
            return "table-danger"
        return ""
    if all(p.csf for p in postes_cmd):
        return "table-success"
    return "table-info"


def couleur_poste_commande(poste):
    if poste.csf and not poste.ref_livrable:
        return "table-warning"
    if poste.csf:
        return "table-success"
    if poste.en_retard:
        return "table-danger"
    return ""
