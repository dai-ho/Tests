"""Gestion des Demandes d'Achat et des Commandes — application web locale."""
import os
import threading
import webbrowser
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy.exc import IntegrityError

import excel_io
import regles
from models import Commande, DemandeAchat, PosteCommande, PosteDA, db

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_DONNEES = os.path.join(DOSSIER, "donnees")


def create_app(db_uri=None):
    app = Flask(__name__)
    os.makedirs(DOSSIER_DONNEES, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri or "sqlite:///" + os.path.join(
        DOSSIER_DONNEES, "achats.db")
    app.config["SECRET_KEY"] = "application-locale"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    @app.template_filter("euros")
    def euros(v):
        if v is None:
            return ""
        return f"{v:,.2f} €".replace(",", " ").replace(".", ",")

    @app.template_filter("date_fr")
    def date_fr(d):
        return d.strftime("%d/%m/%Y") if d else ""

    @app.context_processor
    def contexte():
        return {"couleur_da": regles.couleur_poste_da,
                "couleur_cmd": regles.couleur_poste_commande,
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
    return float(v.replace(" ", "").replace(",", ".")) if v else None


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


def enregistrer_routes(app):

    # --- Tableau de bord ------------------------------------------------------

    @app.route("/")
    def accueil():
        postes_cmd = PosteCommande.query.all()
        postes_da = PosteDA.query.all()
        return render_template(
            "accueil.html",
            nb_da=DemandeAchat.query.count(),
            nb_cmd=Commande.query.count(),
            montant_total=sum(p.montant or 0 for p in postes_da),
            a_certifier=[p for p in postes_cmd if not p.csf],
            en_retard=[p for p in postes_cmd if p.en_retard],
            da_sans_commande=[p for p in postes_da if not p.postes_commande],
        )

    # --- Demandes d'achat -----------------------------------------------------

    @app.route("/da")
    def liste_da():
        das = DemandeAchat.query.order_by(DemandeAchat.reference).all()
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
                return redirect(url_for("detail_da", da_id=da.id))
        return render_template("da_form.html", da=da)

    @app.route("/da/<int:da_id>")
    def detail_da(da_id):
        return render_template("da_detail.html", da=db.get_or_404(DemandeAchat, da_id))

    @app.post("/da/<int:da_id>/supprimer")
    def supprimer_da(da_id):
        da = db.get_or_404(DemandeAchat, da_id)
        if any(p.postes_commande for p in da.postes):
            flash("Impossible : des postes de commande sont rattachés à cette DA.", "danger")
            return redirect(url_for("detail_da", da_id=da_id))
        db.session.delete(da)
        db.session.commit()
        flash(f"DA {da.reference} supprimée.", "success")
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
            poste = PosteDA(
                numero=dernier + 10,
                # Reprise des valeurs du poste précédent pour accélérer la saisie
                code_imputation=precedent.code_imputation if precedent else None,
                demandeur=precedent.demandeur if precedent else None,
                certificateur=precedent.certificateur if precedent else None,
            )
        if request.method == "POST":
            try:
                poste.numero = champ_entier("numero")
                poste.nom = champ("nom")
                poste.montant = champ_montant("montant")
                poste.date_livraison = champ_date("date_livraison")
            except ValueError:
                flash("Valeur numérique ou date invalide.", "danger")
                return render_template("poste_da_form.html", da=da, poste=poste)
            poste.code_imputation = champ("code_imputation")
            poste.demandeur = champ("demandeur")
            poste.certificateur = champ("certificateur")
            if poste_id is None:
                da.postes.append(poste)
            if enregistrer("Poste enregistré.", f"Le poste {poste.numero} existe déjà."):
                if "continuer" in request.form:
                    return redirect(url_for("form_poste_da", da_id=da.id))
                return redirect(url_for("detail_da", da_id=da.id))
            da = db.session.get(DemandeAchat, da.id)
        return render_template("poste_da_form.html", da=da, poste=poste)

    @app.post("/poste-da/<int:poste_id>/supprimer")
    def supprimer_poste_da(poste_id):
        poste = db.get_or_404(PosteDA, poste_id)
        da_id = poste.da_id
        if poste.postes_commande:
            flash("Impossible : des postes de commande sont rattachés à ce poste.", "danger")
        else:
            db.session.delete(poste)
            db.session.commit()
            flash("Poste supprimé.", "success")
        return redirect(url_for("detail_da", da_id=da_id))

    @app.route("/postes-da")
    def postes_da():
        postes = (PosteDA.query.join(DemandeAchat)
                  .order_by(DemandeAchat.reference, PosteDA.numero).all())
        return render_template("postes_da.html", postes=postes)

    # --- Commandes ------------------------------------------------------------

    @app.route("/commandes")
    def liste_commandes():
        cmds = Commande.query.order_by(Commande.reference).all()
        return render_template("cmd_liste.html", cmds=cmds)

    @app.route("/commandes/nouvelle", methods=["GET", "POST"])
    @app.route("/commandes/<int:cmd_id>/modifier", methods=["GET", "POST"])
    def form_commande(cmd_id=None):
        cmd = db.get_or_404(Commande, cmd_id) if cmd_id else Commande()
        if request.method == "POST":
            cmd.reference = champ("reference")
            cmd.commentaire = champ("commentaire")
            if cmd_id is None:
                db.session.add(cmd)
            if enregistrer("Commande enregistrée.",
                           f"La commande {cmd.reference} existe déjà."):
                return redirect(url_for("detail_commande", cmd_id=cmd.id))
        return render_template("cmd_form.html", cmd=cmd)

    @app.route("/commandes/<int:cmd_id>")
    def detail_commande(cmd_id):
        return render_template("cmd_detail.html", cmd=db.get_or_404(Commande, cmd_id))

    @app.post("/commandes/<int:cmd_id>/supprimer")
    def supprimer_commande(cmd_id):
        cmd = db.get_or_404(Commande, cmd_id)
        db.session.delete(cmd)
        db.session.commit()
        flash(f"Commande {cmd.reference} supprimée.", "success")
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
            poste = PosteCommande(numero=dernier + 10, csf=False)
            # Pré-sélection d'un poste de DA passé en paramètre (?poste_da=ID)
            poste_da = request.args.get("poste_da", type=int)
            poste_da = db.session.get(PosteDA, poste_da) if poste_da else None
            if poste_da and request.method == "GET":
                poste.poste_da_id = poste_da.id
                poste.nom = poste_da.nom
                poste.date_livraison = poste_da.date_livraison
        postes_da_dispo = (PosteDA.query.join(DemandeAchat)
                           .order_by(DemandeAchat.reference, PosteDA.numero).all())
        if request.method == "POST":
            try:
                poste.numero = champ_entier("numero")
                poste.date_livraison = champ_date("date_livraison")
                poste_da_id = champ_entier("poste_da_id")
            except ValueError:
                flash("Valeur numérique ou date invalide.", "danger")
                return render_template("poste_cmd_form.html", cmd=cmd, poste=poste,
                                       postes_da=postes_da_dispo)
            if poste_da_id and db.session.get(PosteDA, poste_da_id) is None:
                poste_da_id = None
            poste.poste_da_id = poste_da_id
            poste.nom = champ("nom")
            poste.csf = "csf" in request.form
            poste.ref_livrable = champ("ref_livrable")
            poste.ptf = champ("ptf")
            if poste_id is None:
                cmd.postes.append(poste)
            if enregistrer("Poste enregistré.", f"Le poste {poste.numero} existe déjà."):
                if "continuer" in request.form:
                    return redirect(url_for("form_poste_commande", cmd_id=cmd.id))
                return redirect(url_for("detail_commande", cmd_id=cmd.id))
            cmd = db.session.get(Commande, cmd.id)
        return render_template("poste_cmd_form.html", cmd=cmd, poste=poste,
                               postes_da=postes_da_dispo)

    @app.post("/poste-commande/<int:poste_id>/csf")
    def basculer_csf(poste_id):
        poste = db.get_or_404(PosteCommande, poste_id)
        poste.csf = not poste.csf
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
        if request.method == "POST":
            fichier = request.files.get("fichier")
            if not fichier or not fichier.filename:
                flash("Choisissez un fichier .xlsx.", "danger")
                return redirect(url_for("import_excel"))
            try:
                nb_da, nb_cmd, erreurs = excel_io.importer(fichier, vider="vider" in request.form)
            except Exception as e:  # fichier illisible, feuilles absentes...
                db.session.rollback()
                flash(f"Import impossible : {e}", "danger")
                return redirect(url_for("import_excel"))
            flash(f"Import terminé : {nb_da} poste(s) de DA, {nb_cmd} poste(s) de commande.",
                  "success" if not erreurs else "warning")
            return render_template("import.html", erreurs=erreurs,
                                   colonnes_da=excel_io.COLONNES_DA,
                                   colonnes_cmd=excel_io.COLONNES_CMD)
        return render_template("import.html", erreurs=None,
                               colonnes_da=excel_io.COLONNES_DA,
                               colonnes_cmd=excel_io.COLONNES_CMD)

    @app.route("/export")
    def export_excel():
        return send_file(excel_io.exporter(), as_attachment=True,
                         download_name=f"achats_{date.today():%Y%m%d}.xlsx")

    @app.errorhandler(404)
    def introuvable(_):
        return render_template("erreur.html", message="Page introuvable."), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    create_app().run(host="127.0.0.1", port=port, debug=False)
