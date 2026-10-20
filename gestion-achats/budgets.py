"""Situation des lignes budgétaires : budget (alloué ou demandé), prévisionnel des DA,
imputé réel des BdC, disponible.

Le lien se fait par le centre de coût (code_imputation) et l'année des postes de DA :
- prévu (DA)   = somme des valeurs des postes de DA de la ligne pour l'année (hors supprimés) ;
- imputé (BdC) = somme des postes de BdC rattachés à ces postes de DA.
"""
from collections import defaultdict
from datetime import date

from models import LigneBudgetaire, PosteDA


def cle(code):
    return (code or "").strip().upper()


def agregats():
    """Prévu (DA) et imputé (BdC) par (code, année), calculés en un seul passage."""
    prevu, impute = defaultdict(float), defaultdict(float)
    for p in PosteDA.query:
        if p.statut == "supprimé" or not p.code_imputation or not p.annee:
            continue
        k = (cle(p.code_imputation), p.annee)
        prevu[k] += p.montant or 0
        impute[k] += p.impute
    return prevu, impute


def situation(ligne, annee, ag=None):
    """Chiffres d'une ligne pour une année."""
    prevu, impute = ag or agregats()
    k = (cle(ligne.code), annee)
    b = ligne.budget(annee)
    total = b.total if b else 0
    s = {
        "ligne": ligne, "annee": annee, "budget": b,
        "statut": None if b is None else ("confirmé" if b.confirme else "demandé"),
        "total": total, "prevu": prevu.get(k, 0.0), "impute": impute.get(k, 0.0),
    }
    s["reste_da"] = total - s["prevu"]          # ce qu'il reste à programmer en DA
    s["disponible"] = total - s["impute"]       # ce qu'il reste réellement à commander
    s["alertes"] = alertes(s)
    return s


def alertes(s):
    """Incohérences et points d'attention d'une ligne pour une année."""
    a = []
    if s["budget"] is None and (s["prevu"] or s["impute"]):
        a.append(("danger", "DA sans budget pour cette année"))
    elif s["budget"] is not None:
        if s["impute"] > s["total"] + 0.005:
            a.append(("danger", "BdC supérieurs au budget"))
        elif s["prevu"] > s["total"] + 0.005:
            a.append(("warning", "DA supérieures au budget"))
    if s["budget"] is not None and s["disponible"] > 0.005 and not s["ligne"].reportable:
        if s["annee"] < date.today().year:
            a.append(("secondary", "non consommé : perdu"))
        elif s["annee"] == date.today().year:
            a.append(("info", "à consommer avant le 31/12"))
    return a


def lignes_filtrees(projet=""):
    """Lignes budgétaires, restreintes à un projet : celles du projet et celles
    qui portent des DA de ce projet."""
    lignes = LigneBudgetaire.query.order_by(LigneBudgetaire.type.desc(), LigneBudgetaire.code).all()
    if not projet:
        return lignes
    codes = {cle(p.code_imputation) for p in PosteDA.query.filter_by(projet=projet)}
    return [l for l in lignes if l.projet == projet or cle(l.code) in codes]


def codes_sans_ligne(annee=None):
    """Centres de coût utilisés dans les DA mais sans ligne budgétaire."""
    connus = {cle(l.code) for l in LigneBudgetaire.query}
    resultat = defaultdict(float)
    for p in PosteDA.query:
        if (p.code_imputation and cle(p.code_imputation) not in connus
                and p.statut != "supprimé" and (annee is None or p.annee == annee)):
            resultat[p.code_imputation.strip()] += p.montant or 0
    return sorted(resultat.items())


def annees_affichees():
    """Années de la vue pluriannuelle : de N-1 à N+1 au moins, élargies aux années renseignées."""
    n = date.today().year
    annees = {n - 1, n, n + 1}
    for l in LigneBudgetaire.query:
        annees |= {b.annee for b in l.annees}
    return list(range(min(annees), max(annees) + 1))


def controle(code, annee):
    """Avertissement à afficher après l'enregistrement d'un poste de DA ou de BdC,
    ou None si le budget est cohérent."""
    if not code or not annee:
        return None
    ligne = next((l for l in LigneBudgetaire.query if cle(l.code) == cle(code)), None)
    if ligne is None:
        if LigneBudgetaire.query.first() is None:
            return None  # aucun budget saisi : pas de contrôle
        return f"Attention : aucune ligne budgétaire « {code} » n'est définie."
    s = situation(ligne, annee)
    messages = [m for niveau, m in s["alertes"] if niveau in ("danger", "warning")]
    if not messages:
        return None
    eur = lambda v: f"{v:,.2f} €".replace(",", " ").replace(".", ",")
    return (f"Attention, budget {ligne.code} {annee} : {', '.join(messages)} "
            f"(budget {eur(s['total'])}{'' if s['statut'] == 'confirmé' else ' demandé'}, "
            f"DA {eur(s['prevu'])}, BdC {eur(s['impute'])}).")
