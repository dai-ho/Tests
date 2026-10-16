"""Gestion des Demandes d'Achat et des Bons de Commande — application web locale."""
import os
import shutil
import sqlite3
import threading
import webbrowser
from collections import defaultdict
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy.exc import IntegrityError

import excel_io
import regles
from models import STATUTS_DA, Commande, DemandeAchat, PosteCommande, PosteDA, db

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_DONNEES = os.path.join(DOSSIER, "donnees")
FICHIER_BASE = os.path.join(DOSSIER_DONNEES, "achats.db")
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def mettre_de_cote_base_obsolete(chemin):
    """Une base créée par une version précédente (sans les colonnes du fichier
    Budgets GT) est renommée : une base neuve est créée, à remplir par import Excel."""
    if not os.path.exists(chemin):
        return
    with sqlite3.connect(chemin) as cnx:
        colonnes = {ligne[1] for ligne in cnx.execute("PRAGMA table_info(poste_da)")}
    if colonnes and "annee" not in colonnes:
        shutil.move(chemin, chemin.replace(".db", f"_ancienne_{datetime.now():%Y%m%d_%H%M%S}.db"))


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
        )

    @app.route("/planning")
    def planning():
        """Montants des postes de BdC par activité et par mois d'échéance
        (équivalent de la colonne Excel « Activité:mois:année »)."""
        postes = PosteCommande.query.filter(PosteCommande.date_livraison.isnot(None)).all()
        annees = sorted({p.date_livraison.year for p in postes}) or [date.today().year]
        annee = request.args.get("annee", type=int) or (
            date.today().year if date.today().year in annees else annees[-1])
        tableau = defaultdict(lambda: [0.0] * 12)
        for p in postes:
            if p.date_livraison.year == annee:
                tableau[p.activite or "—"][p.date_livraison.month - 1] += p.montant or 0
        totaux_mois = [sum(ligne[m] for ligne in tableau.values()) for m in range(12)]
        return render_template("planning.html", annees=annees, annee=annee, mois=MOIS,
                               tableau=sorted(tableau.items()), totaux_mois=totaux_mois)

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
                poste.budget = champ_montant("budget")
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

    @app.route("/commandes")
    def liste_commandes():
        cmds = Commande.query.order_by(Commande.reference).all()
        return render_template("cmd_liste.html", cmds=cmds)

    @app.route("/commandes/nouvelle", methods=["GET", "POST"])
    @app.route("/commandes/<int:cmd_id>/modifier", methods=["GET", "POST"])
    def form_commande(cmd_id=None):
        cmd = db.get_or_404(Commande, cmd_id) if cmd_id else Commande()
        societes = valeurs_distinctes(Commande.societe)
        if request.method == "POST":
            cmd.reference = champ("reference")
            cmd.societe = champ("societe")
            cmd.commentaire = champ("commentaire")
            if cmd_id is None:
                db.session.add(cmd)
            if enregistrer("BdC enregistré.", f"Le BdC {cmd.reference} existe déjà."):
                if cmd_id is None:
                    return redirect(url_for("form_poste_commande", cmd_id=cmd.id))
                return redirect(url_for("detail_commande", cmd_id=cmd.id))
        return render_template("cmd_form.html", cmd=cmd, societes=societes)

    @app.route("/commandes/<int:cmd_id>")
    def detail_commande(cmd_id):
        return render_template("cmd_detail.html", cmd=db.get_or_404(Commande, cmd_id))

    @app.post("/commandes/<int:cmd_id>/supprimer")
    def supprimer_commande(cmd_id):
        cmd = db.get_or_404(Commande, cmd_id)
        db.session.delete(cmd)
        db.session.commit()
        flash(f"BdC {cmd.reference} supprimé.", "success")
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
            poste = PosteCommande(numero=dernier + 10, csf=False,
                                  activite=precedent.activite if precedent else None)
        # Postes de DA proposés : ceux ni clos ni supprimés, plus le poste déjà associé
        postes_da_dispo = [p for p in tous_les_postes_da()
                           if p.statut not in ("clos", "supprimé") or p.id == poste.poste_da_id]
        activites = valeurs_distinctes(PosteCommande.activite)

        def afficher(csf_coche):
            return render_template("poste_cmd_form.html", cmd=cmd, poste=poste,
                                   postes_da=postes_da_dispo, activites=activites,
                                   csf_coche=csf_coche)

        if request.method == "POST":
            try:
                poste.numero = champ_entier("numero")
                poste.montant = champ_montant("montant")
                poste.date_livraison = champ_date("date_livraison")
                poste_da_id = champ_entier("poste_da_id")
            except ValueError:
                flash("Valeur numérique ou date invalide.", "danger")
                return afficher("csf" in request.form)
            if poste_da_id and db.session.get(PosteDA, poste_da_id) is None:
                poste_da_id = None
            poste.poste_da_id = poste_da_id
            poste.nom = champ("nom")
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
                  .order_by(Commande.reference, PosteCommande.numero).all())
        return render_template("postes_cmd.html", postes=postes)

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
                nb_da, nb_cmd, erreurs = excel_io.importer(fichier, vider="vider" in request.form)
            except Exception as e:  # fichier illisible, onglets absents...
                db.session.rollback()
                flash(f"Import impossible : {e}", "danger")
                return redirect(url_for("import_excel"))
            flash(f"Import terminé : {nb_da} poste(s) de DA, {nb_cmd} poste(s) de BdC.",
                  "success" if not erreurs else "warning")
        return render_template("import.html", erreurs=erreurs,
                               colonnes_da=excel_io.COLONNES_DA,
                               colonnes_cmd=excel_io.COLONNES_CMD)

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
