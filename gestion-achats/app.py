"""Gestion des Demandes d'Achat et des Bons de Commande — application web locale."""
import glob
import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from collections import defaultdict
from datetime import date, datetime

from flask import (Flask, flash, g, redirect, render_template, request, send_file, session,
                   url_for)
from jinja2 import Undefined
from sqlalchemy import event, inspect, text
from sqlalchemy.pool import StaticPool

import budgets
import excel_io
from formulaires import (champ, champ_date, champ_entier, champ_montant, enregistrer,
                         filtre_courant, valeurs_distinctes)
import mail
import regles
import rh

try:
    import protection
except ImportError:  # bibliothèque « cryptography » pas encore installée (relancer lancer.bat)
    protection = None
from models import (STATUTS_DA, TYPES_BUDGET, Affectation, BudgetAnnuel, Commande,
                    DemandeAchat, LigneBudgetaire, Marche, PosteCommande, PosteDA, db)

# Pages sur lesquelles s'applique le filtre année / projet
PAGES_FILTREES = {"accueil", "liste_da", "postes_da", "liste_commandes", "postes_commande",
                  "liste_budgets", "rh.equipe", "rh.plan_charge", "rh.formations",
                  "rh.temps_realises"}

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_DONNEES = os.path.join(DOSSIER, "donnees")
FICHIER_BASE = os.path.join(DOSSIER_DONNEES, "achats.db")
FICHIER_JOURNAL = os.path.join(DOSSIER_DONNEES, "application.log")
SAUVEGARDES_GARDEES = 30


def mettre_de_cote_base_obsolete(chemin):
    """Une base créée par une version précédente (sans les colonnes du fichier
    Budgets GT) est renommée : une base neuve est créée, à remplir par import Excel."""
    if not os.path.exists(chemin):
        return
    with sqlite3.connect(chemin) as cnx:
        colonnes = {ligne[1] for ligne in cnx.execute("PRAGMA table_info(poste_da)")}
    if colonnes and "annee" not in colonnes:
        shutil.move(chemin, chemin.replace(".db", f"_ancienne_{datetime.now():%Y%m%d_%H%M%S}.db"))


def migrer():
    """Mises à jour de la structure d'une base existante."""
    with db.engine.begin() as cnx:
        # Codes illisibles (tabulation, retour à la ligne, guillemet) laissés par un import raté
        cnx.execute(text("DELETE FROM element_recepteur WHERE instr(code, char(9)) OR "
                         "instr(code, char(10)) OR instr(code, char(13)) OR instr(code, '\"')"))
    colonnes = {c["name"] for c in inspect(db.engine).get_columns("poste_commande")}
    if "societe" not in colonnes:
        # La société passe du BdC à chacun de ses postes
        avait_societe = "societe" in {c["name"] for c in inspect(db.engine).get_columns("commande")}
        with db.engine.begin() as cnx:
            cnx.execute(text("ALTER TABLE poste_commande ADD COLUMN societe VARCHAR(100)"))
            if avait_societe:
                cnx.execute(text("UPDATE poste_commande SET societe = "
                                 "(SELECT societe FROM commande WHERE commande.id = commande_id)"))

    colonnes = {c["name"]: c for c in inspect(db.engine).get_columns("commande")}
    if "marche_id" not in colonnes or not colonnes["reference"]["nullable"]:
        # N° de BdC devenu facultatif + rattachement à un marché : SQLite ne sachant pas
        # modifier une colonne, la table est recréée puis les données recopiées.
        communes = ", ".join(c for c in ("id", "reference", "commentaire") if c in colonnes)
        with db.engine.begin() as cnx:
            cnx.execute(text("ALTER TABLE commande RENAME TO commande_ancienne"))
            Commande.__table__.create(cnx)
            cnx.execute(text(f"INSERT INTO commande ({communes}) "
                             f"SELECT {communes} FROM commande_ancienne"))
            cnx.execute(text("DROP TABLE commande_ancienne"))

    if "simplifie" not in {c["name"] for c in inspect(db.engine).get_columns("marche")}:
        with db.engine.begin() as cnx:
            cnx.execute(text("ALTER TABLE marche ADD COLUMN simplifie BOOLEAN NOT NULL DEFAULT 0"))

    if "lot" not in {c["name"] for c in inspect(db.engine).get_columns("commande")}:
        # Le lot passe du marché à chaque commande : reprise du lot unique du marché
        with db.engine.begin() as cnx:
            cnx.execute(text("ALTER TABLE commande ADD COLUMN lot VARCHAR(100)"))
            cnx.execute(text("UPDATE commande SET lot = (SELECT lot FROM marche WHERE "
                             "marche.id = marche_id AND instr(marche.lot, ';') = 0)"))


def create_app(db_uri=None, dossier=None):
    """`dossier` : dossier des données (par défaut donnees/) ; `db_uri` : base imposée (tests),
    sans protection par carte."""
    app = Flask(__name__)
    dossier = dossier or DOSSIER_DONNEES
    os.makedirs(dossier, exist_ok=True)
    fichier_base = os.path.join(dossier, "achats.db")
    coffre = protection.Coffre(dossier) if protection else None
    protege = db_uri is None and os.path.exists(os.path.join(dossier, "achats.db.chiffre"))
    app.config.update(DOSSIER_DONNEES=dossier, FICHIER_BASE=fichier_base, PROTEGE=protege,
                      SECRET_KEY="application-locale")
    app.extensions["coffre"] = coffre
    if protege:
        # Base chiffrée : déchiffrée en mémoire au déverrouillage par la carte
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        if coffre:
            app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"creator": coffre.creer_connexion,
                                                       "poolclass": StaticPool}
    else:
        if db_uri is None:
            mettre_de_cote_base_obsolete(fichier_base)
            db_uri = "sqlite:///" + fichier_base
        app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    db.init_app(app)
    if not protege:
        with app.app_context():
            db.create_all()
            migrer()
    elif coffre:
        with app.app_context():
            # Chaque validation en base est aussitôt réécrite, chiffrée, sur le disque
            event.listen(db.session, "after_commit", lambda _: coffre.enregistrer())
        coffre.surveiller_carte()

    @app.template_filter("euros")
    def euros(v):
        if v is None or isinstance(v, Undefined):
            return ""
        return f"{v:,.2f} €".replace(",", " ").replace(".", ",")

    @app.template_filter("saisie")
    def saisie(v):
        """Montant pour un champ de formulaire : 24000 ou 1500,5."""
        if v is None or isinstance(v, Undefined):
            return ""
        return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")

    @app.template_filter("date_fr")
    def date_fr(d):
        return d.strftime("%d/%m/%Y") if d else ""

    @app.context_processor
    def contexte():
        return {"style_da": regles.style_poste_da,
                "style_cmd": regles.style_poste_commande,
                "couleurs_da": regles.COULEURS_DA,
                "couleurs_cmd": regles.COULEURS_CMD,
                "mailto": mail.lien_mailto,
                "aujourdhui": date.today()}

    @app.context_processor
    def contexte_filtre():
        if request.endpoint not in PAGES_FILTREES:
            return {}
        annee, projet = filtre_courant()
        annees = set(valeurs_distinctes(PosteDA.annee)) | {date.today().year}
        return {"filtre_actif": True, "filtre_annee": annee, "filtre_projet": projet,
                # Pages RH : le filtre par projet ne s'applique pas (elles portent sur les
                # centres de coût)
                "filtre_sans_projet": request.endpoint.startswith("rh."),
                "filtre_annees": sorted(annees, reverse=True),
                "filtre_projets": sorted(set(valeurs_distinctes(PosteDA.projet))
                                         | set(valeurs_distinctes(LigneBudgetaire.projet))
                                         | set(valeurs_distinctes(Affectation.projet)))}

    @app.before_request
    def controle_verrou():
        if not app.config["PROTEGE"]:
            return None
        if coffre is None:
            return render_template("erreur.html", message="La base est protégée par carte, mais la "
                                   "bibliothèque de chiffrement n'est pas installée : relancez "
                                   "lancer.bat."), 500
        coffre.verrou.acquire()  # la surveillance de la carte attend la fin de la requête
        g.verrou_pris = True
        if coffre.deverrouille or request.endpoint in ("verrou", "deverrouiller", "static",
                                                       "arreter"):
            return None
        return redirect(url_for("verrou", suivant=request.full_path))

    @app.teardown_request
    def liberer_verrou(_):
        if g.pop("verrou_pris", False):
            db.session.remove()
            coffre.verrou.release()

    @app.context_processor
    def contexte_protection():
        return {"base_protegee": app.config["PROTEGE"]}

    enregistrer_routes(app)
    enregistrer_routes_protection(app)
    app.register_blueprint(rh.bp)
    return app


def relancer(app):
    """Redémarre l'application (après activation ou retrait de la protection)."""
    if not app.config.get("RELANCE_POSSIBLE"):
        return  # tests : pas de processus à relancer
    arguments = [a for a in sys.argv[1:] if a != "--relance"] + ["--relance"]
    subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), *arguments], cwd=DOSSIER,
                     creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS, NEW_PROCESS_GROUP
                     close_fds=True)
    threading.Timer(0.5, lambda: os._exit(0)).start()


def enregistrer_routes_protection(app):
    coffre = app.extensions["coffre"]

    def ecran_redemarrage(message):
        relancer(app)
        return render_template("redemarrage.html", message=message,
                               relance=app.config.get("RELANCE_POSSIBLE"))

    @app.route("/verrou")
    def verrou():
        if not app.config["PROTEGE"] or coffre.deverrouille:
            return redirect(url_for("accueil"))
        return render_template("verrou.html", carte=protection.carte_presente(),
                               raison=coffre.raison_verrouillage, enveloppes=coffre.enveloppes(),
                               suivant=request.args.get("suivant", "/"))

    @app.post("/deverrouiller")
    def deverrouiller():
        suivant = request.form.get("suivant", "/")
        try:
            coffre.deverrouiller()
        except protection.ErreurProtection as e:
            flash(f"Déverrouillage impossible : {e}.", "danger")
            return redirect(url_for("verrou", suivant=suivant))
        db.engine.dispose()  # la prochaine connexion sera la base qui vient d'être chargée
        db.create_all()
        migrer()
        coffre.enregistrer()
        return redirect(suivant if suivant.startswith("/") and not suivant.startswith("//")
                        else url_for("accueil"))

    @app.post("/verrouiller")
    def verrouiller():
        if app.config["PROTEGE"]:
            db.session.remove()
            coffre.verrouiller("verrouillage manuel")
        return redirect(url_for("verrou"))

    @app.post("/protection/activer")
    def activer_protection():
        if app.config["PROTEGE"] or protection is None:
            return redirect(url_for("parametres"))
        try:
            certificat = next(c for c in protection.certificats_chiffrement()
                              if c["empreinte"] == request.form.get("empreinte"))
        except (StopIteration, protection.ErreurProtection):
            flash("Certificat introuvable.", "danger")
            return redirect(url_for("parametres"))
        dossier = app.config["DOSSIER_DONNEES"]
        autres = (glob.glob(os.path.join(dossier, "sauvegardes", "*.db"))
                  + glob.glob(os.path.join(dossier, "achats_ancienne_*.db")))
        db.session.remove()
        db.engine.dispose()  # libère le fichier de la base pour pouvoir l'effacer
        try:
            erreurs = coffre.activer(app.config["FICHIER_BASE"], certificat, autres)
        except protection.ErreurProtection as e:
            flash(f"Protection non activée : {e}.", "danger")
            return redirect(url_for("parametres"))
        if erreurs:
            flash("Sauvegardes restées en clair (à supprimer à la main) : " + ", ".join(erreurs),
                  "warning")
        return ecran_redemarrage("Protection activée : la base est désormais chiffrée. "
                                 "L'application redémarre et vous demandera de la déverrouiller.")

    @app.post("/protection/desactiver")
    def desactiver_protection():
        dossier = app.config["DOSSIER_DONNEES"]
        db.session.remove()
        try:
            coffre.desactiver(app.config["FICHIER_BASE"],
                              glob.glob(os.path.join(dossier, "sauvegardes", "*.db.chiffre")))
        except protection.ErreurProtection as e:
            flash(f"Impossible de retirer la protection : {e}.", "danger")
            return redirect(url_for("parametres"))
        return ecran_redemarrage("Protection retirée : la base est de nouveau en clair. "
                                 "L'application redémarre.")

    @app.post("/protection/certificat")
    def ajouter_certificat():
        try:
            certificat = next(c for c in protection.certificats_chiffrement()
                              if c["empreinte"] == request.form.get("empreinte"))
            coffre.ajouter_certificat(certificat)
            flash(f"Certificat « {certificat['sujet']} » (émis par {certificat['emetteur']}) "
                  "associé à la base.", "success")
        except StopIteration:
            flash("Certificat introuvable.", "danger")
        except protection.ErreurProtection as e:
            flash(f"Certificat non associé : {e}.", "danger")
        return redirect(url_for("parametres"))

    @app.post("/protection/certificat/<empreinte>/retirer")
    def retirer_certificat(empreinte):
        try:
            coffre.retirer_certificat(empreinte)
            flash("Certificat retiré : il ne permet plus d'ouvrir la base.", "success")
        except protection.ErreurProtection as e:
            flash(f"{str(e)[:1].upper()}{str(e)[1:]}.", "danger")
        return redirect(url_for("parametres"))


# --- Lecture des formulaires -------------------------------------------------

def tous_les_postes_da():
    return (PosteDA.query.join(DemandeAchat)
            .order_by(DemandeAchat.reference.is_(None), DemandeAchat.reference,
                      PosteDA.numero).all())


def garder_poste_da(p, annee, projet):
    return (annee is None or p.annee == annee) and (not projet or p.projet == projet)


def garder_poste_cmd(p, annee, projet):
    """Un poste de BdC prend l'année et le projet de son poste de DA ; à défaut,
    l'année de son échéance et son activité."""
    pd = p.poste_da
    a = pd.annee if pd and pd.annee else (p.date_livraison.year if p.date_livraison else None)
    pr = (pd.projet if pd and pd.projet else None) or p.activite
    return (annee is None or a == annee) and (not projet or pr == projet)


def postes_da_ouverts(sauf_id=None):
    """Postes de DA proposés à l'imputation : ni clos ni supprimés (plus le poste déjà associé)."""
    return [p for p in tous_les_postes_da()
            if p.statut not in ("clos", "supprimé") or p.id == sauf_id]


def marches_ouverts(sauf_id=None):
    """Marchés proposés : non échus et, pour un marché simplifié, sans commande
    (plus le marché déjà associé)."""
    return [m for m in Marche.query.order_by(Marche.reference)
            if m.id == sauf_id or not (m.expire or (m.simplifie and m.commandes))]


def eur(v):
    return f"{v or 0:,.2f} €".replace(",", " ").replace(".", ",")


def controle_commande_unique(marche, sauf_commande=None):
    """Message d'erreur si un marché simplifié a déjà sa commande."""
    if marche is not None and marche.simplifie and any(
            c is not sauf_commande for c in marche.commandes):
        return (f"Le marché {marche.reference} est un marché simplifié : "
                "il comporte déjà sa commande unique.")
    return None


def controle_marche(marche, montant, sauf_poste=None, sauf_commande=None):
    """Message d'erreur si `montant` ajouté au marché dépasse son montant maximal."""
    if marche is None or marche.montant_max is None:
        return None
    total = marche.engage(sauf_poste=sauf_poste, sauf_commande=sauf_commande) + (montant or 0)
    if total > marche.montant_max + 0.005:
        return (f"Montant maximal du marché {marche.reference} dépassé : {eur(total)} engagés "
                f"pour {eur(marche.montant_max)} autorisés "
                f"(reste disponible : {eur(marche.montant_max - total + (montant or 0))}).")
    return None


def alerte_budget(poste_da):
    """Avertit (sans bloquer) si les DA ou les BdC dépassent le budget de la ligne."""
    if poste_da is not None:
        message = budgets.controle(poste_da.code_imputation, poste_da.annee)
        if message:
            flash(message, "warning")


def situations_annee(annee, projet="", alertes=False):
    """Situation des lignes budgétaires pour une année (seulement celles en alerte si demandé)."""
    ag = budgets.agregats()
    s = [budgets.situation(l, annee, ag) for l in budgets.lignes_filtrees(projet)]
    return [x for x in s if x["alertes"]] if alertes else s


def synthese_budgetaire(postes_da):
    """Totaux Valeur / Imputé / Disponible par projet et par année (hors postes supprimés)."""
    totaux = defaultdict(lambda: {"valeur": 0, "impute": 0, "disponible": 0, "nb": 0})
    for p in postes_da:
        if p.statut == "supprimé":
            continue
        t = totaux[(p.projet or "—", p.annee)]
        t["valeur"] += p.montant or 0
        t["impute"] += p.impute
        t["disponible"] += p.disponible
        t["nb"] += 1
    return sorted(totaux.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0))


def enregistrer_routes(app):

    # --- Tableau de bord ------------------------------------------------------

    @app.route("/filtre")
    def filtrer():
        annee = request.args.get("annee", "")
        session["annee"] = int(annee) if annee.isdigit() else None
        session["projet"] = request.args.get("projet", "")
        retour = request.args.get("retour", "")
        return redirect(retour if retour.startswith("/") and not retour.startswith("//")
                        else url_for("accueil"))

    @app.route("/")
    def accueil():
        annee, projet = filtre_courant()
        postes_da = [p for p in tous_les_postes_da() if garder_poste_da(p, annee, projet)]
        postes_cmd = [p for p in PosteCommande.query if garder_poste_cmd(p, annee, projet)]
        actifs = [p for p in postes_da if p.statut not in ("clos", "supprimé")]
        return render_template(
            "accueil.html",
            synthese=synthese_budgetaire(postes_da),
            en_retard=sorted((p for p in postes_cmd if p.en_retard),
                             key=lambda p: p.date_livraison),
            non_imputes=[p for p in actifs if p.impute == 0],
            depassements=[p for p in postes_da if p.statut != "supprimé" and p.disponible < 0],
            en_attente=[c for c in Commande.query.filter(Commande.reference.is_(None))
                        if not c.postes or any(garder_poste_cmd(p, annee, projet)
                                               for p in c.postes)],
            marches_alerte=[m for m in Marche.query.order_by(Marche.reference)
                            if not m.expire and m.taux is not None and m.taux >= 90],
            budgets_alerte=situations_annee(annee or date.today().year, projet, alertes=True),
            annee_budget=annee or date.today().year,
        )

    # --- Demandes d'achat -----------------------------------------------------

    @app.route("/da")
    def liste_da():
        annee, projet = filtre_courant()
        lignes = []
        for da in (DemandeAchat.query
                   .order_by(DemandeAchat.reference.is_(None), DemandeAchat.reference)):
            postes = [p for p in da.postes if garder_poste_da(p, annee, projet)]
            if not postes and da.postes:
                continue  # DA dont aucun poste ne correspond au filtre (une DA vide reste visible)
            comptes = [p for p in postes if p.statut != "supprimé"]
            lignes.append({"da": da, "postes": postes,
                           "valeur": sum(p.montant or 0 for p in comptes),
                           "impute": sum(p.impute for p in comptes),
                           "disponible": sum(p.disponible for p in comptes)})
        return render_template("da_liste.html", lignes=lignes)

    @app.route("/da/nouvelle", methods=["GET", "POST"])
    @app.route("/da/<int:da_id>/modifier", methods=["GET", "POST"])
    def form_da(da_id=None):
        da = db.get_or_404(DemandeAchat, da_id) if da_id else DemandeAchat()
        if request.method == "POST":
            da.reference = champ("reference")
            da.commentaire = champ("commentaire")
            if da_id is None:
                db.session.add(da)
            if enregistrer("DA enregistrée.", f"La DA {da.reference} existe déjà."):
                if da_id is None:
                    return redirect(url_for("form_poste_da", da_id=da.id))
                return redirect(url_for("detail_da", da_id=da.id))
        return render_template("da_form.html", da=da)

    @app.route("/da/<int:da_id>")
    def detail_da(da_id):
        return render_template("da_detail.html", da=db.get_or_404(DemandeAchat, da_id))

    @app.post("/da/<int:da_id>/supprimer")
    def supprimer_da(da_id):
        da = db.get_or_404(DemandeAchat, da_id)
        if any(p.postes_commande for p in da.postes):
            flash("Impossible : des postes de BdC sont rattachés à cette DA. "
                  "Passez plutôt ses postes au statut « supprimé ».", "danger")
            return redirect(url_for("detail_da", da_id=da_id))
        db.session.delete(da)
        db.session.commit()
        flash(f"{da.libelle} supprimée.", "success")
        return redirect(url_for("liste_da"))

    @app.route("/da/<int:da_id>/poste/nouveau", methods=["GET", "POST"])
    @app.route("/poste-da/<int:poste_id>/modifier", methods=["GET", "POST"])
    def form_poste_da(da_id=None, poste_id=None):
        if poste_id:
            poste = db.get_or_404(PosteDA, poste_id)
            da = poste.da
        else:
            da = db.get_or_404(DemandeAchat, da_id)
            dernier = max((p.numero for p in da.postes), default=0)
            precedent = da.postes[-1] if da.postes else None
            # Reprise des valeurs du poste précédent pour accélérer la saisie
            reprise = {c: getattr(precedent, c) if precedent else None
                       for c in ("annee", "projet", "code_imputation", "demandeur",
                                 "certificateur")}
            reprise["annee"] = reprise["annee"] or date.today().year
            poste = PosteDA(numero=dernier + 10, statut="", **reprise)
        suggestions = {"projets": valeurs_distinctes(PosteDA.projet),
                       "centres": sorted(set(valeurs_distinctes(PosteDA.code_imputation))
                                         | set(valeurs_distinctes(LigneBudgetaire.code)))}

        def afficher():
            return render_template("poste_da_form.html", da=da, poste=poste,
                                   statuts=STATUTS_DA, **suggestions)

        if request.method == "POST":
            try:
                poste.numero = champ_entier("numero")
                poste.annee = champ_entier("annee")
                poste.montant = champ_montant("montant")
                poste.date_livraison = champ_date("date_livraison")
            except ValueError:
                flash("Valeur numérique ou date invalide.", "danger")
                return afficher()
            poste.nom = champ("nom")
            poste.projet = champ("projet")
            poste.code_imputation = champ("code_imputation")
            poste.statut = champ("statut") if champ("statut") in STATUTS_DA else ""
            poste.remarque = champ("remarque")
            poste.demandeur = champ("demandeur")
            poste.certificateur = champ("certificateur")
            if poste_id is None:
                da.postes.append(poste)
            if enregistrer("Poste enregistré.", f"Le poste {poste.numero} existe déjà."):
                alerte_budget(poste)
                if "continuer" in request.form:
                    return redirect(url_for("form_poste_da", da_id=da.id))
                return redirect(url_for("detail_da", da_id=da.id))
            da = db.session.get(DemandeAchat, da.id)
        return afficher()

    @app.post("/poste-da/<int:poste_id>/supprimer")
    def supprimer_poste_da(poste_id):
        poste = db.get_or_404(PosteDA, poste_id)
        da_id = poste.da_id
        if poste.postes_commande:
            flash("Impossible : des postes de BdC sont rattachés à ce poste. "
                  "Passez-le plutôt au statut « supprimé ».", "danger")
        else:
            db.session.delete(poste)
            db.session.commit()
            flash("Poste supprimé.", "success")
        return redirect(url_for("detail_da", da_id=da_id))

    @app.route("/postes-da")
    def postes_da():
        annee, projet = filtre_courant()
        return render_template("postes_da.html", postes=[
            p for p in tous_les_postes_da() if garder_poste_da(p, annee, projet)])

    # --- Bons de commande -----------------------------------------------------

    def contexte_nouveau_bdc():
        return {"postes_da": postes_da_ouverts(), "marches": marches_ouverts(),
                "activites": valeurs_distinctes(PosteCommande.activite),
                "societes": valeurs_distinctes(PosteCommande.societe)}

    @app.route("/commandes")
    def liste_commandes():
        # BdC en attente de numéro en tête
        annee, projet = filtre_courant()
        cmds = [c for c in Commande.query.order_by(Commande.reference.isnot(None),
                                                   Commande.reference)
                if not c.postes or any(garder_poste_cmd(p, annee, projet) for p in c.postes)]
        return render_template("cmd_liste.html", cmds=cmds, saisie={},
                               **contexte_nouveau_bdc())

    @app.route("/commandes/nouvelle", methods=["GET", "POST"])
    def nouvelle_commande():
        """Création d'un BdC et de son premier poste, avant que le n° soit connu."""
        if request.method == "GET":
            return render_template("cmd_nouvelle.html", saisie={}, **contexte_nouveau_bdc())
        try:
            montant = champ_montant("montant")
            echeance = champ_date("date_livraison")
            poste_da_id = champ_entier("poste_da_id")
            marche_id = champ_entier("marche_id")
        except ValueError:
            montant = None
            erreur = "Valeur numérique ou date invalide."
        else:
            marche = db.session.get(Marche, marche_id) if marche_id else None
            erreur = controle_commande_unique(marche) or controle_marche(marche, montant)
            if not champ("nom"):
                erreur = "La désignation est obligatoire."
        reference = champ("reference")
        if not erreur and reference and Commande.query.filter_by(reference=reference).first():
            erreur = f"Le BdC {reference} existe déjà."
        if erreur:
            flash(erreur, "danger")
            return render_template("cmd_nouvelle.html", saisie=request.form,
                                   **contexte_nouveau_bdc())
        cmd = Commande(reference=reference, marche=marche, lot=champ("lot") if marche else None,
                       commentaire=champ("commentaire"))
        cmd.postes.append(PosteCommande(
            numero=10, nom=champ("nom"), societe=champ("societe"), activite=champ("activite"),
            montant=montant, date_livraison=echeance, csf=False,
            poste_da=db.session.get(PosteDA, poste_da_id) if poste_da_id else None))
        db.session.add(cmd)
        db.session.commit()
        flash("BdC créé. Envoyez la demande au service achat ; vous saisirez le n° de BdC "
              "quand il vous sera communiqué.", "success")
        alerte_budget(cmd.postes[0].poste_da)
        return redirect(url_for("mail_commande", cmd_id=cmd.id))

    @app.route("/commandes/<int:cmd_id>/modifier", methods=["GET", "POST"])
    def form_commande(cmd_id):
        cmd = db.get_or_404(Commande, cmd_id)
        marches = marches_ouverts(sauf_id=cmd.marche_id)
        if request.method == "POST":
            marche_id = champ_entier("marche_id")
            marche = db.session.get(Marche, marche_id) if marche_id else None
            erreur = (controle_commande_unique(marche, sauf_commande=cmd)
                      or controle_marche(marche, cmd.montant_total, sauf_commande=cmd)
                      if marche is not cmd.marche else None)
            if erreur:
                flash(erreur, "danger")
            else:
                cmd.reference = champ("reference")
                cmd.marche = marche
                cmd.lot = champ("lot") if marche else None
                cmd.commentaire = champ("commentaire")
                if enregistrer("BdC enregistré.", f"Le BdC {champ('reference')} existe déjà."):
                    return redirect(url_for("detail_commande", cmd_id=cmd.id))
                cmd = db.session.get(Commande, cmd_id)
        return render_template("cmd_form.html", cmd=cmd, marches=marches)

    @app.route("/commandes/<int:cmd_id>/mail")
    def mail_commande(cmd_id):
        cmd = db.get_or_404(Commande, cmd_id)
        destinataire, objet, corps = mail.generer(cmd)
        return render_template("cmd_mail.html", cmd=cmd, destinataire=destinataire,
                               objet=objet, corps=corps, contenu=mail.contenu(cmd))

    @app.route("/commandes/<int:cmd_id>")
    def detail_commande(cmd_id):
        return render_template("cmd_detail.html", cmd=db.get_or_404(Commande, cmd_id))

    @app.post("/commandes/<int:cmd_id>/supprimer")
    def supprimer_commande(cmd_id):
        cmd = db.get_or_404(Commande, cmd_id)
        db.session.delete(cmd)
        db.session.commit()
        flash(f"BdC {cmd.libelle} supprimé.", "success")
        return redirect(url_for("liste_commandes"))

    @app.route("/commandes/<int:cmd_id>/poste/nouveau", methods=["GET", "POST"])
    @app.route("/poste-commande/<int:poste_id>/modifier", methods=["GET", "POST"])
    def form_poste_commande(cmd_id=None, poste_id=None):
        if poste_id:
            poste = db.get_or_404(PosteCommande, poste_id)
            cmd = poste.commande
        else:
            cmd = db.get_or_404(Commande, cmd_id)
            dernier = max((p.numero for p in cmd.postes), default=0)
            precedent = cmd.postes[-1] if cmd.postes else None
            # Reprise du fournisseur et de l'activité du poste précédent
            poste = PosteCommande(numero=dernier + 10, csf=False,
                                  societe=(precedent.societe if precedent else None)
                                  or (cmd.marche.titulaire if cmd.marche else None),
                                  activite=precedent.activite if precedent else None)
        postes_da_dispo = postes_da_ouverts(sauf_id=poste.poste_da_id)
        suggestions = {"activites": valeurs_distinctes(PosteCommande.activite),
                       "societes": valeurs_distinctes(PosteCommande.societe)}

        def afficher(csf_coche):
            return render_template("poste_cmd_form.html", cmd=cmd, poste=poste,
                                   postes_da=postes_da_dispo, csf_coche=csf_coche,
                                   **suggestions)

        if request.method == "POST":
            try:
                poste.numero = champ_entier("numero")
                poste.montant = champ_montant("montant")
                poste.date_livraison = champ_date("date_livraison")
                poste_da_id = champ_entier("poste_da_id")
            except ValueError:
                flash("Valeur numérique ou date invalide.", "danger")
                return afficher("csf" in request.form)
            erreur = controle_marche(cmd.marche, poste.montant, sauf_poste=poste)
            if erreur:
                flash(erreur, "danger")
                return afficher("csf" in request.form)
            if poste_da_id and db.session.get(PosteDA, poste_da_id) is None:
                poste_da_id = None
            poste.poste_da_id = poste_da_id
            poste.nom = champ("nom")
            poste.societe = champ("societe")
            poste.activite = champ("activite")
            poste.ptf = champ("ptf")
            poste.csf = "csf" in request.form
            # La référence du livrable justifie la CSF : elle n'existe que si la CSF est faite
            poste.ref_livrable = champ("ref_livrable") if poste.csf else None
            if poste_id is None:
                cmd.postes.append(poste)
            if enregistrer("Poste enregistré.", f"Le poste {poste.numero} existe déjà."):
                alerte_budget(poste.poste_da)
                if "continuer" in request.form:
                    return redirect(url_for("form_poste_commande", cmd_id=cmd.id))
                return redirect(url_for("detail_commande", cmd_id=cmd.id))
            cmd = db.session.get(Commande, cmd.id)
        # ?csf=1 : arrivée depuis le bouton « À faire », la case CSF est pré-cochée
        return afficher(poste.csf or request.args.get("csf") == "1")

    @app.post("/poste-commande/<int:poste_id>/annuler-csf")
    def annuler_csf(poste_id):
        poste = db.get_or_404(PosteCommande, poste_id)
        poste.csf = False
        poste.ref_livrable = None
        db.session.commit()
        return redirect(request.referrer or url_for("detail_commande", cmd_id=poste.commande_id))

    @app.post("/poste-commande/<int:poste_id>/supprimer")
    def supprimer_poste_commande(poste_id):
        poste = db.get_or_404(PosteCommande, poste_id)
        cmd_id = poste.commande_id
        db.session.delete(poste)
        db.session.commit()
        flash("Poste supprimé.", "success")
        return redirect(url_for("detail_commande", cmd_id=cmd_id))

    @app.route("/postes-commande")
    def postes_commande():
        postes = (PosteCommande.query.join(Commande)
                  .order_by(Commande.reference.isnot(None), Commande.reference,
                            PosteCommande.numero).all())
        annee, projet = filtre_courant()
        return render_template("postes_cmd.html", postes=[
            p for p in postes if garder_poste_cmd(p, annee, projet)])

    # --- Marchés ---------------------------------------------------------------

    @app.route("/marches")
    def liste_marches():
        marches = Marche.query.order_by(Marche.date_echeance.is_(None), Marche.date_echeance,
                                        Marche.reference).all()
        return render_template("marche_liste.html", marches=marches)

    @app.route("/marches/nouveau", methods=["GET", "POST"])
    @app.route("/marches/<int:marche_id>/modifier", methods=["GET", "POST"])
    def form_marche(marche_id=None):
        marche = db.get_or_404(Marche, marche_id) if marche_id else Marche()
        titulaires = sorted(set(valeurs_distinctes(Marche.titulaire))
                            | set(valeurs_distinctes(PosteCommande.societe)))
        if request.method == "POST":
            try:
                montant_max = champ_montant("montant_max")
                date_echeance = champ_date("date_echeance")
            except ValueError:
                flash("Valeur numérique ou date invalide.", "danger")
                return render_template("marche_form.html", marche=marche, titulaires=titulaires)
            if marche_id and montant_max is not None and marche.engage() > montant_max + 0.005:
                flash(f"Impossible : {eur(marche.engage())} sont déjà commandés sur ce marché.",
                      "danger")
                return render_template("marche_form.html", marche=marche, titulaires=titulaires)
            marche.reference = champ("reference")
            marche.titulaire = champ("titulaire")
            if marche_id and "simplifie" in request.form and len(marche.commandes) > 1:
                flash("Impossible de passer ce marché en simplifié : il comporte déjà "
                      f"{len(marche.commandes)} commandes.", "danger")
                return render_template("marche_form.html", marche=marche, titulaires=titulaires)
            marche.lots = "; ".join(x.strip() for x in (champ("lots") or "").split(";")
                                    if x.strip()) or None
            marche.simplifie = "simplifie" in request.form
            marche.montant_max = montant_max
            marche.date_echeance = date_echeance
            marche.commentaire = champ("commentaire")
            if marche_id is None:
                db.session.add(marche)
            if enregistrer("Marché enregistré.", f"Le marché {marche.reference} existe déjà."):
                return redirect(url_for("detail_marche", marche_id=marche.id))
            if marche_id:
                marche = db.session.get(Marche, marche_id)
        return render_template("marche_form.html", marche=marche, titulaires=titulaires)

    @app.route("/marches/<int:marche_id>")
    def detail_marche(marche_id):
        marche = db.get_or_404(Marche, marche_id)
        # BdC rattachables : ceux sans marché, ceux du titulaire du marché en premier
        titulaire = (marche.titulaire or "").strip().lower()
        candidats = sorted(Commande.query.filter(Commande.marche_id.is_(None)),
                           key=lambda c: (titulaire not in [s.lower() for s in c.societes],
                                          c.reference is None, c.reference or ""))
        return render_template("marche_detail.html", marche=marche, candidats=candidats)

    @app.post("/marches/<int:marche_id>/rattacher")
    def rattacher_commandes(marche_id):
        marche = db.get_or_404(Marche, marche_id)
        cmds = [c for c in (db.session.get(Commande, i)
                            for i in request.form.getlist("cmd_id", type=int))
                if c is not None and c.marche_id is None]
        if not cmds:
            flash("Cochez au moins un BdC à rattacher.", "warning")
            return redirect(url_for("detail_marche", marche_id=marche_id))
        if marche.simplifie and len(marche.commandes) + len(cmds) > 1:
            erreur = (f"Le marché {marche.reference} est un marché simplifié : "
                      "une seule commande peut y être rattachée.")
        else:
            erreur = controle_marche(marche, sum(c.montant_total for c in cmds))
        if erreur:
            flash(erreur, "danger")
            return redirect(url_for("detail_marche", marche_id=marche_id))
        lot = champ("lot")
        for c in cmds:
            c.marche = marche
            c.lot = lot
        db.session.commit()
        flash(f"{len(cmds)} BdC rattaché(s) au marché {marche.reference}.", "success")
        return redirect(url_for("detail_marche", marche_id=marche_id))

    @app.post("/marches/<int:marche_id>/detacher/<int:cmd_id>")
    def detacher_commande(marche_id, cmd_id):
        cmd = db.get_or_404(Commande, cmd_id)
        if cmd.marche_id == marche_id:
            cmd.marche = None
            cmd.lot = None
            db.session.commit()
            flash(f"BdC {cmd.libelle} détaché du marché.", "success")
        return redirect(url_for("detail_marche", marche_id=marche_id))

    @app.post("/marches/<int:marche_id>/supprimer")
    def supprimer_marche(marche_id):
        marche = db.get_or_404(Marche, marche_id)
        if marche.commandes:
            flash("Impossible : des BdC sont passés sur ce marché.", "danger")
            return redirect(url_for("detail_marche", marche_id=marche_id))
        db.session.delete(marche)
        db.session.commit()
        flash(f"Marché {marche.reference} supprimé.", "success")
        return redirect(url_for("liste_marches"))

    @app.route("/parametres", methods=["GET", "POST"])
    def parametres():
        if request.method == "POST":
            mail.enregistrer_parametres(request.form)
            flash("Paramètres enregistrés.", "success")
            return redirect(url_for("parametres"))
        coffre = app.extensions["coffre"]
        certificats, erreur_certificats = [], None
        if coffre is not None:
            try:
                certificats = protection.certificats_chiffrement()
            except protection.ErreurProtection as e:
                erreur_certificats = str(e)
        return render_template("parametres.html", definitions=mail.PARAMETRES,
                               valeurs=mail.parametres(), protection_disponible=coffre is not None,
                               protege=app.config["PROTEGE"], certificats=certificats,
                               erreur_certificats=erreur_certificats,
                               enveloppes=coffre.enveloppes() if coffre else [])

    # --- Budgets ---------------------------------------------------------------

    @app.route("/budgets")
    def liste_budgets():
        annee, projet = filtre_courant()
        annee = annee or date.today().year
        lignes = budgets.lignes_filtrees(projet)
        ag = budgets.agregats()
        annees = budgets.annees_affichees()
        return render_template(
            "budget_liste.html", annee=annee, annees=annees,
            situations=[budgets.situation(l, annee, ag) for l in lignes],
            matrice=[(l, [budgets.situation(l, a, ag) for a in annees]) for l in lignes],
            orphelins=budgets.codes_sans_ligne(annee), types=TYPES_BUDGET)

    @app.route("/budgets/lignes/nouvelle", methods=["GET", "POST"])
    @app.route("/budgets/lignes/<int:ligne_id>/modifier", methods=["GET", "POST"])
    def form_ligne_budget(ligne_id=None):
        ligne = db.get_or_404(LigneBudgetaire, ligne_id) if ligne_id else LigneBudgetaire(
            code=request.args.get("code"), type="structure")
        if request.method == "POST":
            ligne.code = champ("code")
            ligne.libelle = champ("libelle")
            ligne.type = champ("type") if champ("type") in TYPES_BUDGET else "structure"
            ligne.projet = champ("projet")
            ligne.commentaire = champ("commentaire")
            if ligne_id is None:
                db.session.add(ligne)
            if enregistrer("Ligne budgétaire enregistrée.",
                           f"La ligne budgétaire {ligne.code} existe déjà."):
                return redirect(url_for("detail_ligne_budget", ligne_id=ligne.id))
            if ligne_id:
                ligne = db.session.get(LigneBudgetaire, ligne_id)
        return render_template("budget_ligne_form.html", ligne=ligne, types=TYPES_BUDGET,
                               projets=valeurs_distinctes(PosteDA.projet))

    @app.route("/budgets/lignes/<int:ligne_id>")
    def detail_ligne_budget(ligne_id):
        ligne = db.get_or_404(LigneBudgetaire, ligne_id)
        ag = budgets.agregats()
        annees = sorted({b.annee for b in ligne.annees}
                        | {p.annee for p in PosteDA.query if p.annee
                           and budgets.cle(p.code_imputation) == budgets.cle(ligne.code)}
                        | {date.today().year})
        postes = [p for p in tous_les_postes_da()
                  if budgets.cle(p.code_imputation) == budgets.cle(ligne.code)]
        return render_template("budget_ligne_detail.html", ligne=ligne, types=TYPES_BUDGET,
                               situations=[budgets.situation(ligne, a, ag) for a in annees],
                               postes=sorted(postes, key=lambda p: (-(p.annee or 0), p.cle)),
                               annee_suivante=date.today().year + 1)

    @app.post("/budgets/lignes/<int:ligne_id>/supprimer")
    def supprimer_ligne_budget(ligne_id):
        ligne = db.get_or_404(LigneBudgetaire, ligne_id)
        db.session.delete(ligne)
        db.session.commit()
        flash(f"Ligne budgétaire {ligne.code} supprimée (les DA ne sont pas modifiées).", "success")
        return redirect(url_for("liste_budgets"))

    @app.post("/budgets/lignes/<int:ligne_id>/annee")
    def enregistrer_budget_annuel(ligne_id):
        """Ajout ou mise à jour du budget d'une année (demande, allocation, report)."""
        ligne = db.get_or_404(LigneBudgetaire, ligne_id)
        try:
            annee = champ_entier("annee")
            valeurs = {c: champ_montant(c) for c in ("montant_demande", "montant_alloue", "report")}
        except ValueError:
            flash("Valeur numérique invalide.", "danger")
            return redirect(url_for("detail_ligne_budget", ligne_id=ligne_id))
        if not annee:
            flash("Indiquez l'année.", "danger")
            return redirect(url_for("detail_ligne_budget", ligne_id=ligne_id))
        b = ligne.budget(annee)
        if b is None:
            b = BudgetAnnuel(annee=annee)
            ligne.annees.append(b)
        for c, v in valeurs.items():
            setattr(b, c, v)
        b.commentaire = champ("commentaire")
        db.session.commit()
        flash(f"Budget {annee} de la ligne {ligne.code} enregistré.", "success")
        return redirect(url_for("detail_ligne_budget", ligne_id=ligne_id))

    @app.post("/budgets/annuel/<int:budget_id>/supprimer")
    def supprimer_budget_annuel(budget_id):
        b = db.get_or_404(BudgetAnnuel, budget_id)
        ligne_id = b.ligne_id
        db.session.delete(b)
        db.session.commit()
        flash(f"Budget {b.annee} supprimé.", "success")
        return redirect(url_for("detail_ligne_budget", ligne_id=ligne_id))

    @app.post("/budgets/lignes/<int:ligne_id>/reporter/<int:annee>")
    def reporter_budget(ligne_id, annee):
        """Report du disponible de l'année sur l'année suivante (lignes projet)."""
        ligne = db.get_or_404(LigneBudgetaire, ligne_id)
        s = budgets.situation(ligne, annee)
        if not ligne.reportable or s["budget"] is None or s["disponible"] <= 0:
            flash("Rien à reporter.", "warning")
        else:
            suivant = ligne.budget(annee + 1)
            if suivant is None:
                suivant = BudgetAnnuel(annee=annee + 1)
                ligne.annees.append(suivant)
            suivant.report = round(s["disponible"], 2)
            db.session.commit()
            flash(f"{eur(s['disponible'])} reportés de {annee} sur {annee + 1}.", "success")
        return redirect(url_for("detail_ligne_budget", ligne_id=ligne_id))

    # --- Excel ----------------------------------------------------------------

    @app.route("/import", methods=["GET", "POST"])
    def import_excel():
        erreurs = None
        if request.method == "POST":
            fichier = request.files.get("fichier")
            if not fichier or not fichier.filename:
                flash("Choisissez un fichier .xlsx.", "danger")
                return redirect(url_for("import_excel"))
            try:
                nb_da, nb_cmd, erreurs, onglets = excel_io.importer(
                    fichier, vider="vider" in request.form,
                    avec_referentiels="avec_referentiels" in request.form)
            except Exception as e:  # fichier illisible, onglets absents...
                db.session.rollback()
                flash(f"Import impossible : {e}", "danger")
                return redirect(url_for("import_excel"))
            flash(f"Import terminé : {nb_da} poste(s) de DA, {nb_cmd} poste(s) de BdC "
                  f"(onglets lus : {', '.join(f'« {o} »' for o in onglets)} ; "
                  "les autres onglets sont ignorés).",
                  "success" if not erreurs else "warning")
        return render_template("import.html", erreurs=erreurs,
                               colonnes_da=excel_io.COLONNES_DA,
                               colonnes_cmd=excel_io.COLONNES_CMD,
                               colonnes_marche=excel_io.COLONNES_MARCHE)

    @app.route("/export")
    def export_excel():
        return send_file(excel_io.exporter(), as_attachment=True,
                         download_name=f"Budgets_{date.today():%Y%m%d}.xlsx")

    @app.post("/arreter")
    def arreter():
        """Arrête l'application (utile quand elle tourne en arrière-plan, sans fenêtre)."""
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return render_template("erreur.html", message="L'application est arrêtée. Pour la relancer : "
                               "lancer.bat, ou ouvrir une nouvelle session Windows si le démarrage "
                               "automatique est activé.")

    @app.errorhandler(404)
    def introuvable(_):
        return render_template("erreur.html", message="Page introuvable."), 404


def port_occupe(port):
    """Vrai si l'application (ou un autre programme) écoute déjà sur ce port."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def sauvegarde_quotidienne(dossier_donnees=DOSSIER_DONNEES):
    """Copie de la base une fois par jour dans donnees/sauvegardes (30 dernières gardées).
    Base protégée : c'est le fichier chiffré qui est copié."""
    base = os.path.join(dossier_donnees, "achats.db")
    chiffre = base + ".chiffre"
    dossier = os.path.join(dossier_donnees, "sauvegardes")
    os.makedirs(dossier, exist_ok=True)
    cible = os.path.join(dossier, f"achats_{date.today():%Y%m%d}.db")
    if os.path.exists(chiffre):
        if not os.path.exists(cible + ".chiffre"):
            shutil.copy2(chiffre, cible + ".chiffre")
    elif os.path.exists(base) and not os.path.exists(cible):
        source, copie = sqlite3.connect(base), sqlite3.connect(cible)
        source.backup(copie)  # copie cohérente même si la base est en cours d'utilisation
        copie.close()
        source.close()
    for extension in (".db", ".db.chiffre"):
        modele = os.path.join(dossier, "achats_" + "[0-9]" * 8 + extension)
        for ancienne in sorted(glob.glob(modele))[:-SAUVEGARDES_GARDEES]:
            os.remove(ancienne)


def journaliser_dans_fichier():
    """Sans fenêtre (pythonw), les messages et erreurs vont dans donnees/application.log."""
    os.makedirs(DOSSIER_DONNEES, exist_ok=True)
    if os.path.exists(FICHIER_JOURNAL) and os.path.getsize(FICHIER_JOURNAL) > 5_000_000:
        os.replace(FICHIER_JOURNAL, FICHIER_JOURNAL + ".1")
    journal = open(FICHIER_JOURNAL, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = journal
    print(f"--- Démarrage {datetime.now():%d/%m/%Y %H:%M:%S}")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # pas une ligne par page vue


if __name__ == "__main__":
    # --arriere-plan : lancement automatique à l'ouverture de session, sans ouvrir le navigateur
    arriere_plan = "--arriere-plan" in sys.argv
    port = int(os.environ.get("PORT", 5000))
    url = f"http://127.0.0.1:{port}"
    relance = "--relance" in sys.argv
    if relance:  # redémarrage demandé par l'application : attendre que l'ancienne soit arrêtée
        for _ in range(30):
            if not port_occupe(port):
                break
            threading.Event().wait(0.5)
    if port_occupe(port):
        # Déjà lancée : on se contente d'ouvrir le navigateur
        if not arriere_plan:
            webbrowser.open(url)
        sys.exit(0)
    if arriere_plan or sys.stdout is None:  # sys.stdout est None avec pythonw.exe
        journaliser_dans_fichier()
    if not arriere_plan and not relance and not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    application = create_app()
    application.config["RELANCE_POSSIBLE"] = True
    try:
        sauvegarde_quotidienne()
    except Exception as e:  # une sauvegarde ratée ne doit pas empêcher le démarrage
        print(f"Sauvegarde quotidienne impossible : {e}")
    # Un seul traitement à la fois : la base protégée est une connexion unique en mémoire
    application.run(host="127.0.0.1", port=port, debug=False, threaded=False)
