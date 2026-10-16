"""Modèle de données : Demandes d'Achat (DA), Commandes et leurs postes."""
from datetime import date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class DemandeAchat(db.Model):
    __tablename__ = "demande_achat"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    commentaire = db.Column(db.Text)

    postes = db.relationship(
        "PosteDA", back_populates="da", cascade="all, delete-orphan",
        order_by="PosteDA.numero",
    )

    @property
    def montant_total(self):
        return sum(p.montant or 0 for p in self.postes)


class PosteDA(db.Model):
    __tablename__ = "poste_da"
    __table_args__ = (db.UniqueConstraint("da_id", "numero"),)

    id = db.Column(db.Integer, primary_key=True)
    da_id = db.Column(db.Integer, db.ForeignKey("demande_achat.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    nom = db.Column(db.String(255), nullable=False)
    montant = db.Column(db.Float)
    date_livraison = db.Column(db.Date)
    code_imputation = db.Column(db.String(50))
    demandeur = db.Column(db.String(100))
    certificateur = db.Column(db.String(100))

    da = db.relationship("DemandeAchat", back_populates="postes")
    postes_commande = db.relationship("PosteCommande", back_populates="poste_da")

    @property
    def libelle(self):
        return f"{self.da.reference} / {self.numero} – {self.nom}"


class Commande(db.Model):
    __tablename__ = "commande"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    commentaire = db.Column(db.Text)

    postes = db.relationship(
        "PosteCommande", back_populates="commande", cascade="all, delete-orphan",
        order_by="PosteCommande.numero",
    )

    @property
    def nb_certifies(self):
        return sum(1 for p in self.postes if p.csf)


class PosteCommande(db.Model):
    __tablename__ = "poste_commande"
    __table_args__ = (db.UniqueConstraint("commande_id", "numero"),)

    id = db.Column(db.Integer, primary_key=True)
    commande_id = db.Column(db.Integer, db.ForeignKey("commande.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    poste_da_id = db.Column(db.Integer, db.ForeignKey("poste_da.id"))
    nom = db.Column(db.String(255), nullable=False)
    csf = db.Column(db.Boolean, nullable=False, default=False)
    ref_livrable = db.Column(db.String(255))
    ptf = db.Column(db.String(255))
    date_livraison = db.Column(db.Date)

    commande = db.relationship("Commande", back_populates="postes")
    poste_da = db.relationship("PosteDA", back_populates="postes_commande")

    @property
    def en_retard(self):
        return (not self.csf and self.date_livraison is not None
                and self.date_livraison < date.today())
