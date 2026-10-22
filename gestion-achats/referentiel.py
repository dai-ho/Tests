"""Référentiel des centres de coût (codes EOTP) : type, désignation SAP, description,
activité de rattachement ; import CSV par type ; regroupement Type → Activité → Code."""
import re
import unicodedata

from formulaires import lignes_csv
from models import (TYPE_NON_CLASSE, TYPES_CODE, Activite, Affectation, AliasCode, ElementRecepteur,
                    TempsSaisi, db)

SANS_ACTIVITE = "(sans activité)"


def cle(code):
    return (code or "").strip().upper()


def elements_par_code(avec_alias=False):
    """clé du code -> élément du référentiel ; avec_alias : les autres graphies aussi."""
    resultat = {cle(e.code): e for e in ElementRecepteur.query}
    if avec_alias:
        for a in AliasCode.query:
            resultat.setdefault(cle(a.alias), a.element)
    return resultat


def table_canonique():
    """clé d'un alias -> code de référence, pour convertir les codes à l'import."""
    return {cle(a.alias): a.element.code for a in AliasCode.query}


def forme_reduite(code):
    """Forme de comparaison pour repérer les doublons : sans parenthèses, crochets, espaces,
    guillemets ni ponctuation finale, en majuscules."""
    return re.sub(r"[\s()\[\]\"'.;,]+", "", (code or "").upper())


def doublons_probables(codes):
    """Groupes de codes identiques une fois réduits : [(code proposé comme référence, [autres])].
    La référence proposée : le code du référentiel qui a une désignation, sinon le plus court."""
    elements = elements_par_code()
    groupes = {}
    for c in codes:
        groupes.setdefault(forme_reduite(c), set()).add(c)
    resultat = []
    for variantes in groupes.values():
        if len(variantes) < 2:
            continue
        cible = min(variantes, key=lambda c: (not (elements.get(cle(c)) and elements[cle(c)].designation),
                                             cle(c) not in elements, len(c), c))
        resultat.append((cible, sorted(variantes - {cible})))
    return sorted(resultat)


# --- Renommage et fusion -----------------------------------------------------------------

def _reecrire(ancien, nouveau):
    """Reporte les temps saisis et le plan de charge de l'ancien code sur le nouveau,
    en additionnant les valeurs qui se recouvrent (même personne, même date / année)."""
    if cle(ancien) == cle(nouveau) and ancien == nouveau:
        return
    for modele, champ_code, cles_uniques, champ_valeur in (
            (TempsSaisi, "code", ("agent_id", "date"), "heures"),
            (Affectation, "projet", ("agent_id", "annee"), "etp")):
        existants = {}
        for ligne in modele.query:
            if cle(getattr(ligne, champ_code)) == cle(nouveau) and getattr(ligne, champ_code) == nouveau:
                existants[tuple(getattr(ligne, k) for k in cles_uniques)] = ligne
        for ligne in [l for l in modele.query if cle(getattr(l, champ_code)) == cle(ancien)
                      and getattr(l, champ_code) != nouveau]:
            k = tuple(getattr(ligne, c) for c in cles_uniques)
            if k in existants:  # même personne et même période sur les deux codes : cumul
                cible = existants[k]
                setattr(cible, champ_valeur, (getattr(cible, champ_valeur) or 0)
                        + (getattr(ligne, champ_valeur) or 0))
                db.session.delete(ligne)
            else:
                setattr(ligne, champ_code, nouveau)
                existants[k] = ligne
        db.session.flush()


def _ajouter_alias(element, graphie):
    if not graphie or cle(graphie) == cle(element.code):
        return
    existant = next((a for a in AliasCode.query if cle(a.alias) == cle(graphie)), None)
    if existant:
        existant.element = element
    else:
        element.alias.append(AliasCode(alias=graphie.strip()))


def renommer(element, nouveau):
    """Change le code d'un élément. Si le nouveau code existe déjà (code ou alias d'un autre
    élément), les deux sont fusionnés dans celui-ci. Renvoie l'élément conservé."""
    nouveau = nouveau.strip()
    autre = elements_par_code(avec_alias=True).get(cle(nouveau))
    if autre is not None and autre is not element:
        return fusionner(element.code, autre, source=element)
    ancien = element.code
    for a in list(element.alias):  # le nouveau code ne peut plus être un alias de lui-même
        if cle(a.alias) == cle(nouveau):
            db.session.delete(a)
    element.code = nouveau
    db.session.flush()
    _ajouter_alias(element, ancien)
    _reecrire(ancien, nouveau)
    return element


def fusionner(code_source, cible, source=None):
    """Fusionne un code (élément du référentiel `source`, ou code seulement utilisé) dans
    l'élément `cible` : informations manquantes complétées, alias repris, temps et plan de
    charge reportés ; l'ancien code devient un alias de la cible."""
    if source is not None and source is not cible:
        for champ in ("designation", "description", "type"):
            if not getattr(cible, champ) and getattr(source, champ):
                setattr(cible, champ, getattr(source, champ))
        if cible.activite is None and source.activite is not None and (
                source.activite.type == cible.type):
            cible.activite = source.activite
        for a in list(source.alias):
            a.element = cible
        db.session.delete(source)
        db.session.flush()
    _ajouter_alias(cible, code_source)
    _reecrire(code_source, cible.code)
    return cible


def regrouper(codes):
    """Range des codes en [(type, [(activité, [codes])])], dans l'ordre des types puis des
    activités (« sans activité » en dernier) ; les codes absents du référentiel vont dans
    « Non classé »."""
    elements = elements_par_code(avec_alias=True)
    arbre = {}
    for code in codes:
        e = elements.get(cle(code))
        type_ = (e.type if e and e.type else None) or TYPE_NON_CLASSE
        activite = e.activite.nom if e and e.activite else SANS_ACTIVITE
        arbre.setdefault(type_, {}).setdefault(activite, []).append(code)
    ordre_types = TYPES_CODE + sorted(t for t in arbre if t not in TYPES_CODE and t != TYPE_NON_CLASSE)
    ordre_types.append(TYPE_NON_CLASSE)
    return [(t, [(a, sorted(arbre[t][a])) for a in sorted(arbre[t], key=lambda a: (a == SANS_ACTIVITE, a.lower()))])
            for t in ordre_types if t in arbre]


def designations(codes):
    """code -> désignation SAP (pour info-bulles et libellés)."""
    elements = elements_par_code()
    return {c: elements[cle(c)].designation for c in codes
            if cle(c) in elements and elements[cle(c)].designation}


# --- Import CSV d'un type ---------------------------------------------------------------

def _normaliser(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()


def importer_csv(contenu, type_):
    """Colonnes : code EOTP, désignation SAP, description, cible MSO (ignorée).
    Crée ou met à jour les codes (le type est imposé ; l'activité existante est conservée).
    Renvoie (créés, mis à jour, lignes ignorées)."""
    elements = elements_par_code()
    crees = mis_a_jour = 0
    ignorees = []
    for num, ligne in enumerate(lignes_csv(contenu), start=1):
        cellules = [c.strip() for c in ligne] + ["", "", ""]
        # « HORSREMUNER | Absences non rémunérées » : code avant « | », libellé après
        code, _, complement = cellules[0].partition("|")
        code, complement = code.strip(), complement.strip()
        if not code:
            continue
        if num == 1 and ("eotp" in _normaliser(code) or "code" in _normaliser(code)):
            continue  # ligne d'en-tête
        if len(code) > 100 or any(ch in code for ch in "\t\n\""):
            ignorees.append(num)
            continue
        if complement:
            cellules[2] = f"{complement} — {cellules[2]}" if cellules[2] else complement
        e = elements.get(cle(code))
        if e is None:
            e = elements[cle(code)] = ElementRecepteur(code=code)
            db.session.add(e)
            crees += 1
        else:
            mis_a_jour += 1
            if e.activite and e.activite.type != type_:
                e.activite = None  # l'activité d'un autre type ne convient plus
        e.type = type_
        e.designation = cellules[1] or e.designation
        e.description = cellules[2] or e.description
        # cellules[3] : cible MSO, ignorée
    db.session.commit()
    return crees, mis_a_jour, ignorees


def activites_par_type():
    resultat = {t: [] for t in TYPES_CODE}
    for a in Activite.query.order_by(Activite.nom):
        resultat.setdefault(a.type, []).append(a)
    return resultat
