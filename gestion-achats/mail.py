"""E-mail de demande de commande au service achat (format du modèle « MSOGT Marché ... MOOZ »)."""
from urllib.parse import quote

from models import Parametre, db

# clé -> (libellé, valeur par défaut)
PARAMETRES = {
    "mail_destinataire": ("Adresse(s) e-mail du service achat (séparées par « ; »)", ""),
    "mail_prenom": ("Prénom du destinataire", "Lucie"),
    "mail_prefixe": ("Préfixe de l'objet", "[MSO/GT]"),
    "mail_fin": ("Formule de fin", "Merci beaucoup, et à très bientôt !"),
    "mail_signature": ("Signature", "Vincent"),
}


def parametres():
    valeurs = {p.cle: p.valeur for p in Parametre.query}
    return {cle: valeurs.get(cle, defaut) for cle, (_, defaut) in PARAMETRES.items()}


def enregistrer_parametres(valeurs):
    for cle in PARAMETRES:
        if cle in valeurs:
            db.session.merge(Parametre(cle=cle, valeur=valeurs[cle].strip()))
    db.session.commit()


def _euros(v):
    return f"{v or 0:,.2f} €".replace(",", " ").replace(".", ",")


def generer(cmd):
    """Renvoie (destinataire, objet, corps) de l'e-mail de demande pour un BdC."""
    p = parametres()
    projets = list(dict.fromkeys(
        poste.activite or (poste.poste_da.projet if poste.poste_da else None)
        for poste in cmd.postes))
    projets = ", ".join(x for x in projets if x)

    marche = cmd.marche
    objet = [p["mail_prefixe"], f"Marché {marche.reference}" if marche else "Demande de commande",
             projets]
    objet = " – ".join(x for x in objet if x)

    demande = "Pourrais-tu lancer la commande suivante"
    if marche:
        demande += f", sur le marché {marche.reference}"
        if cmd.lot:
            demande += f", sur le lot {cmd.lot}"
    demande += " ?"

    blocs = []
    for poste in cmd.postes:
        lignes = [poste.nom, _euros(poste.montant)]
        if poste.date_livraison:
            lignes.append(poste.date_livraison.strftime("%d/%m/%y"))
        if poste.poste_da:
            lignes.append(poste.poste_da.rappel)
        blocs.append("\n".join(lignes))

    salutation = f"Bonjour {p['mail_prenom']}," if p["mail_prenom"] else "Bonjour,"
    corps = "\n\n".join(x for x in [salutation, demande, *blocs, p["mail_fin"],
                                    p["mail_signature"]] if x)
    return p["mail_destinataire"], objet, corps


def lien_mailto(cmd):
    """Lien qui ouvre un nouveau message pré-rempli dans la messagerie (Outlook)."""
    destinataire, objet, corps = generer(cmd)
    corps = corps.replace("\n", "\r\n")
    return (f"mailto:{quote(destinataire, safe='@;,')}"
            f"?subject={quote(objet)}&body={quote(corps)}")
