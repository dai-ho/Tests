"""Modèle de données : Demandes d'Achat (DA), Bons de Commande (BdC) et leurs postes."""
from datetime import date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

STATUTS_DA = ["", "clos", "supprimé"]


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
    budget = db.Column(db.Float)
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


class Commande(db.Model):
    __tablename__ = "commande"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)  # N° BDC / Marché
    societe = db.Column(db.String(100))
    commentaire = db.Column(db.Text)

    postes = db.relationship(
        "PosteCommande", back_populates="commande", cascade="all, delete-orphan",
        order_by="PosteCommande.numero",
    )

    @property
    def nb_certifies(self):
        return sum(1 for p in self.postes if p.csf)

    @property
    def montant_total(self):
        return sum(p.montant or 0 for p in self.postes)


class PosteCommande(db.Model):
    __tablename__ = "poste_commande"
    __table_args__ = (db.UniqueConstraint("commande_id", "numero"),)

    id = db.Column(db.Integer, primary_key=True)
    commande_id = db.Column(db.Integer, db.ForeignKey("commande.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    poste_da_id = db.Column(db.Integer, db.ForeignKey("poste_da.id"))
    nom = db.Column(db.String(255), nullable=False)        # Désignation
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
