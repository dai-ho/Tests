"""Gestion des Demandes d'Achat et des Bons de Commande — application web locale."""
import os
import shutil
import sqlite3
import threading
import webbrowser
from collections import defaultdict
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import excel_io
import mail
import regles
from models import STATUTS_DA, Commande, DemandeAchat, Marche, PosteCommande, PosteDA, db

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_DONNEES = os.path.join(DOSSIER, "donnees")
FICHIER_BASE = os.path.join(DOSSIER_DONNEES, "achats.db")


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


def create_app(db_uri=None):
    app = Flask(__name__)
    os.makedirs(DOSSIER_DONNEES, exist_ok=True)
    if db_uri is None:
        mettre_de_cote_base_obsolete(FICHIER_BASE)
        db_uri = "sqlite:///" + FICHIER_BASE
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["SECRET_KEY"] = "application-locale"
    db.init_app(app)
    with app.app_context():
        db.create_all()
        migrer()

    @app.template_filter("euros")
    def euros(v):
        if v is None:
            return ""
        return f"{v:,.2f} €".replace(",", " ").replace(".", ",")

    @app.template_filter("saisie")
    def saisie(v):
        """Montant pour un champ de formulaire : 24000 ou 1500,5."""
        if v is None:
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

    enregistrer_routes(app)
    return app


# --- Lecture des formulaires -------------------------------------------------

def champ(nom):
    v = request.form.get(nom, "").strip()
    return v or None


def champ_entier(nom):
    v = champ(nom)
    return int(v) if v else None


def champ_montant(nom):
    v = champ(nom)
    return float(v.replace(" ", "").replace("€", "").replace(",", ".")) if v else None


def champ_date(nom):
    v = champ(nom)
    return datetime.strptime(v, "%Y-%m-%d").date() if v else None


def enregistrer(message_ok, message_doublon):
    try:
        db.session.commit()
        flash(message_ok, "success")
        return True
    except IntegrityError:
        db.session.rollback()
        flash(message_doublon, "danger")
        return False


def tous_les_postes_da():
    return (PosteDA.query.join(DemandeAchat)
            .order_by(DemandeAchat.reference.is_(None), DemandeAchat.reference,
                      PosteDA.numero).all())


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


def valeurs_distinctes(colonne):
    """Valeurs déjà saisies, proposées en suggestion dans les formulaires."""
    return [v for (v,) in db.session.query(colonne).distinct().order_by(colonne) if v]


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

    @app.route("/")
    def accueil():
        postes_da = tous_les_postes_da()
        postes_cmd = PosteCommande.query.all()
        actifs = [p for p in postes_da if p.statut not in ("clos", "supprimé")]
        return render_template(
            "accueil.html",
            synthese=synthese_budgetaire(postes_da),
            en_retard=sorted((p for p in postes_cmd if p.en_retard),
                             key=lambda p: p.date_livraison),
            non_imputes=[p for p in actifs if p.impute == 0],
            depassements=[p for p in postes_da if p.statut != "supprimé" and p.disponible < 0],
            en_attente=Commande.query.filter(Commande.reference.is_(None)).all(),
            marches_alerte=[m for m in Marche.query.order_by(Marche.reference)
                            if not m.expire and m.taux is not None and m.taux >= 90],
        )

    # --- Demandes d'achat -----------------------------------------------------

    @app.route("/da")
    def liste_da():
        das = (DemandeAchat.query
               .order_by(DemandeAchat.reference.is_(None), DemandeAchat.reference).all())
        return render_template("da_liste.html", das=das)

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
                       "centres": valeurs_distinctes(PosteDA.code_imputation)}

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
        return render_template("postes_da.html", postes=tous_les_postes_da())

    # --- Bons de commande -----------------------------------------------------

    def contexte_nouveau_bdc():
        return {"postes_da": postes_da_ouverts(), "marches": marches_ouverts(),
                "activites": valeurs_distinctes(PosteCommande.activite),
                "societes": valeurs_distinctes(PosteCommande.societe)}

    @app.route("/commandes")
    def liste_commandes():
        # BdC en attente de numéro en tête
        cmds = Commande.query.order_by(Commande.reference.isnot(None), Commande.reference).all()
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
        return render_template("postes_cmd.html", postes=postes)

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
        return render_template("parametres.html", definitions=mail.PARAMETRES,
                               valeurs=mail.parametres())

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
                    avec_marches="avec_marches" in request.form)
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

    @app.errorhandler(404)
    def introuvable(_):
        return render_template("erreur.html", message="Page introuvable."), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    create_app().run(host="127.0.0.1", port=port, debug=False)
