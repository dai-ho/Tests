# Pilotage – budgets et équipe

Application web **locale** pour remplacer le suivi Excel des Demandes d'Achat et des Commandes.
Elle ne nécessite aucun serveur et aucune donnée ne quitte le PC.

## Démarrage sous Windows

1. Installer Python 3.10 ou plus depuis <https://www.python.org/downloads/>
   (cocher **« Add python.exe to PATH »**).
2. Double-cliquer sur **`lancer.bat`**.
   Au premier lancement, un environnement Python local (`.venv`) est créé et les dépendances
   sont installées (une à deux minutes). Le navigateur s'ouvre ensuite sur <http://127.0.0.1:5000>.
3. Pour arrêter : `arreter.bat` (l'application tourne sans fenêtre).

Pour reprendre l'existant : menu **Importer Excel**, puis choisir le fichier actuel.

## Lancement automatique en arrière-plan (sans droits administrateur)

- **`demarrage_auto_activer.bat`** : l'application démarre sans fenêtre à chaque ouverture de session
  (raccourci dans le dossier « Démarrage » de l'utilisateur) et un raccourci « Budgets DA-BdC » est créé
  sur le Bureau. Elle est lancée immédiatement.
- **`demarrage_auto_desactiver.bat`** : retire ces raccourcis.
- **`arreter.bat`** (ou *Paramètres > Arrêter l'application*) : arrête l'application.
- **`lancer_console.bat`** : lancement dans une fenêtre, pour voir les messages en cas de problème.
- Une seule instance tourne à la fois : relancer l'application ouvre simplement le navigateur.
- Sans fenêtre, les messages et erreurs sont écrits dans `donnees/application.log`, et une copie de la
  base est faite chaque jour dans `donnees/sauvegardes` (30 dernières conservées).

## Protection de la base par carte à puce (facultative)

*Paramètres > Protection de la base par carte à puce* : choisir le certificat de chiffrement de la carte
puis « Activer la protection » (Windows demande le code PIN une fois, pour vérifier que la carte sait relire la clé).

- La base (`donnees/achats.db.chiffre`) et ses sauvegardes sont chiffrées en AES-256-GCM ; la clé est chiffrée
  avec le certificat de la carte (`donnees/cle_protection.json`). La base déchiffrée n'existe qu'en mémoire.
- Au démarrage, l'application est verrouillée : bouton « Déverrouiller avec la carte » puis code PIN.
- Le retrait de la carte du lecteur verrouille l'application (bouton « 🔒 Verrouiller » pour le faire à la main).
- **Renouvellement de carte** : avant l'expiration, déverrouiller avec l'ancienne carte puis associer le certificat
  de la nouvelle (Paramètres). **Perte de la carte** : seule la récupération de la clé de chiffrement par le service
  PKI (séquestre) permet de rouvrir la base.
- Les exports Excel ne sont pas chiffrés.
- Restaurer une sauvegarde : application arrêtée, copier `sauvegardes/achats_AAAAMMJJ.db.chiffre` sur
  `donnees/achats.db.chiffre` (même clé).

## Organisation

Une barre latérale donne accès à deux espaces :

- **Gestion budgétaire** : tableau de bord, budgets, demandes d'achat, bons de commande, marchés, import / export Excel
  (détaillés plus bas).
- **Gestion RH** :
  - **Équipe** : fiches des personnes (fonction, statut, quotité en ETP, dates d'arrivée et de départ), vue d'ensemble
    (effectif, capacité, charge planifiée, écarts de charge, compétences à risque, formations à venir).
  - **Fiche d'une personne** : plan de charge par année, points forts et axes de progrès (datés), niveaux de
    compétence (1 Notions → 4 Expert), formations.
  - **Plan de charge** : une ligne par centre de coût, regroupée par type puis par activité (groupes repliables,
    sous-totaux), une colonne par personne ; ETP de l'année, totaux et écarts à la quotité recalculés à la saisie
    (surcharge, sous-charge) ; le réalisé est rappelé sous chaque valeur.
  - **Codes et activités** : référentiel des codes EOTP (type, désignation SAP, description) importé par type
    depuis un CSV (code EOTP, désignation SAP, description, cible MSO — ignorée) ; regroupement manuel des codes
    en activités ; les codes utilisés mais absents du référentiel apparaissent en « Non classé ».
    Chaque code est modifiable ; renommer un code vers un code existant les fusionne (temps et plan de charge
    reportés et cumulés), l'ancienne graphie devenant un alias converti aux imports suivants. Les doublons
    probables (mêmes codes aux parenthèses, espaces et majuscules près) sont signalés avec un bouton « Fusionner ».
  - **Temps réalisés** : import du marquage des temps (Excel ou CSV à 4 colonnes : Genre Prénom NOM, objet
    récepteur, date, heures saisies). Les saisies de la période couverte par le fichier sont remplacées (pas de
    doublon en cas de réimport), les personnes inconnues sont créées. Synthèse par personne et centre de coût, en
    heures ou en ETP (base de conversion réglable, 1 607 h = 1 ETP par défaut).
  - **Compétences** : référentiel et matrice de l'équipe ; une compétence maîtrisée (niveau ≥ 3) par moins de
    2 personnes est signalée « à risque ».
  - **Formations** : prévues, réalisées ou annulées, rattachables à une compétence.

Les données RH sont dans la même base que les budgets : elles sont donc chiffrées si la protection par carte
est activée. Elles ne figurent pas dans l'export Excel.

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
- **Budgets** : lignes budgétaires (code = centre de coût des DA, ex. 23T_0531 ou C_MMX/20), de type
  *structure* (à consommer dans l'année, perdu sinon) ou *projet* (reliquat reportable sur N+1, bouton
  « Reporter »). Par année : montant demandé (demande faite en N pour N+1), montant alloué à la confirmation,
  report. Vue annuelle et pluriannuelle comparant le budget aux DA (prévisionnel) et aux BdC (imputé réel),
  avec alertes (DA ou BdC au-delà du budget, budget structure à consommer avant le 31/12, centres de coût
  sans ligne). Un avertissement s'affiche à l'enregistrement d'un poste de DA ou de BdC qui dépasse le budget.
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
| `protection.py` | Chiffrement de la base, clé protégée par la carte à puce, verrouillage |
| `temps.py` | Import du marquage des temps, conversion heures → ETP |
| `referentiel.py` | Référentiel des codes EOTP, import CSV, regroupement type → activité → code |
| `rh.py` | Gestion RH : équipe, compétences, plan de charge, formations |
| `formulaires.py` | Lecture des formulaires, filtre année / projet (communs) |
| `budgets.py` | Calcul des situations budgétaires (budget, DA, BdC, disponible, alertes) |
| `mail.py` | E-mail de demande de commande au service achat |
| `excel_io.py` | Import / export Excel, en-têtes de colonnes reconnus |
| `templates/` | Pages HTML (Jinja2 + Bootstrap) |
| `static/` | CSS / JS (Bootstrap embarqué : fonctionne sans Internet) |
