"""Protection de la base par la carte à puce (Scytale ou autre carte gérée par Windows).

- La base est chiffrée sur le disque (AES-256-GCM) : donnees/achats.db.chiffre.
- La clé AES est elle-même chiffrée avec le certificat de chiffrement de la carte
  (donnees/cle_protection.json) : seule la carte, avec son code PIN, peut la retrouver.
- Une fois déverrouillée, la base n'existe déchiffrée qu'en mémoire ; chaque enregistrement
  est réécrit chiffré sur le disque.
- Le retrait de la carte du lecteur verrouille l'application.

Les opérations sur la carte passent par Windows (PowerShell / .NET) : c'est Windows qui
affiche la demande de code PIN. Aucun droit administrateur n'est nécessaire.
"""
import base64
import ctypes
import json
import os
import sqlite3
import subprocess
import threading
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENTETE = b"BUDGDA1\0"           # signature et version du format du fichier chiffré
SANS_FENETRE = 0x08000000       # CREATE_NO_WINDOW : pas de console PowerShell visible


class ErreurProtection(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""


# --- Chiffrement des données ------------------------------------------------------

def chiffrer(donnees, cle):
    nonce = os.urandom(12)
    return ENTETE + nonce + AESGCM(cle).encrypt(nonce, donnees, ENTETE)


def dechiffrer(contenu, cle):
    if not contenu.startswith(ENTETE):
        raise ErreurProtection("fichier chiffré non reconnu")
    nonce = contenu[len(ENTETE):len(ENTETE) + 12]
    try:
        return AESGCM(cle).decrypt(nonce, contenu[len(ENTETE) + 12:], ENTETE)
    except Exception:
        raise ErreurProtection("clé incorrecte ou fichier chiffré endommagé")


def ecrire_atomique(chemin, contenu):
    """Écrit dans un fichier temporaire puis le substitue : jamais de fichier à moitié écrit."""
    temporaire = chemin + ".tmp"
    with open(temporaire, "wb") as f:
        f.write(contenu)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporaire, chemin)


def effacer(chemin):
    """Supprime un fichier en clair après l'avoir écrasé (au mieux : un SSD peut garder des copies)."""
    if os.path.exists(chemin):
        with open(chemin, "r+b") as f:
            f.write(b"\0" * os.path.getsize(chemin))
            f.flush()
            os.fsync(f.fileno())
        os.remove(chemin)


def base_vers_octets(chemin):
    """Contenu d'une base SQLite (fichier) sous forme d'octets, copie cohérente."""
    source, memoire = sqlite3.connect(chemin), sqlite3.connect(":memory:")
    source.backup(memoire)
    source.close()
    octets = memoire.serialize()
    memoire.close()
    return octets


def octets_vers_fichier(octets, chemin):
    memoire = sqlite3.connect(":memory:")
    memoire.deserialize(octets)
    cible = sqlite3.connect(chemin)
    memoire.backup(cible)
    cible.close()
    memoire.close()


# --- Certificats et carte (via Windows) ---------------------------------------------

def _powershell(script):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8",
                       creationflags=SANS_FENETRE)
    if r.returncode != 0:
        message = (r.stderr or r.stdout).strip().splitlines()
        raise ErreurProtection(_message_carte(" ".join(message[:3])))
    return r.stdout.strip()


def _message_carte(erreur):
    e = erreur.lower()
    if "annul" in e or "cancel" in e:
        return "saisie du code PIN annulée"
    if "pin" in e and ("incorrect" in e or "wrong" in e):
        return "code PIN incorrect"
    if "bloqu" in e or "blocked" in e:
        return "carte bloquée (trop d'erreurs de code PIN)"
    if "carte" in e or "smart card" in e or "absent" in e or "keyset" in e or "jeu de cl" in e:
        return "carte absente ou certificat introuvable sur la carte"
    return f"opération refusée par la carte : {erreur}"


_UTF8 = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "


def certificats_chiffrement():
    """Certificats de l'utilisateur utilisables pour chiffrer (clé privée présente,
    usage « chiffrement de clé »), ceux d'une carte à puce en premier."""
    script = _UTF8 + r"""
$res = foreach ($c in Get-ChildItem Cert:\CurrentUser\My) {
  if (-not $c.HasPrivateKey -or $c.PublicKey.Oid.FriendlyName -ne 'RSA') { continue }
  $ku = ($c.Extensions | Where-Object { $_ -is [System.Security.Cryptography.X509Certificates.X509KeyUsageExtension] }).KeyUsages
  if ("$ku" -notmatch 'KeyEncipherment') { continue }
  $fournisseur = ''
  try { $fournisseur = $c.PrivateKey.CspKeyContainerInfo.ProviderName } catch { }
  if (-not $fournisseur) { try { $fournisseur = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($c).Key.Provider.Provider } catch { } }
  [pscustomobject]@{ empreinte = $c.Thumbprint; sujet = ($c.Subject -replace ',.*', '');
    emetteur = ($c.Issuer -replace ',.*', ''); expire = $c.NotAfter.ToString('yyyy-MM-dd');
    carte = ($fournisseur -match 'Smart Card|Carte'); fournisseur = "$fournisseur" }
}
ConvertTo-Json -Compress @($res)
"""
    liste = json.loads(_powershell(script) or "[]")
    aujourdhui = datetime.now().strftime("%Y-%m-%d")
    for c in liste:
        c["valide"] = c["expire"] >= aujourdhui
    return sorted(liste, key=lambda c: (not c["carte"], not c["valide"], c["expire"]), reverse=False)


def envelopper(cle, empreinte):
    """Chiffre la clé avec la clé publique du certificat (pas de code PIN)."""
    script = (r"$c = Get-Item 'Cert:\CurrentUser\My\%s'; "
              r"$k = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($c); "
              r"[Convert]::ToBase64String($k.Encrypt([Convert]::FromBase64String('%s'), "
              r"[System.Security.Cryptography.RSAEncryptionPadding]::Pkcs1))"
              % (_empreinte(empreinte), base64.b64encode(cle).decode()))
    return _powershell(script)


def desenvelopper(enveloppe, empreinte):
    """Déchiffre la clé avec la clé privée du certificat : Windows demande le code PIN."""
    script = (r"$c = Get-Item 'Cert:\CurrentUser\My\%s'; "
              r"$k = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($c); "
              r"[Convert]::ToBase64String($k.Decrypt([Convert]::FromBase64String('%s'), "
              r"[System.Security.Cryptography.RSAEncryptionPadding]::Pkcs1))"
              % (_empreinte(empreinte), enveloppe))
    return base64.b64decode(_powershell(script))


def _empreinte(e):
    if not e or not all(ch in "0123456789ABCDEFabcdef" for ch in e):
        raise ErreurProtection("empreinte de certificat invalide")
    return e


def carte_presente():
    """Vrai si une carte est insérée dans un lecteur, None si l'information est indisponible."""
    try:
        w = ctypes.WinDLL("winscard")
    except OSError:
        return None

    class Lecteur(ctypes.Structure):
        _fields_ = [("szReader", ctypes.c_wchar_p), ("pvUserData", ctypes.c_void_p),
                    ("dwCurrentState", ctypes.c_ulong), ("dwEventState", ctypes.c_ulong),
                    ("cbAtr", ctypes.c_ulong), ("rgbAtr", ctypes.c_ubyte * 36)]

    ctx = ctypes.c_size_t()
    if w.SCardEstablishContext(2, None, None, ctypes.byref(ctx)):  # SCARD_SCOPE_SYSTEM
        return None
    try:
        taille = ctypes.c_ulong(0)
        if w.SCardListReadersW(ctx, None, None, ctypes.byref(taille)):
            return False  # aucun lecteur
        tampon = ctypes.create_unicode_buffer(taille.value)
        if w.SCardListReadersW(ctx, None, tampon, ctypes.byref(taille)):
            return False
        noms = [n for n in tampon[:taille.value].split("\0") if n]
        etats = (Lecteur * len(noms))(*[Lecteur(szReader=n) for n in noms])
        if w.SCardGetStatusChangeW(ctx, 0, etats, len(noms)):
            return None
        return any(e.dwEventState & 0x20 for e in etats)  # SCARD_STATE_PRESENT
    finally:
        w.SCardReleaseContext(ctx)


# --- Coffre : état de la base protégée ------------------------------------------------

class Coffre:
    def __init__(self, dossier):
        self.fichier = os.path.join(dossier, "achats.db.chiffre")
        self.fichier_cle = os.path.join(dossier, "cle_protection.json")
        self.cle = None
        self.connexion = None
        self.verrou = threading.RLock()
        self.raison_verrouillage = None

    @property
    def active(self):
        return os.path.exists(self.fichier)

    @property
    def deverrouille(self):
        return self.connexion is not None

    def enveloppes(self):
        if not os.path.exists(self.fichier_cle):
            return []
        with open(self.fichier_cle, encoding="utf-8") as f:
            return json.load(f)["enveloppes"]

    def _ecrire_enveloppes(self, enveloppes):
        ecrire_atomique(self.fichier_cle, json.dumps({"version": 1, "enveloppes": enveloppes},
                                                     indent=2, ensure_ascii=False).encode())

    def nouvelle_enveloppe(self, cle, certificat):
        return {"empreinte": certificat["empreinte"], "sujet": certificat["sujet"],
                "emetteur": certificat["emetteur"], "expire": certificat["expire"],
                "rembourrage": "pkcs1", "cle": envelopper(cle, certificat["empreinte"]),
                "ajoutee": datetime.now().strftime("%Y-%m-%d")}

    # Déverrouillage / verrouillage
    def deverrouiller(self):
        """Retrouve la clé grâce à la carte (code PIN) et charge la base en mémoire."""
        with self.verrou:
            if self.deverrouille:
                return
            enveloppes = sorted(self.enveloppes(), key=lambda e: e["expire"], reverse=True)
            if not enveloppes:
                raise ErreurProtection("fichier de clé absent : base impossible à déverrouiller")
            presents = {c["empreinte"].upper() for c in certificats_chiffrement()}
            utilisables = [e for e in enveloppes if e["empreinte"].upper() in presents]
            if not utilisables:
                raise ErreurProtection(
                    "aucun des certificats associés à la base n'est disponible : insérez votre "
                    "carte (certificat attendu : " + ", ".join(
                        f"{e['sujet']} émis par {e['emetteur']}, expirant le {e['expire']}"
                        for e in enveloppes) + ")")
            erreurs = []
            for e in utilisables:
                try:
                    cle = desenvelopper(e["cle"], e["empreinte"])
                    break
                except ErreurProtection as err:
                    erreurs.append(str(err))
            else:
                raise ErreurProtection(erreurs[0])
            with open(self.fichier, "rb") as f:
                octets = dechiffrer(f.read(), cle)
            connexion = sqlite3.connect(":memory:", check_same_thread=False)
            connexion.deserialize(octets)
            self.cle, self.connexion, self.raison_verrouillage = cle, connexion, None

    def enregistrer(self):
        """Réécrit le fichier chiffré à partir de la base en mémoire."""
        with self.verrou:
            if self.deverrouille:
                ecrire_atomique(self.fichier, chiffrer(self.connexion.serialize(), self.cle))

    def verrouiller(self, raison=None):
        with self.verrou:
            if not self.deverrouille:
                return
            self.enregistrer()
            self.connexion.close()
            self.cle, self.connexion = None, None
            self.raison_verrouillage = raison

    def creer_connexion(self):
        """Fournie à SQLAlchemy : la connexion à la base en mémoire."""
        if not self.deverrouille:
            raise ErreurProtection("base verrouillée")
        return self.connexion

    # Mise en place / retrait / certificats
    def activer(self, chemin_base, certificat, autres_bases=()):
        """Chiffre la base en clair existante avec une nouvelle clé liée au certificat.
        Rien n'est effacé tant que la carte n'a pas prouvé (code PIN) qu'elle sait relire la clé
        et que le fichier chiffré n'a pas été relu avec succès ; en cas d'échec, tout est annulé."""
        cle = os.urandom(32)
        enveloppe = self.nouvelle_enveloppe(cle, certificat)
        if desenvelopper(enveloppe["cle"], certificat["empreinte"]) != cle:
            raise ErreurProtection("la carte n'a pas restitué la clé : protection non activée")
        # Mise de côté de la base : échoue proprement si un autre programme l'a ouverte
        en_cours = chemin_base + ".en_cours"
        presente = os.path.exists(chemin_base)
        if presente:
            try:
                os.replace(chemin_base, en_cours)
            except OSError:
                raise ErreurProtection("la base est ouverte par un autre programme : fermez-le "
                                       "et réessayez")
        try:
            if presente:
                octets = base_vers_octets(en_cours)
            else:
                vide = sqlite3.connect(":memory:")
                octets = vide.serialize()
                vide.close()
            ecrire_atomique(self.fichier, chiffrer(octets, cle))
            with open(self.fichier, "rb") as f:  # contrôle de relecture
                if dechiffrer(f.read(), cle) != octets:
                    raise ErreurProtection("contrôle de relecture du fichier chiffré échoué")
            self._ecrire_enveloppes([enveloppe])
        except Exception:
            for chemin in (self.fichier, self.fichier_cle):
                if os.path.exists(chemin):
                    os.remove(chemin)
            if presente:
                os.replace(en_cours, chemin_base)
            raise
        if presente:
            effacer(en_cours)
        erreurs = []
        for chemin in autres_bases:  # sauvegardes et anciennes bases en clair
            try:
                ecrire_atomique(chemin + ".chiffre", chiffrer(base_vers_octets(chemin), cle))
                effacer(chemin)
            except Exception as e:
                erreurs.append(f"{os.path.basename(chemin)} ({e})")
        return erreurs

    def desactiver(self, chemin_base, sauvegardes=()):
        """Réécrit la base en clair (base déverrouillée requise) et retire la protection."""
        with self.verrou:
            if not self.deverrouille:
                raise ErreurProtection("déverrouillez d'abord la base")
            temporaire = chemin_base + ".tmp"
            try:
                for chemin in (temporaire, chemin_base):
                    if os.path.exists(chemin):
                        os.remove(chemin)
                octets_vers_fichier(self.connexion.serialize(), temporaire)
                os.replace(temporaire, chemin_base)
            except OSError as e:
                raise ErreurProtection(f"écriture de la base en clair impossible ({e})")
            for chemin in sauvegardes:  # sauvegardes chiffrées remises en clair
                clair = chemin[:-len(".chiffre")]
                if os.path.exists(clair):
                    os.remove(clair)
                with open(chemin, "rb") as f:
                    octets_vers_fichier(dechiffrer(f.read(), self.cle), clair)
                os.remove(chemin)
            self.connexion.close()
            self.cle, self.connexion = None, None
            os.remove(self.fichier)
            os.remove(self.fichier_cle)

    def ajouter_certificat(self, certificat):
        """Associe un certificat supplémentaire (ex. nouvelle carte) : base déverrouillée requise."""
        with self.verrou:
            if not self.deverrouille:
                raise ErreurProtection("déverrouillez d'abord la base")
            enveloppes = [e for e in self.enveloppes()
                          if e["empreinte"].upper() != certificat["empreinte"].upper()]
            enveloppes.append(self.nouvelle_enveloppe(self.cle, certificat))
            self._ecrire_enveloppes(enveloppes)

    def retirer_certificat(self, empreinte):
        enveloppes = self.enveloppes()
        restantes = [e for e in enveloppes if e["empreinte"].upper() != empreinte.upper()]
        if not restantes:
            raise ErreurProtection("impossible de retirer le dernier certificat associé")
        self._ecrire_enveloppes(restantes)

    def surveiller_carte(self, intervalle=2.0):
        """Verrouille la base dès que la carte est retirée du lecteur."""
        def boucle():
            arret = threading.Event()
            while not arret.wait(intervalle):
                if self.deverrouille and carte_presente() is False:
                    self.verrouiller("carte retirée du lecteur")
        threading.Thread(target=boucle, daemon=True, name="surveillance-carte").start()
