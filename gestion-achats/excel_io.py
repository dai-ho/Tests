"""Import / export Excel (.xlsx) des DA et des commandes."""
import re
import unicodedata
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from models import Commande, DemandeAchat, PosteCommande, PosteDA, db

# Colonnes reconnues : clé interne -> en-têtes acceptés (le premier sert à l'export).
# Les en-têtes sont comparés sans accents, sans casse ni ponctuation.
COLONNES_DA = {
    "reference": ["N° DA", "Num DA", "Numéro DA", "Référence DA", "Ref DA", "DA", "Référence"],
    "numero": ["Poste", "N° poste", "Poste DA"],
    "nom": ["Nom", "Désignation", "Libellé", "Intitulé"],
    "montant": ["Montant", "Montant HT", "Montant €", "Montant EUR"],
    "date_livraison": ["Date de livraison", "Date livraison", "Livraison"],
    "code_imputation": ["Code d'imputation", "Code imputation", "Imputation"],
    "demandeur": ["Demandeur"],
    "certificateur": ["Certificateur"],
}

COLONNES_CMD = {
    "reference": ["N° Commande", "Num commande", "Numéro commande", "Référence commande",
                  "Ref commande", "Commande", "Référence"],
    "numero": ["Poste", "N° poste", "Poste commande"],
    "da_reference": ["N° DA", "Num DA", "Numéro DA", "Référence DA", "Ref DA", "DA"],
    "da_poste": ["Poste DA", "N° poste DA"],
    "nom": ["Nom", "Désignation", "Libellé", "Intitulé"],
    "csf": ["CSF", "Certification", "Certifié", "Statut CSF"],
    "ref_livrable": ["Référence livrable", "Ref livrable", "Livrable", "Référence du livrable"],
    "ptf": ["PTF", "Proposition technique et financière"],
    "date_livraison": ["Date de livraison", "Date livraison", "Livraison"],
}

VRAI = {"oui", "o", "x", "1", "fait", "ok", "yes", "y", "vrai", "true", "certifie"}


def _normaliser(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()


def _texte(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _entier(v):
    s = _texte(v)
    return int(float(s.replace(",", "."))) if s else None


def _montant(v):
    if v is None or isinstance(v, (int, float)):
        return v
    s = re.sub(r"[^\d,.\-]", "", str(v)).replace(",", ".")
    return float(s) if s else None


def _date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"date illisible « {s} »")


def _booleen(v):
    if isinstance(v, bool):
        return v
    return _normaliser(v) in VRAI


def _lire_feuille(ws, colonnes):
    """Renvoie la liste des lignes (dict clé interne -> valeur) d'une feuille."""
    alias = {_normaliser(a): cle for cle, noms in colonnes.items() for a in noms}
    lignes = list(ws.iter_rows(values_only=True))
    for i, ligne in enumerate(lignes[:15]):
        mapping = {}
        for j, cellule in enumerate(ligne):
            cle = alias.get(_normaliser(cellule))
            if cle and cle not in mapping.values():
                mapping[j] = cle
        if "reference" in mapping.values() and "numero" in mapping.values():
            break
    else:
        raise ValueError(f"feuille « {ws.title} » : en-têtes introuvables "
                         "(il faut au moins une colonne référence et une colonne poste)")

    resultat, reference_courante = [], None
    for num_ligne, ligne in enumerate(lignes[i + 1:], start=i + 2):
        valeurs = {cle: ligne[j] if j < len(ligne) else None for j, cle in mapping.items()}
        if all(_texte(v) is None for v in valeurs.values()):
            continue
        # Cellules fusionnées : la référence n'est souvent saisie que sur le 1er poste
        if _texte(valeurs["reference"]):
            reference_courante = _texte(valeurs["reference"])
        valeurs["reference"] = reference_courante
        valeurs["_ligne"] = num_ligne
        resultat.append(valeurs)
    return resultat


def _trouver_feuilles(wb):
    feuille_da = feuille_cmd = None
    for ws in wb.worksheets:
        nom = _normaliser(ws.title)
        if "command" in nom and feuille_cmd is None:
            feuille_cmd = ws
        elif ("da" in nom.split() or "demande" in nom) and feuille_da is None:
            feuille_da = ws
    return feuille_da, feuille_cmd


def importer(fichier, vider=False):
    """Importe un classeur. Renvoie (nb_postes_da, nb_postes_cmd, erreurs)."""
    wb = load_workbook(fichier, data_only=True, read_only=True)
    feuille_da, feuille_cmd = _trouver_feuilles(wb)
    if feuille_da is None and feuille_cmd is None:
        raise ValueError("aucune feuille DA ou Commandes trouvée "
                         "(les onglets doivent contenir « DA » ou « Commande » dans leur nom)")

    if vider:
        PosteCommande.query.delete()
        Commande.query.delete()
        PosteDA.query.delete()
        DemandeAchat.query.delete()
        db.session.flush()

    erreurs, nb_da, nb_cmd = [], 0, 0

    if feuille_da is not None:
        das = {d.reference: d for d in DemandeAchat.query.all()}
        for v in _lire_feuille(feuille_da, COLONNES_DA):
            ou = f"{feuille_da.title} ligne {v['_ligne']}"
            try:
                ref, numero = v["reference"], _entier(v["numero"])
                if not ref or numero is None:
                    raise ValueError("référence ou numéro de poste manquant")
                # Conversion complète avant toute écriture : une ligne invalide est ignorée
                champs = dict(
                    nom=_texte(v.get("nom")) or f"Poste {numero}",
                    montant=_montant(v.get("montant")),
                    date_livraison=_date(v.get("date_livraison")),
                    code_imputation=_texte(v.get("code_imputation")),
                    demandeur=_texte(v.get("demandeur")),
                    certificateur=_texte(v.get("certificateur")),
                )
                da = das.get(ref)
                if da is None:
                    da = das[ref] = DemandeAchat(reference=ref)
                    db.session.add(da)
                poste = next((p for p in da.postes if p.numero == numero), None)
                if poste is None:
                    poste = PosteDA(numero=numero)
                    da.postes.append(poste)
                for cle, valeur in champs.items():
                    setattr(poste, cle, valeur)
                nb_da += 1
            except (ValueError, TypeError) as e:
                erreurs.append(f"{ou} : {e}")
        db.session.flush()

    if feuille_cmd is not None:
        postes_da = {(p.da.reference, p.numero): p for p in PosteDA.query.all()}
        cmds = {c.reference: c for c in Commande.query.all()}
        for v in _lire_feuille(feuille_cmd, COLONNES_CMD):
            ou = f"{feuille_cmd.title} ligne {v['_ligne']}"
            try:
                ref, numero = v["reference"], _entier(v["numero"])
                if not ref or numero is None:
                    raise ValueError("référence ou numéro de poste manquant")
                da_ref, da_poste = _texte(v.get("da_reference")), _entier(v.get("da_poste"))
                champs = dict(
                    nom=_texte(v.get("nom")) or f"Poste {numero}",
                    csf=_booleen(v.get("csf")),
                    ref_livrable=_texte(v.get("ref_livrable")) if _booleen(v.get("csf")) else None,
                    ptf=_texte(v.get("ptf")),
                    date_livraison=_date(v.get("date_livraison")),
                    poste_da=postes_da.get((da_ref, da_poste)) if da_ref else None,
                )
                cmd = cmds.get(ref)
                if cmd is None:
                    cmd = cmds[ref] = Commande(reference=ref)
                    db.session.add(cmd)
                poste = next((p for p in cmd.postes if p.numero == numero), None)
                if poste is None:
                    poste = PosteCommande(numero=numero)
                    cmd.postes.append(poste)
                for cle, valeur in champs.items():
                    setattr(poste, cle, valeur)
                if da_ref and poste.poste_da is None:
                    erreurs.append(f"{ou} : poste de DA {da_ref} / {da_poste} introuvable, "
                                   "poste importé sans lien")
                nb_cmd += 1
            except (ValueError, TypeError) as e:
                erreurs.append(f"{ou} : {e}")

    db.session.commit()
    return nb_da, nb_cmd, erreurs


def _ecrire_feuille(ws, entetes, lignes):
    ws.append(entetes)
    for cellule in ws[1]:
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="305496")
    for ligne in lignes:
        ws.append(ligne)
    for i, entete in enumerate(entetes, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, len(entete) + 4)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def exporter():
    """Exporte toute la base dans un classeur au format réimportable."""
    wb = Workbook()
    ws_da = wb.active
    ws_da.title = "DA"
    _ecrire_feuille(
        ws_da, [noms[0] for noms in COLONNES_DA.values()],
        [[p.da.reference, p.numero, p.nom, p.montant, p.date_livraison, p.code_imputation,
          p.demandeur, p.certificateur]
         for p in PosteDA.query.join(DemandeAchat)
                               .order_by(DemandeAchat.reference, PosteDA.numero)],
    )
    _ecrire_feuille(
        wb.create_sheet("Commandes"), [noms[0] for noms in COLONNES_CMD.values()],
        [[p.commande.reference, p.numero,
          p.poste_da.da.reference if p.poste_da else None,
          p.poste_da.numero if p.poste_da else None,
          p.nom, "Oui" if p.csf else "Non", p.ref_livrable, p.ptf, p.date_livraison]
         for p in PosteCommande.query.join(Commande)
                                     .order_by(Commande.reference, PosteCommande.numero)],
    )
    for ws in wb.worksheets:
        for ligne in ws.iter_rows(min_row=2):
            for cellule in ligne:
                if isinstance(cellule.value, date):
                    cellule.number_format = "DD/MM/YYYY"
    flux = BytesIO()
    wb.save(flux)
    flux.seek(0)
    return flux
