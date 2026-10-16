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

- **Demandes d'achat** : référence, postes (10, 20, 30…) avec nom, montant, date de livraison,
  code d'imputation, demandeur, certificateur. Un nouveau poste reprend l'imputation, le demandeur et le
  certificateur du poste précédent.
- **Commandes** : référence, postes rattachés chacun à un poste de DA (de n'importe quelle DA), nom,
  CSF fait / non fait (bouton cliquable), référence du livrable, PTF, date de livraison.
- **Vues « Tous les postes »** façon tableur : filtre texte instantané et tri en cliquant sur les en-têtes.
- **Tableau de bord** : postes en retard de certification, postes de DA pas encore commandés.
- **Mise en couleur des lignes** : règles provisoires dans `regles.py`, à adapter.
- **Import / export Excel** : l'export produit un fichier réimportable, utilisable aussi comme sauvegarde.

## Données

Base SQLite dans `donnees/achats.db` (un seul fichier). `sauvegarder.bat` en fait une copie horodatée
dans `donnees/sauvegardes/`.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `app.py` | Application Flask : pages et formulaires |
| `models.py` | Modèle de données (DA, postes DA, commandes, postes commande) |
| `regles.py` | Règles de couleur des lignes |
| `excel_io.py` | Import / export Excel, en-têtes de colonnes reconnus |
| `templates/` | Pages HTML (Jinja2 + Bootstrap) |
| `static/` | CSS / JS (Bootstrap embarqué : fonctionne sans Internet) |
