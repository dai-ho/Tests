# Gestion des achats – DA / Commandes

Application web **locale** pour remplacer le suivi Excel des Demandes d'Achat et des Commandes.
Elle ne nécessite aucun serveur et aucune donnée ne quitte le PC.

## Démarrage sous Windows

1. Installer Python 3.10 ou plus depuis <https://www.python.org/downloads/>
   (cocher **« Add python.exe to PATH »**).
2. Double-cliquer sur **`lancer.bat`**.
   Au premier lancement, un environnement Python local (`.venv`) est créé et les dépendances
   sont installées (une à deux minutes). Le navigateur s'ouvre ensuite sur <http://127.0.0.1:5000>.
3. Pour arrêter : fermer la fenêtre noire.

Pour reprendre l'existant : menu **Importer Excel**, puis choisir le fichier actuel.

## Fonctionnalités

Reprend la structure du fichier **Budgets GT** (onglets « Suivi DA » et « Suivi BdC ») :

- **Demandes d'achat** : n° de DA (peut rester vide tant qu'il n'est pas attribué), postes avec année, projet,
  désignation, valeur, centre de coût, statut (en cours / clos / supprimé), remarque.
  **Imputé** (somme des postes de BdC rattachés) et **Disponible** sont calculés automatiquement.
- **Bons de commande** : n° BDC/Marché, postes avec société (fournisseur), activité, désignation, montant,
  échéance, PTF (PAF), CSF et CR pour CSF (ce dernier n'apparaît que lorsque la CSF est cochée). Chaque poste est rattaché à un
  poste de DA, choisi dans une liste qui affiche le disponible restant.
- **Création d'un BdC en une étape** (pop-up) : poste de DA, marché, société, désignation, projet,
  montant, échéance, lot. Le n° de BdC est saisi plus tard, quand le service achat le communique.
- **E-mail de demande de commande** : bouton « ✉ E-mail » sur chaque BdC, qui ouvre un message pré-rempli
  dans la messagerie (objet, marché, lot, désignation, montant, échéance, rappel du poste de DA).
  Destinataire, prénom, formule de fin et signature se règlent dans **Paramètres**.
- **Marchés** : référence, titulaire, lots, échéance, montant maximal. Le total des BdC passés sur un marché
  ne peut pas dépasser son montant maximal (contrôle à la saisie, jauge de consommation). Le lot est choisi
  à chaque commande parmi ceux du marché. Un marché **simplifié** n'accepte qu'une seule commande.
- **Suivi DA / Suivi BdC** : vues tableur avec filtre instantané et tri par colonne.
- **Filtre année / projet** (bandeau sous le menu) sur le tableau de bord, les DA, le Suivi DA, les BdC et le
  Suivi BdC ; l'année en cours est sélectionnée par défaut. Un poste de BdC prend l'année et le projet de son
  poste de DA. Les marchés, pluriannuels, ne sont pas filtrés.
- **Tableau de bord** : synthèse Valeur / Imputé / Disponible par projet et année, échéances dépassées sans
  CSF, postes de DA sans BdC, dépassements.
- **Couleurs des lignes** : mêmes règles et mêmes teintes que la mise en forme conditionnelle du fichier
  Excel, regroupées dans `regles.py`.
- **Import / export Excel** au format du fichier Budgets GT (l'export est réimportable).

## Données

Base SQLite dans `donnees/achats.db` (un seul fichier). `sauvegarder.bat` en fait une copie horodatée
dans `donnees/sauvegardes/`.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `app.py` | Application Flask : pages et formulaires |
| `models.py` | Modèle de données (DA, postes DA, BdC, postes BdC) |
| `regles.py` | Règles de couleur des lignes |
| `mail.py` | E-mail de demande de commande au service achat |
| `excel_io.py` | Import / export Excel, en-têtes de colonnes reconnus |
| `templates/` | Pages HTML (Jinja2 + Bootstrap) |
| `static/` | CSS / JS (Bootstrap embarqué : fonctionne sans Internet) |
