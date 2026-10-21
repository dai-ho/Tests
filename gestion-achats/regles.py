"""Règles de mise en couleur des lignes, reprises de la mise en forme
conditionnelle du fichier Excel « Budgets GT ».

Les règles sont évaluées dans l'ordre : la première qui s'applique donne la couleur
(comme la priorité des règles dans Excel). Pour modifier une couleur ou un libellé,
changer les dictionnaires COULEURS_* ; pour modifier une règle, changer la fonction.
"""
from datetime import date

# clé -> (couleur de fond, libellé affiché dans la légende)
# Les teintes sont définies dans static/app.css (variables --ligne-…), adaptées au thème sombre ;
# elles transposent les couleurs de la mise en forme conditionnelle du fichier Excel.
COULEURS_DA = {
    "supprime": ("var(--ligne-supprime)", "Statut « supprimé »"),
    "clos": ("var(--ligne-clos)", "Statut « clos »"),
    "sans_numero": ("var(--ligne-en-attente)", "N° de DA pas encore attribué"),
    "non_impute": ("var(--ligne-alerte)", "Rien d'imputé (aucun BdC)"),
    "annee_impaire": ("var(--ligne-annee-impaire)", "Année impaire"),
    "annee_paire": ("var(--ligne-annee-paire)", "Année paire"),
}

COULEURS_CMD = {
    "csf_ok": ("var(--ligne-clos)", "CSF OK"),
    "echeance_depassee": ("var(--ligne-alerte)", "Échéance dépassée, CSF non faite"),
    "en_attente": ("var(--ligne-en-attente)", "N° de BdC en attente"),
}


def regle_poste_da(poste):
    if poste.statut == "supprimé":
        return "supprime"
    if poste.statut == "clos":
        return "clos"
    if not poste.da.reference:
        return "sans_numero"
    if poste.impute == 0:
        return "non_impute"
    if poste.annee:
        return "annee_impaire" if poste.annee % 2 else "annee_paire"
    return None


def regle_poste_commande(poste):
    if poste.csf:
        return "csf_ok"
    if poste.date_livraison and poste.date_livraison < date.today():
        return "echeance_depassee"
    if not poste.commande.reference:
        return "en_attente"
    return None


def _style(couleurs, cle):
    # Variable CSS de Bootstrap : colore la ligne tout en gardant le survol
    return f"--bs-table-bg: {couleurs[cle][0]};" if cle else ""


def style_poste_da(poste):
    return _style(COULEURS_DA, regle_poste_da(poste))


def style_poste_commande(poste):
    return _style(COULEURS_CMD, regle_poste_commande(poste))
