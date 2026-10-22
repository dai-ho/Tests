"""Référentiel des centres de coût (codes EOTP) : type, désignation SAP, description,
activité de rattachement ; import CSV par type ; regroupement Type → Activité → Code."""
import csv
import io
import re
import unicodedata

from models import TYPE_NON_CLASSE, TYPES_CODE, Activite, ElementRecepteur, db

SANS_ACTIVITE = "(sans activité)"


def cle(code):
    return (code or "").strip().upper()


def elements_par_code():
    return {cle(e.code): e for e in ElementRecepteur.query}


def regrouper(codes):
    """Range des codes en [(type, [(activité, [codes])])], dans l'ordre des types puis des
    activités (« sans activité » en dernier) ; les codes absents du référentiel vont dans
    « Non classé »."""
    elements = elements_par_code()
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
    texte = None
    for codage in ("utf-8-sig", "cp1252"):
        try:
            texte = contenu.decode(codage)
            break
        except UnicodeDecodeError:
            pass
    if texte is None:
        raise ValueError("encodage du fichier non reconnu")
    try:
        separateur = csv.Sniffer().sniff(texte[:4096], delimiters=";,\t").delimiter
    except csv.Error:
        separateur = ";"
    elements = elements_par_code()
    crees = mis_a_jour = 0
    ignorees = []
    for num, ligne in enumerate(csv.reader(io.StringIO(texte), delimiter=separateur), start=1):
        cellules = [c.strip() for c in ligne] + ["", "", ""]
        code = cellules[0]
        if not code:
            continue
        if num == 1 and ("eotp" in _normaliser(code) or "code" in _normaliser(code)):
            continue  # ligne d'en-tête
        if len(code) > 100:
            ignorees.append(num)
            continue
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
