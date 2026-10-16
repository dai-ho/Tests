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


def contenu(cmd):
    """Éléments de l'e-mail de demande pour un BdC : destinataire, objet, paragraphes
    d'introduction, lignes du tableau des postes (une liste de cellules par poste), fin."""
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

    # Une ligne par poste : désignation, montant, échéance, rappel du poste de DA
    lignes = [[poste.nom, _euros(poste.montant),
               poste.date_livraison.strftime("%d/%m/%y") if poste.date_livraison else "",
               poste.poste_da.rappel if poste.poste_da else ""]
              for poste in cmd.postes]

    salutation = f"Bonjour {p['mail_prenom']}," if p["mail_prenom"] else "Bonjour,"
    return {"destinataire": p["mail_destinataire"], "objet": objet,
            "intro": [salutation, demande], "lignes": lignes,
            "fin": [x for x in (p["mail_fin"], p["mail_signature"]) if x]}


def generer(cmd):
    """Renvoie (destinataire, objet, corps en texte brut) de l'e-mail de demande pour un BdC.
    Les colonnes du tableau des postes sont séparées par des tabulations."""
    c = contenu(cmd)
    tableau = "\n".join("\t".join(ligne) for ligne in c["lignes"])
    corps = "\n\n".join(x for x in [*c["intro"], tableau, *c["fin"]] if x)
    return c["destinataire"], c["objet"], corps


def lien_mailto(cmd):
    """Lien qui ouvre un nouveau message pré-rempli dans la messagerie (Outlook)."""
    destinataire, objet, corps = generer(cmd)
    corps = corps.replace("\n", "\r\n")
    return (f"mailto:{quote(destinataire, safe='@;,')}"
            f"?subject={quote(objet)}&body={quote(corps)}")
