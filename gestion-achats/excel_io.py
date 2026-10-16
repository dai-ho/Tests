"""Import / export Excel (.xlsx) au format du fichier « Budgets GT »
(onglets « Suivi DA » et « Suivi BdC »)."""
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
# Les colonnes calculées d'Excel (DA@poste, Imputé, Disponible) sont recalculées par l'application.
COLONNES_DA = {
    "annee": ["Année", "Annee budgétaire"],
    "projet": ["Projet"],
    "reference": ["DA", "N° DA", "Num DA", "Numéro DA", "Référence DA"],
    "numero": ["poste", "N° poste", "Poste DA"],
    "nom": ["Désignation", "Nom", "Libellé", "Intitulé"],
    "montant": ["Valeur", "Montant", "Montant HT"],
    "code_imputation": ["Centre de coût", "Code d'imputation", "Imputation"],
    "budget": ["Budget"],
    "statut": ["Statut"],
    "remarque": ["Remarque", "Remarques", "Commentaire"],
    "date_livraison": ["Date de livraison", "Date livraison"],
    "demandeur": ["Demandeur"],
    "certificateur": ["Certificateur"],
}

COLONNES_CMD = {
    "societe": ["Société", "Fournisseur"],
    "activite": ["Activité"],
    "da_designation": ["Imputation", "Désignation DA"],
    "reference": ["BDC/Marché", "BDC", "N° BDC", "N° Commande", "Commande", "Marché"],
    "numero": ["poste du BDC", "Poste", "Poste commande"],
    "nom": ["Désignation", "Nom", "Libellé"],
    "montant": ["Montant"],
    "date_livraison": ["Echéance", "Date de livraison", "Date livraison"],
    "da_cle": ["DA@poste"],
    "ptf": ["PAF", "PTF"],
    "csf": ["CSF"],
    "ref_livrable": ["CR pour CSF", "Référence livrable", "Livrable"],
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


def _statut(v):
    s = _normaliser(v)
    if s.startswith("supprim"):
        return "supprimé"
    if s.startswith("clos"):
        return "clos"
    return _texte(v) or ""


def _lire_feuille(ws, colonnes, obligatoires):
    """Renvoie la liste des lignes (dict clé interne -> valeur) d'une feuille."""
    alias = {}
    for cle, noms in colonnes.items():
        for a in noms:
            alias.setdefault(_normaliser(a), cle)
    lignes = ws.iter_rows(values_only=True)
    for num_entete, ligne in enumerate(lignes, start=1):
        mapping = {}
        for j, cellule in enumerate(ligne):
            cle = alias.get(_normaliser(cellule))
            if cle and cle not in mapping.values():
                mapping[j] = cle
        if obligatoires <= set(mapping.values()):
            break
        if num_entete >= 15:
            raise ValueError(f"onglet « {ws.title} » : ligne d'en-tête introuvable "
                             f"(colonnes attendues : {', '.join(colonnes[c][0] for c in obligatoires)})")
    else:
        raise ValueError(f"onglet « {ws.title} » vide")

    resultat = []
    for num_ligne, ligne in enumerate(lignes, start=num_entete + 1):
        valeurs = {cle: ligne[j] if j < len(ligne) else None for j, cle in mapping.items()}
        if all(_texte(v) is None for v in valeurs.values()):
            continue
        valeurs["_ligne"] = num_ligne
        resultat.append(valeurs)
    return resultat


def _trouver_feuilles(wb):
    feuille_da = feuille_cmd = None
    for ws in wb.worksheets:
        mots = _normaliser(ws.title).split()
        if feuille_cmd is None and ({"bdc", "bc", "commandes", "commande"} & set(mots)):
            feuille_cmd = ws
        elif feuille_da is None and ("da" in mots or "demande" in mots or "demandes" in mots):
            feuille_da = ws
    return feuille_da, feuille_cmd


def _vider():
    PosteCommande.query.delete()
    Commande.query.delete()
    PosteDA.query.delete()
    DemandeAchat.query.delete()
    db.session.flush()


def _importer_da(feuille, erreurs):
    das = {d.reference: d for d in DemandeAchat.query.filter(DemandeAchat.reference.isnot(None))}
    # Postes sans n° de DA : retrouvés par leur désignation lors d'une mise à jour
    sans_numero = {p.nom: p for p in PosteDA.query.join(DemandeAchat)
                   .filter(DemandeAchat.reference.is_(None))}
    nb = 0
    for v in _lire_feuille(feuille, COLONNES_DA, {"reference", "numero", "nom"}):
        ou = f"{feuille.title} ligne {v['_ligne']}"
        try:
            ref, nom = _texte(v.get("reference")), _texte(v.get("nom"))
            numero = _entier(v.get("numero"))
            if not nom:
                if ref or numero:
                    raise ValueError("désignation manquante")
                continue  # ligne ne contenant que des valeurs annexes
            # Conversion complète avant toute écriture : une ligne invalide est ignorée
            champs = dict(
                nom=nom,
                montant=_montant(v.get("montant")),
                annee=_entier(v.get("annee")),
                projet=_texte(v.get("projet")),
                code_imputation=_texte(v.get("code_imputation")),
                budget=_montant(v.get("budget")),
                statut=_statut(v.get("statut")),
                remarque=_texte(v.get("remarque")),
                date_livraison=_date(v.get("date_livraison")),
                demandeur=_texte(v.get("demandeur")),
                certificateur=_texte(v.get("certificateur")),
            )
            if ref:
                if numero is None:
                    raise ValueError("numéro de poste manquant")
                da = das.get(ref)
                if da is None:
                    da = das[ref] = DemandeAchat(reference=ref)
                    db.session.add(da)
                poste = next((p for p in da.postes if p.numero == numero), None)
                if poste is None:
                    poste = PosteDA(numero=numero)
                    da.postes.append(poste)
            else:
                poste = sans_numero.get(nom)
                if poste is None:
                    da = DemandeAchat()
                    db.session.add(da)
                    poste = sans_numero[nom] = PosteDA(numero=numero or 10)
                    da.postes.append(poste)
            for cle, valeur in champs.items():
                setattr(poste, cle, valeur)
            nb += 1
        except (ValueError, TypeError) as e:
            erreurs.append(f"{ou} : {e}")
    db.session.flush()
    return nb


def _trouver_poste_da(v, par_designation, par_cle):
    """Retrouve le poste de DA d'une ligne de BdC : par la désignation (colonne
    « Imputation », comme la RECHERCHEV d'Excel), sinon par « DA@poste »."""
    designation = _texte(v.get("da_designation"))
    candidats = par_designation.get(_normaliser(designation), []) if designation else []
    cle = _texte(v.get("da_cle"))
    m = re.match(r"\s*([^@\s]*)@(\d+)", cle or "")
    if m:
        poste = par_cle.get((m.group(1), int(m.group(2))))
        if poste and (not candidats or poste in candidats):
            return poste, None
    if len(candidats) == 1:
        return candidats[0], None
    if len(candidats) > 1:
        return None, f"désignation de DA « {designation} » en double, poste importé sans lien"
    if designation or cle:
        return None, f"poste de DA « {designation or cle} » introuvable, poste importé sans lien"
    return None, None


def _importer_cmd(feuille, erreurs):
    par_designation, par_cle = {}, {}
    for p in PosteDA.query.all():
        par_designation.setdefault(_normaliser(p.nom), []).append(p)
        if p.da.reference:
            par_cle[(p.da.reference, p.numero)] = p
    cmds = {c.reference: c for c in Commande.query.all()}
    nb = 0
    for v in _lire_feuille(feuille, COLONNES_CMD, {"reference", "numero"}):
        ou = f"{feuille.title} ligne {v['_ligne']}"
        try:
            ref, numero = _texte(v.get("reference")), _entier(v.get("numero"))
            if not ref or numero is None:
                if _texte(v.get("nom")) or _texte(v.get("da_designation")):
                    raise ValueError("n° de BdC ou de poste manquant")
                continue
            csf = _booleen(v.get("csf"))
            poste_da, alerte = _trouver_poste_da(v, par_designation, par_cle)
            champs = dict(
                nom=_texte(v.get("nom")) or (poste_da.nom if poste_da else f"Poste {numero}"),
                activite=_texte(v.get("activite")),
                montant=_montant(v.get("montant")),
                date_livraison=_date(v.get("date_livraison")),
                ptf=_texte(v.get("ptf")),
                csf=csf,
                # La référence du livrable justifie la CSF : ignorée si la CSF n'est pas faite
                ref_livrable=_texte(v.get("ref_livrable")) if csf else None,
                poste_da=poste_da,
            )
            cmd = cmds.get(ref)
            if cmd is None:
                cmd = cmds[ref] = Commande(reference=ref)
                db.session.add(cmd)
            cmd.societe = _texte(v.get("societe")) or cmd.societe
            poste = next((p for p in cmd.postes if p.numero == numero), None)
            if poste is None:
                poste = PosteCommande(numero=numero)
                cmd.postes.append(poste)
            for cle, valeur in champs.items():
                setattr(poste, cle, valeur)
            if alerte:
                erreurs.append(f"{ou} : {alerte}")
            nb += 1
        except (ValueError, TypeError) as e:
            erreurs.append(f"{ou} : {e}")
    return nb


def importer(fichier, vider=False):
    """Importe un classeur. Renvoie (nb_postes_da, nb_postes_cmd, erreurs)."""
    wb = load_workbook(fichier, data_only=True, read_only=True)
    feuille_da, feuille_cmd = _trouver_feuilles(wb)
    if feuille_da is None and feuille_cmd is None:
        raise ValueError("aucun onglet « Suivi DA » ou « Suivi BdC » trouvé")
    if vider:
        _vider()
    erreurs = []
    nb_da = _importer_da(feuille_da, erreurs) if feuille_da is not None else 0
    nb_cmd = _importer_cmd(feuille_cmd, erreurs) if feuille_cmd is not None else 0
    db.session.commit()
    return nb_da, nb_cmd, erreurs


# --- Export ----------------------------------------------------------------------

ENTETES_DA = ["Année", "Projet", "DA", "poste", "Désignation", "DA@poste", "Valeur",
              "Centre de coût", "Budget", "Imputé", "Disponible", "Statut", "Remarque",
              "Date de livraison", "Demandeur", "Certificateur"]
ENTETES_CMD = ["Société", "Activité", "Imputation", "BDC/Marché", "poste du BDC", "Désignation",
               "Montant", "Echéance", "DA@poste", "PAF", "CSF", "CR pour CSF"]
COLONNES_EUROS = {"Valeur", "Budget", "Imputé", "Disponible", "Montant"}


def _entier_si_possible(s):
    return int(s) if s and s.isdigit() else s


def _ecrire_feuille(ws, entetes, lignes):
    ws.append(entetes)
    for cellule in ws[1]:
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="305496")
    for ligne in lignes:
        ws.append(ligne)
    for i, entete in enumerate(entetes, start=1):
        lettre = get_column_letter(i)
        ws.column_dimensions[lettre].width = 40 if entete in ("Désignation", "Remarque", "Imputation") \
            else max(12, len(entete) + 4)
        for cellule in ws[lettre][1:]:
            if isinstance(cellule.value, date):
                cellule.number_format = "DD/MM/YYYY"
            elif entete in COLONNES_EUROS:
                cellule.number_format = '#,##0.00\\ "€"'
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def exporter():
    """Exporte toute la base au format du fichier Excel (réimportable)."""
    postes_da = (PosteDA.query.join(DemandeAchat)
                 .order_by(DemandeAchat.reference.is_(None), DemandeAchat.reference,
                           PosteDA.numero).all())
    postes_cmd = (PosteCommande.query.join(Commande)
                  .order_by(Commande.reference, PosteCommande.numero).all())
    wb = Workbook()
    ws_da = wb.active
    ws_da.title = "Suivi DA"
    _ecrire_feuille(ws_da, ENTETES_DA, [
        [p.annee, p.projet, _entier_si_possible(p.da.reference), p.numero, p.nom, p.cle,
         p.montant, p.code_imputation, p.budget, p.impute, p.disponible, p.statut or None,
         p.remarque, p.date_livraison, p.demandeur, p.certificateur]
        for p in postes_da])
    _ecrire_feuille(wb.create_sheet("Suivi BdC"), ENTETES_CMD, [
        [p.commande.societe, p.activite, p.poste_da.nom if p.poste_da else None,
         _entier_si_possible(p.commande.reference), p.numero, p.nom, p.montant, p.date_livraison,
         p.poste_da.cle if p.poste_da else None, p.ptf, "OK" if p.csf else None, p.ref_livrable]
        for p in postes_cmd])
    flux = BytesIO()
    wb.save(flux)
    flux.seek(0)
    return flux
