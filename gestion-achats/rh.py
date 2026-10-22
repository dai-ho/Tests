"""Gestion RH de l'équipe : fiches, compétences, points forts / axes de progrès,
plan de charge (en ETP) par projet / activité et par année, formations."""
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from formulaires import (champ, champ_date, champ_entier, champ_montant, enregistrer,
                         filtre_courant, valeurs_distinctes)
from models import (NIVEAUX, STATUTS_AGENT, STATUTS_FORMATION, TYPES_APPRECIATION, Affectation,
                    Agent, Appreciation, Competence, Formation, LigneBudgetaire, NiveauCompetence,
                    PosteDA, db)

bp = Blueprint("rh", __name__, url_prefix="/rh")

# Seuils du plan de charge (écart entre la charge planifiée et la quotité de l'agent)
TOLERANCE_SURCHARGE = 0.05
SEUIL_SOUS_CHARGE = 0.1
# Une compétence est « à risque » si moins de 2 personnes la maîtrisent (niveau ≥ 3)
NIVEAU_MAITRISE = 3
MINIMUM_MAITRISES = 2


def annee_courante():
    annee, _ = filtre_courant()
    return annee or date.today().year


def agents_actifs():
    return [a for a in Agent.query.order_by(Agent.nom, Agent.prenom) if a.actif]


def projets_connus():
    """Projets / activités proposés : ceux des affectations, des DA et des budgets."""
    return sorted(set(valeurs_distinctes(Affectation.projet)) | set(valeurs_distinctes(PosteDA.projet))
                  | set(valeurs_distinctes(LigneBudgetaire.projet)))


def ecart_charge(agent, annee):
    """« surcharge », « sous-charge » ou None."""
    ecart = agent.charge(annee) - (agent.etp or 0)
    if ecart > TOLERANCE_SURCHARGE:
        return "surcharge"
    if ecart < -SEUIL_SOUS_CHARGE:
        return "sous-charge"
    return None


def competences_a_risque(agents):
    """Compétences maîtrisées (niveau ≥ 3) par moins de 2 personnes de l'équipe active."""
    resultat = []
    for c in Competence.query.order_by(Competence.domaine, Competence.nom):
        maitres = [a for a in agents if a.niveau(c.id) >= NIVEAU_MAITRISE]
        if len(maitres) < MINIMUM_MAITRISES:
            resultat.append((c, maitres))
    return resultat


def obtenir_agent(agent_id):
    return db.get_or_404(Agent, agent_id)


# --- Équipe -----------------------------------------------------------------------

@bp.route("/")
def equipe():
    annee = annee_courante()
    agents = Agent.query.order_by(Agent.nom, Agent.prenom).all()
    actifs = [a for a in agents if a.actif]
    prochainement = date.today() + timedelta(days=90)
    return render_template(
        "rh_equipe.html", annee=annee, agents=agents, actifs=actifs,
        capacite=sum(a.etp or 0 for a in actifs),
        charge=sum(a.charge(annee) for a in actifs),
        ecarts={a.id: ecart_charge(a, annee) for a in actifs},
        a_risque=competences_a_risque(actifs),
        formations_prevues=Formation.query.filter(
            Formation.statut == "prévue", Formation.date_debut <= prochainement)
        .order_by(Formation.date_debut).all(),
    )


@bp.route("/agents/nouveau", methods=["GET", "POST"])
@bp.route("/agents/<int:agent_id>/modifier", methods=["GET", "POST"])
def form_agent(agent_id=None):
    agent = obtenir_agent(agent_id) if agent_id else Agent(etp=1.0)
    if request.method == "POST":
        try:
            etp = champ_montant("etp")
            date_arrivee, date_depart = champ_date("date_arrivee"), champ_date("date_depart")
        except ValueError:
            flash("Quotité ou date invalide.", "danger")
            return render_template("rh_agent_form.html", agent=agent, statuts=STATUTS_AGENT)
        agent.nom, agent.prenom = champ("nom"), champ("prenom")
        agent.fonction, agent.statut, agent.email = champ("fonction"), champ("statut"), champ("email")
        agent.etp = 1.0 if etp is None else etp
        agent.date_arrivee, agent.date_depart = date_arrivee, date_depart
        agent.commentaire = champ("commentaire")
        if agent_id is None:
            db.session.add(agent)
        db.session.commit()
        flash(f"Fiche de {agent.nom_complet} enregistrée.", "success")
        return redirect(url_for("rh.fiche_agent", agent_id=agent.id))
    return render_template("rh_agent_form.html", agent=agent, statuts=STATUTS_AGENT)


@bp.route("/agents/<int:agent_id>")
def fiche_agent(agent_id):
    agent = obtenir_agent(agent_id)
    annee = annee_courante()
    competences = Competence.query.order_by(Competence.domaine, Competence.nom).all()
    return render_template(
        "rh_agent.html", agent=agent, annee=annee, ecart=ecart_charge(agent, annee),
        competences=competences, niveaux=NIVEAUX, types=TYPES_APPRECIATION,
        statuts_formation=STATUTS_FORMATION, projets=projets_connus(),
        annees=sorted({a.annee for a in agent.affectations} | {annee, annee + 1}, reverse=True),
        aujourdhui=date.today())


@bp.post("/agents/<int:agent_id>/supprimer")
def supprimer_agent(agent_id):
    agent = obtenir_agent(agent_id)
    db.session.delete(agent)
    db.session.commit()
    flash(f"Fiche de {agent.nom_complet} supprimée (avec ses compétences, affectations et "
          "formations).", "success")
    return redirect(url_for("rh.equipe"))


@bp.post("/agents/<int:agent_id>/competences")
def enregistrer_competences(agent_id):
    """Niveaux de toutes les compétences de l'agent, en une fois (0 = non renseigné)."""
    agent = obtenir_agent(agent_id)
    existants = {n.competence_id: n for n in agent.competences}
    for c in Competence.query:
        niveau = request.form.get(f"niveau_{c.id}", type=int) or 0
        if niveau in NIVEAUX:
            if c.id in existants:
                existants[c.id].niveau = niveau
            else:
                agent.competences.append(NiveauCompetence(competence=c, niveau=niveau))
        elif c.id in existants:
            db.session.delete(existants[c.id])
    db.session.commit()
    flash("Compétences enregistrées.", "success")
    return redirect(url_for("rh.fiche_agent", agent_id=agent_id) + "#competences")


@bp.post("/agents/<int:agent_id>/appreciations")
def ajouter_appreciation(agent_id):
    agent = obtenir_agent(agent_id)
    texte, type_ = champ("texte"), champ("type")
    if texte and type_ in TYPES_APPRECIATION:
        try:
            jour = champ_date("date") or date.today()
        except ValueError:
            jour = date.today()
        agent.appreciations.append(Appreciation(type=type_, texte=texte, date=jour))
        db.session.commit()
    return redirect(url_for("rh.fiche_agent", agent_id=agent_id) + "#appreciations")


@bp.post("/appreciations/<int:appreciation_id>/supprimer")
def supprimer_appreciation(appreciation_id):
    a = db.get_or_404(Appreciation, appreciation_id)
    agent_id = a.agent_id
    db.session.delete(a)
    db.session.commit()
    return redirect(url_for("rh.fiche_agent", agent_id=agent_id) + "#appreciations")


@bp.post("/agents/<int:agent_id>/affectations")
def ajouter_affectation(agent_id):
    """Ajout ou mise à jour d'une affectation (projet, année) depuis la fiche de l'agent."""
    agent = obtenir_agent(agent_id)
    try:
        annee, etp = champ_entier("annee"), champ_montant("etp")
    except ValueError:
        flash("Année ou ETP invalide.", "danger")
        return redirect(url_for("rh.fiche_agent", agent_id=agent_id) + "#charge")
    projet = champ("projet")
    if not (annee and projet and etp is not None):
        flash("Indiquez l'année, le projet / l'activité et la part d'ETP.", "warning")
    else:
        definir_affectation(agent, annee, projet, etp)
        db.session.commit()
    return redirect(url_for("rh.fiche_agent", agent_id=agent_id) + "#charge")


@bp.post("/affectations/<int:affectation_id>/supprimer")
def supprimer_affectation(affectation_id):
    a = db.get_or_404(Affectation, affectation_id)
    agent_id = a.agent_id
    db.session.delete(a)
    db.session.commit()
    return redirect(url_for("rh.fiche_agent", agent_id=agent_id) + "#charge")


def definir_affectation(agent, annee, projet, etp):
    """Crée, met à jour ou (si etp = 0) supprime l'affectation de l'agent."""
    existante = next((a for a in agent.affectations
                      if a.annee == annee and a.projet == projet), None)
    if not etp:
        if existante:
            db.session.delete(existante)
    elif existante:
        existante.etp = etp
    else:
        agent.affectations.append(Affectation(annee=annee, projet=projet, etp=etp))


# --- Plan de charge -------------------------------------------------------------------

@bp.route("/plan-de-charge", methods=["GET", "POST"])
def plan_charge():
    """Grille agents × projets de l'année : chaque case est une part d'ETP."""
    annee = annee_courante()
    _, projet_filtre = filtre_courant()
    agents = agents_actifs()
    if request.method == "POST":
        # Colonnes affichées (une case vide = pas d'affectation) + éventuelle nouvelle colonne
        colonnes = [(i, p.strip(), True) for i, p in enumerate(request.form.getlist("projet"))]
        nouveau = champ("nouveau_projet")
        if nouveau and nouveau not in [p for _, p, _ in colonnes]:
            colonnes.append(("nouveau", nouveau, False))
        erreurs = 0
        for agent in agents:
            for i, projet, existante in colonnes:
                brut = request.form.get(f"etp_{agent.id}_{i}", "").strip()
                if not brut and not existante:
                    continue  # nouvelle colonne laissée vide pour cet agent
                try:
                    etp = float(brut.replace(",", ".")) if brut else 0
                except ValueError:
                    erreurs += 1
                    continue
                definir_affectation(agent, annee, projet, etp)
        db.session.commit()
        flash(f"Plan de charge {annee} enregistré."
              + (f" {erreurs} valeur(s) illisible(s) ignorée(s)." if erreurs else ""),
              "warning" if erreurs else "success")
        return redirect(url_for("rh.plan_charge"))

    affectations = Affectation.query.filter_by(annee=annee).all()
    projets = sorted({a.projet for a in affectations})
    if projet_filtre:
        projets = [p for p in projets if p == projet_filtre] or [projet_filtre]
    grille = {(a.agent_id, a.projet): a.etp for a in affectations}
    return render_template("rh_plan_charge.html", annee=annee, agents=agents, projets=projets,
                           grille=grille, projets_connus=projets_connus(),
                           filtre_projet=projet_filtre,
                           ecarts={a.id: ecart_charge(a, annee) for a in agents})


# --- Compétences ------------------------------------------------------------------------

@bp.route("/competences", methods=["GET", "POST"])
def competences():
    if request.method == "POST":
        nom = champ("nom")
        if nom:
            db.session.add(Competence(nom=nom, domaine=champ("domaine"),
                                      description=champ("description")))
            enregistrer(f"Compétence « {nom} » ajoutée.", f"La compétence « {nom} » existe déjà.")
        return redirect(url_for("rh.competences"))
    actifs = agents_actifs()
    liste = Competence.query.order_by(Competence.domaine, Competence.nom).all()
    return render_template("rh_competences.html", competences=liste, agents=actifs,
                           niveaux=NIVEAUX, a_risque={c.id for c, _ in competences_a_risque(actifs)},
                           domaines=valeurs_distinctes(Competence.domaine),
                           niveau_maitrise=NIVEAU_MAITRISE)


@bp.route("/competences/<int:competence_id>/modifier", methods=["GET", "POST"])
def form_competence(competence_id):
    c = db.get_or_404(Competence, competence_id)
    if request.method == "POST":
        c.nom, c.domaine, c.description = champ("nom"), champ("domaine"), champ("description")
        if enregistrer("Compétence enregistrée.", f"La compétence « {c.nom} » existe déjà."):
            return redirect(url_for("rh.competences"))
        c = db.get_or_404(Competence, competence_id)
    return render_template("rh_competence_form.html", competence=c,
                           domaines=valeurs_distinctes(Competence.domaine))


@bp.post("/competences/<int:competence_id>/supprimer")
def supprimer_competence(competence_id):
    c = db.get_or_404(Competence, competence_id)
    Formation.query.filter_by(competence_id=c.id).update({"competence_id": None})
    db.session.delete(c)
    db.session.commit()
    flash(f"Compétence « {c.nom} » supprimée (et retirée des fiches).", "success")
    return redirect(url_for("rh.competences"))


# --- Formations ---------------------------------------------------------------------------

@bp.route("/formations")
def formations():
    annee, _ = filtre_courant()
    statut = request.args.get("statut", "")
    requete = Formation.query.join(Agent)
    if statut in STATUTS_FORMATION:
        requete = requete.filter(Formation.statut == statut)
    liste = [f for f in requete.order_by(Formation.date_debut.desc()).all()
             if annee is None or f.date_debut is None or f.date_debut.year == annee]
    return render_template("rh_formations.html", formations=liste, statut=statut,
                           statuts=STATUTS_FORMATION, annee=annee,
                           jours=sum(f.duree_jours or 0 for f in liste if f.statut == "réalisée"))


@bp.route("/formations/nouvelle", methods=["GET", "POST"])
@bp.route("/formations/<int:formation_id>/modifier", methods=["GET", "POST"])
def form_formation(formation_id=None):
    if formation_id:
        f = db.get_or_404(Formation, formation_id)
    else:
        f = Formation(statut="prévue", agent_id=request.args.get("agent", type=int))
    retour = request.args.get("retour") or request.form.get("retour") or url_for("rh.formations")
    contexte = {"agents": Agent.query.order_by(Agent.nom, Agent.prenom).all(),
                "competences": Competence.query.order_by(Competence.nom).all(),
                "statuts": STATUTS_FORMATION, "retour": retour,
                "organismes": valeurs_distinctes(Formation.organisme)}
    if request.method == "POST":
        try:
            f.date_debut, f.duree_jours = champ_date("date_debut"), champ_montant("duree_jours")
            f.agent_id, f.competence_id = champ_entier("agent_id"), champ_entier("competence_id")
        except ValueError:
            flash("Date ou durée invalide.", "danger")
            return render_template("rh_formation_form.html", formation=f, **contexte)
        f.intitule, f.organisme, f.commentaire = champ("intitule"), champ("organisme"), champ("commentaire")
        f.statut = champ("statut") if champ("statut") in STATUTS_FORMATION else "prévue"
        if not (f.agent_id and f.intitule):
            flash("Indiquez la personne et l'intitulé.", "danger")
            return render_template("rh_formation_form.html", formation=f, **contexte)
        if formation_id is None:
            db.session.add(f)
        db.session.commit()
        flash("Formation enregistrée.", "success")
        return redirect(retour if retour.startswith("/") and not retour.startswith("//")
                        else url_for("rh.formations"))
    return render_template("rh_formation_form.html", formation=f, **contexte)


@bp.post("/formations/<int:formation_id>/supprimer")
def supprimer_formation(formation_id):
    f = db.get_or_404(Formation, formation_id)
    db.session.delete(f)
    db.session.commit()
    flash("Formation supprimée.", "success")
    retour = request.form.get("retour", "")
    return redirect(retour if retour.startswith("/") and not retour.startswith("//")
                    else url_for("rh.formations"))


@bp.app_template_filter("etp")
def format_etp(v):
    """Part d'ETP à la française : 0,5 – 1 – 0,25."""
    if v is None:
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")

