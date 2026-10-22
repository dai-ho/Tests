"""Modèle de données : gestion budgétaire (Demandes d'Achat, Bons de Commande, marchés,
budgets), gestion RH (équipe, compétences, plan de charge, formations), paramètres."""
from datetime import date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

STATUTS_DA = ["", "clos", "supprimé"]


def k_euros(montant):
    """Montant en k€ comme dans le fichier Excel : 55000 -> « 55k€ », 24555 -> « 24,555k€ »."""
    return f"{(montant or 0) / 1000:.3f}".rstrip("0").rstrip(".").replace(".", ",") + "k€"


class Parametre(db.Model):
    """Réglages modifiables depuis l'application (ex. : destinataire de l'e-mail)."""
    __tablename__ = "parametre"

    cle = db.Column(db.String(50), primary_key=True)
    valeur = db.Column(db.Text)


class Marche(db.Model):
    __tablename__ = "marche"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    titulaire = db.Column(db.String(100))                   # Fournisseur
    lots = db.Column("lot", db.String(255))                 # lots du marché, séparés par « ; »
    # Marché simplifié : une seule commande en tout et pour tout
    simplifie = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    date_echeance = db.Column(db.Date)
    montant_max = db.Column(db.Float)
    commentaire = db.Column(db.Text)

    commandes = db.relationship("Commande", back_populates="marche")

    @property
    def liste_lots(self):
        return [x.strip() for x in (self.lots or "").split(";") if x.strip()]

    def engage(self, sauf_poste=None, sauf_commande=None):
        """Total des postes de BdC passés sur ce marché."""
        return sum(p.montant or 0 for c in self.commandes if c is not sauf_commande
                   for p in c.postes if p is not sauf_poste)

    @property
    def restant(self):
        return None if self.montant_max is None else self.montant_max - self.engage()

    @property
    def taux(self):
        return self.engage() / self.montant_max * 100 if self.montant_max else None

    @property
    def expire(self):
        return self.date_echeance is not None and self.date_echeance < date.today()


class DemandeAchat(db.Model):
    __tablename__ = "demande_achat"

    id = db.Column(db.Integer, primary_key=True)
    # Vide tant que le numéro de DA n'est pas attribué
    reference = db.Column(db.String(50), unique=True)
    commentaire = db.Column(db.Text)

    postes = db.relationship(
        "PosteDA", back_populates="da", cascade="all, delete-orphan",
        order_by="PosteDA.numero",
    )

    @property
    def libelle(self):
        return self.reference or f"DA sans n° (#{self.id})"

    def _somme(self, attribut):
        return sum(getattr(p, attribut) or 0 for p in self.postes if p.statut != "supprimé")

    @property
    def montant_total(self):
        return self._somme("montant")

    @property
    def impute_total(self):
        return self._somme("impute")

    @property
    def disponible_total(self):
        return self._somme("disponible")


class PosteDA(db.Model):
    __tablename__ = "poste_da"
    __table_args__ = (db.UniqueConstraint("da_id", "numero"),)

    id = db.Column(db.Integer, primary_key=True)
    da_id = db.Column(db.Integer, db.ForeignKey("demande_achat.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)        # Désignation
    montant = db.Column(db.Float)                           # Valeur
    annee = db.Column(db.Integer)
    projet = db.Column(db.String(100))
    code_imputation = db.Column(db.String(50))              # Centre de coût
    budget = db.Column(db.Float)  # colonne cachée du fichier : conservée, non affichée pour l'instant
    statut = db.Column(db.String(20), nullable=False, default="")
    remarque = db.Column(db.Text)
    date_livraison = db.Column(db.Date)
    demandeur = db.Column(db.String(100))
    certificateur = db.Column(db.String(100))

    da = db.relationship("DemandeAchat", back_populates="postes")
    postes_commande = db.relationship("PosteCommande", back_populates="poste_da")

    @property
    def impute(self):
        """Somme des montants des postes de BdC rattachés (colonne « Imputé »)."""
        return sum(p.montant or 0 for p in self.postes_commande)

    @property
    def disponible(self):
        return (self.montant or 0) - self.impute

    @property
    def cle(self):
        """Équivalent de la colonne Excel « DA@poste »."""
        return f"{self.da.reference or ''}@{self.numero}"

    @property
    def libelle(self):
        return f"{self.nom} — {self.cle}"

    @property
    def rappel(self):
        """Rappel du poste de DA dans l'e-mail : « 10181766@10 (55k€) »."""
        return f"{self.cle} ({k_euros(self.montant)})"


TYPES_BUDGET = {
    "structure": "Structure : à consommer dans l'année, perdu sinon",
    "projet": "Projet : reliquat reportable sur l'année suivante",
}


class LigneBudgetaire(db.Model):
    """Ligne budgétaire allouée, identifiée par un code (ex. 23T_0531, C_MMX/20) : c'est le
    « centre de coût » des postes de DA qui la consomment."""
    __tablename__ = "ligne_budgetaire"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    libelle = db.Column(db.String(255))
    type = db.Column(db.String(20), nullable=False, default="structure")
    projet = db.Column(db.String(100))
    commentaire = db.Column(db.Text)

    annees = db.relationship("BudgetAnnuel", back_populates="ligne",
                             cascade="all, delete-orphan", order_by="BudgetAnnuel.annee")

    @property
    def reportable(self):
        return self.type == "projet"

    def budget(self, annee):
        return next((b for b in self.annees if b.annee == annee), None)


class BudgetAnnuel(db.Model):
    """Budget d'une ligne pour une année : demandé (en N-1), puis alloué à la confirmation,
    plus un éventuel report de l'année précédente (lignes projet)."""
    __tablename__ = "budget_annuel"
    __table_args__ = (db.UniqueConstraint("ligne_id", "annee"),)

    id = db.Column(db.Integer, primary_key=True)
    ligne_id = db.Column(db.Integer, db.ForeignKey("ligne_budgetaire.id"), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    montant_demande = db.Column(db.Float)
    montant_alloue = db.Column(db.Float)        # vide tant que la demande n'est pas confirmée
    report = db.Column(db.Float)
    commentaire = db.Column(db.Text)

    ligne = db.relationship("LigneBudgetaire", back_populates="annees")

    @property
    def confirme(self):
        return self.montant_alloue is not None

    @property
    def montant(self):
        """Montant de référence : l'alloué s'il est confirmé, sinon le demandé (envisagé)."""
        return self.montant_alloue if self.confirme else (self.montant_demande or 0)

    @property
    def total(self):
        return self.montant + (self.report or 0)


class Commande(db.Model):
    __tablename__ = "commande"

    id = db.Column(db.Integer, primary_key=True)
    # N° BdC : vide tant que le service achat ne l'a pas communiqué
    reference = db.Column(db.String(50), unique=True)
    marche_id = db.Column(db.Integer, db.ForeignKey("marche.id"))
    lot = db.Column(db.String(100))                         # lot du marché commandé, ex. « à BPU »
    commentaire = db.Column(db.Text)

    marche = db.relationship("Marche", back_populates="commandes")
    postes = db.relationship(
        "PosteCommande", back_populates="commande", cascade="all, delete-orphan",
        order_by="PosteCommande.numero",
    )

    @property
    def libelle(self):
        return self.reference or "N° en attente"

    @property
    def nb_certifies(self):
        return sum(1 for p in self.postes if p.csf)

    @property
    def montant_total(self):
        return sum(p.montant or 0 for p in self.postes)

    @property
    def societes(self):
        """Fournisseurs des postes (en général un seul par BdC)."""
        return list(dict.fromkeys(p.societe for p in self.postes if p.societe))


class PosteCommande(db.Model):
    __tablename__ = "poste_commande"
    __table_args__ = (db.UniqueConstraint("commande_id", "numero"),)

    id = db.Column(db.Integer, primary_key=True)
    commande_id = db.Column(db.Integer, db.ForeignKey("commande.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    poste_da_id = db.Column(db.Integer, db.ForeignKey("poste_da.id"))
    nom = db.Column(db.String(255), nullable=False)        # Désignation
    societe = db.Column(db.String(100))                     # Fournisseur
    activite = db.Column(db.String(100))
    montant = db.Column(db.Float)
    date_livraison = db.Column(db.Date)                     # Échéance
    ptf = db.Column(db.String(255))                         # PTF / PAF
    csf = db.Column(db.Boolean, nullable=False, default=False)
    ref_livrable = db.Column(db.String(255))                # CR pour CSF

    commande = db.relationship("Commande", back_populates="postes")
    poste_da = db.relationship("PosteDA", back_populates="postes_commande")

    @property
    def en_retard(self):
        return (not self.csf and self.date_livraison is not None
                and self.date_livraison < date.today())


# --- Gestion RH ----------------------------------------------------------------------

NIVEAUX = {1: "Notions", 2: "Pratique", 3: "Maîtrise", 4: "Expert"}
STATUTS_AGENT = ["Titulaire", "CDI", "CDD", "Alternant", "Stagiaire", "Prestataire"]
STATUTS_FORMATION = ["prévue", "réalisée", "annulée"]
TYPES_APPRECIATION = {"fort": "Point fort", "progres": "Axe de progrès"}


class Agent(db.Model):
    """Membre de l'équipe."""
    __tablename__ = "agent"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100))
    fonction = db.Column(db.String(150))
    statut = db.Column(db.String(50))
    etp = db.Column(db.Float, nullable=False, default=1.0)   # quotité : 1 = temps plein
    date_arrivee = db.Column(db.Date)
    date_depart = db.Column(db.Date)
    email = db.Column(db.String(150))
    commentaire = db.Column(db.Text)

    competences = db.relationship("NiveauCompetence", back_populates="agent",
                                  cascade="all, delete-orphan")
    appreciations = db.relationship("Appreciation", back_populates="agent",
                                    cascade="all, delete-orphan",
                                    order_by="Appreciation.date.desc()")
    affectations = db.relationship("Affectation", back_populates="agent",
                                   cascade="all, delete-orphan",
                                   order_by="(Affectation.annee.desc(), Affectation.projet)")
    formations = db.relationship("Formation", back_populates="agent",
                                 cascade="all, delete-orphan",
                                 order_by="Formation.date_debut.desc()")

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}" if self.prenom else self.nom

    @property
    def actif(self):
        return self.date_depart is None or self.date_depart >= date.today()

    def charge(self, annee):
        """Total des affectations (en ETP) sur l'année."""
        return sum(a.etp or 0 for a in self.affectations if a.annee == annee)

    def niveau(self, competence_id):
        return next((n.niveau for n in self.competences if n.competence_id == competence_id), 0)


class Competence(db.Model):
    __tablename__ = "competence"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(150), unique=True, nullable=False)
    domaine = db.Column(db.String(100))
    description = db.Column(db.Text)

    niveaux = db.relationship("NiveauCompetence", back_populates="competence",
                              cascade="all, delete-orphan")


class NiveauCompetence(db.Model):
    __tablename__ = "niveau_competence"
    __table_args__ = (db.UniqueConstraint("agent_id", "competence_id"),)

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agent.id"), nullable=False)
    competence_id = db.Column(db.Integer, db.ForeignKey("competence.id"), nullable=False)
    niveau = db.Column(db.Integer, nullable=False)          # 1 à 4, voir NIVEAUX

    agent = db.relationship("Agent", back_populates="competences")
    competence = db.relationship("Competence", back_populates="niveaux")


class Appreciation(db.Model):
    """Point fort ou axe de progrès, daté (garde l'historique)."""
    __tablename__ = "appreciation"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agent.id"), nullable=False)
    type = db.Column(db.String(10), nullable=False)          # voir TYPES_APPRECIATION
    texte = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)

    agent = db.relationship("Agent", back_populates="appreciations")


class Affectation(db.Model):
    """Part du temps d'un agent sur un projet / une activité pour une année (en ETP)."""
    __tablename__ = "affectation"
    __table_args__ = (db.UniqueConstraint("agent_id", "annee", "projet"),)

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agent.id"), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    projet = db.Column(db.String(100), nullable=False)
    etp = db.Column(db.Float, nullable=False)

    agent = db.relationship("Agent", back_populates="affectations")


class Formation(db.Model):
    __tablename__ = "formation"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agent.id"), nullable=False)
    intitule = db.Column(db.String(255), nullable=False)
    organisme = db.Column(db.String(150))
    date_debut = db.Column(db.Date)
    duree_jours = db.Column(db.Float)
    statut = db.Column(db.String(20), nullable=False, default="prévue")
    competence_id = db.Column(db.Integer, db.ForeignKey("competence.id"))
    commentaire = db.Column(db.Text)

    agent = db.relationship("Agent", back_populates="formations")
    competence = db.relationship("Competence")
