from flask import Flask, request, send_from_directory, jsonify
from flask_cors import CORS
import smtplib
import os
from datetime import datetime
import json
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

app = Flask(__name__)
CORS(app)

# Configuration Email pour ZeenDoc
EMAIL_DESTINATAIRE = os.environ.get('EMAIL_DESTINATAIRE', 'eloise.csmt@gmail.com')
ZEENDOC_EMAIL = os.environ.get('ZEENDOC_EMAIL', 'repos@zeendoc.com')  # Adresse ZeenDoc

# Configuration SMTP (optionnelle pour envoi automatique)
SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

# Servir les fichiers statiques (HTML, CSS)
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/styles.css')
def css():
    return send_from_directory('.', 'styles.css')

@app.route('/envoyer-demande', methods=['POST'])
def envoyer_demande():
    try:
        # Récupérer les données du formulaire
        data = request.form.to_dict()
        files = request.files
        
        # Construire le sujet
        type_demande = data.get('type', 'Demande')
        nom = data.get('nom', '')
        prenom = data.get('prenom', '')
        date_demande = data.get('dateDemande', datetime.now().strftime('%d/%m/%Y'))
        
        sujet_principal = f"Demande {type_demande.title()} - {nom} {prenom} - {date_demande}"
        sujet_zeendoc = f"[ZEENDOC] Documents - {nom} {prenom} - {type_demande.title()}"
        
        # Construire le corps du mail principal
        corps_principal = generer_corps_email(data)
        
        # Préparer les fichiers pour ZeenDoc
        fichiers_pieces = []
        if files and any(file.filename for file in files.values() if file):
            fichiers_pieces = preparer_fichiers_zeendoc(files, nom, prenom, type_demande)
        
        # Générer les URLs mailto
        mailto_principal = generer_mailto(sujet_principal, corps_principal)
        mailto_zeendoc = None
        
        if fichiers_pieces:
            corps_zeendoc = generer_corps_zeendoc(data, fichiers_pieces)
            mailto_zeendoc = generer_mailto_zeendoc(sujet_zeendoc, corps_zeendoc)
        
        # Optionnel : Envoi automatique via SMTP si configuré
        envoi_auto_reussi = False
        if SMTP_SERVER and SMTP_USERNAME and fichiers_pieces:
            try:
                envoi_auto_reussi = envoyer_email_zeendoc_auto(
                    sujet_zeendoc, 
                    corps_zeendoc, 
                    fichiers_pieces
                )
            except Exception as e:
                print(f"Erreur envoi automatique: {str(e)}")
        
        return jsonify({
            "status": "success", 
            "message": "Demande préparée avec succès!",
            "mailto_principal": mailto_principal,
            "mailto_zeendoc": mailto_zeendoc,
            "fichiers_count": len(fichiers_pieces),
            "envoi_auto": envoi_auto_reussi,
            "fichiers_info": [f["nom"] for f in fichiers_pieces]
        })
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"status": "error", "message": f"Erreur lors de la préparation: {str(e)}"}), 500

def preparer_fichiers_zeendoc(files, nom, prenom, type_demande):
    """Prépare les fichiers pour l'envoi vers ZeenDoc"""
    
    fichiers_pieces = []
    
    for key, file in files.items():
        if file and file.filename:
            try:
                # Lire le contenu du fichier
                file_content = file.read()
                file.seek(0)  # Remettre le curseur au début
                
                # Générer un nom de fichier standardisé
                nom_standardise = generer_nom_fichier_zeendoc(
                    file.filename, 
                    nom, 
                    prenom, 
                    type_demande,
                    key
                )
                
                fichiers_pieces.append({
                    'nom': nom_standardise,
                    'nom_original': file.filename,
                    'contenu': file_content,
                    'type_mime': file.content_type or 'application/octet-stream',
                    'taille': len(file_content),
                    'categorie': obtenir_categorie_document(key)
                })
                
            except Exception as e:
                print(f"Erreur préparation fichier {file.filename}: {str(e)}")
                continue
    
    return fichiers_pieces

def generer_nom_fichier_zeendoc(nom_fichier, nom, prenom, type_demande, doc_id):
    """Génère un nom de fichier standardisé pour ZeenDoc"""
    
    # Extraire l'extension
    extension = ""
    if '.' in nom_fichier:
        extension = nom_fichier.split('.')[-1].lower()
    
    # Mapper les IDs de documents vers des noms courts
    mapping_docs = {
        'majProfil_doc': 'MAJ_Profil',
        'etudeSignee_doc': 'Etude_Signee',
        'cniValide_doc': 'CNI',
        'justifDom_doc': 'Justif_Domicile',
        'ribJour_doc': 'RIB',
        'justifProvenance_doc': 'Justif_Provenance',
        'justifDomImpot_doc': 'Justif_Dom_Impot',
        'clauseBeneficiaire_doc': 'Clause_Beneficiaire',
        'majProfilRachat_doc': 'MAJ_Profil',
        'ribJourRachat_doc': 'RIB',
        'majProfilArbitrage_doc': 'MAJ_Profil',
        'ficheRenseignement_doc': 'Fiche_Renseignement',
        'profilClientSigne_doc': 'Profil_Client',
        'cartoClientSigne_doc': 'Cartographie',
        'lettreMiseRelation_doc': 'Lettre_Relation',
        'filSigne_doc': 'FIL',
        'justifDomCreation_doc': 'Justif_Domicile',
        'cniValideCreation_doc': 'CNI'
    }
    
    doc_type = mapping_docs.get(doc_id, 'Document')
    
    # Format: TYPE_DEMANDE_NOM_Prenom_TypeDocument_YYYYMMDD.ext
    date_str = datetime.now().strftime('%Y%m%d')
    nom_final = f"{type_demande.upper()}_{nom.upper()}_{prenom}_{doc_type}_{date_str}"
    
    if extension:
        nom_final += f".{extension}"
    
    return nom_final

def obtenir_categorie_document(doc_id):
    """Retourne la catégorie du document pour ZeenDoc"""
    
    categories = {
        'majProfil_doc': 'Profil Client',
        'etudeSignee_doc': 'Etudes',
        'cniValide_doc': 'Identité',
        'justifDom_doc': 'Justificatifs',
        'ribJour_doc': 'Bancaire',
        'justifProvenance_doc': 'Justificatifs',
        'justifDomImpot_doc': 'Justificatifs',
        'clauseBeneficiaire_doc': 'Bénéficiaires',
        'majProfilRachat_doc': 'Profil Client',
        'ribJourRachat_doc': 'Bancaire',
        'majProfilArbitrage_doc': 'Profil Client',
        'ficheRenseignement_doc': 'Profil Client',
        'profilClientSigne_doc': 'Profil Client',
        'cartoClientSigne_doc': 'Cartographie',
        'lettreMiseRelation_doc': 'Relation Client',
        'filSigne_doc': 'Documents Légaux',
        'justifDomCreation_doc': 'Justificatifs',
        'cniValideCreation_doc': 'Identité'
    }
    
    return categories.get(doc_id, 'Général')

def generer_corps_zeendoc(data, fichiers_pieces):
    """Génère le corps de l'email pour ZeenDoc"""
    
    type_demande = data.get('type', 'Non spécifié').upper()
    nom = data.get('nom', '')
    prenom = data.get('prenom', '')
    date_demande = data.get('dateDemande', datetime.now().strftime('%d/%m/%Y'))
    
    corps = f"""=== DÉPÔT AUTOMATIQUE ZEENDOC ===
Type de demande: {type_demande}
Client: {nom} {prenom}
Date: {date_demande}
Nombre de pièces: {len(fichiers_pieces)}

=== CLASSIFICATION DES DOCUMENTS ===
"""

    # Grouper par catégorie
    par_categorie = {}
    for fichier in fichiers_pieces:
        cat = fichier['categorie']
        if cat not in par_categorie:
            par_categorie[cat] = []
        par_categorie[cat].append(fichier)
    
    for categorie, fichiers in par_categorie.items():
        corps += f"\n📁 {categorie.upper()}:\n"
        for fichier in fichiers:
            taille_fmt = format_file_size(fichier['taille'])
            corps += f"  • {fichier['nom']} ({taille_fmt})\n"
    
    corps += f"""

=== INFORMATIONS TECHNIQUES ===
Format de nommage: TYPE_NOM_Prenom_TypeDoc_YYYYMMDD.ext
Origine: Formulaire automatisé de gestion des demandes
Horodatage: {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}

=== INSTRUCTIONS ZEENDOC ===
Ces documents sont à classer automatiquement dans le dossier client:
- Nom du dossier: {nom.upper()} {prenom}
- Type de demande: {type_demande}
- Référence: {type_demande}_{nom.upper()}_{prenom}_{datetime.now().strftime('%Y%m%d')}

Merci de confirmer la réception et le classement.
"""
    
    return corps

def envoyer_email_zeendoc_auto(sujet, corps, fichiers_pieces):
    """Envoie automatiquement l'email vers ZeenDoc via SMTP"""
    
    try:
        # Créer le message
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = ZEENDOC_EMAIL
        msg['Cc'] = EMAIL_DESTINATAIRE  # Copie pour suivi
        msg['Subject'] = sujet
        
        # Ajouter le corps du message
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))
        
        # Ajouter les pièces jointes
        for fichier in fichiers_pieces:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(fichier['contenu'])
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= "{fichier["nom"]}"'
            )
            msg.attach(part)
        
        # Connexion SMTP et envoi
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        
        destinataires = [ZEENDOC_EMAIL, EMAIL_DESTINATAIRE]
        server.send_message(msg, to_addrs=destinataires)
        server.quit()
        
        return True
        
    except Exception as e:
        print(f"Erreur SMTP: {str(e)}")
        return False

def generer_mailto_zeendoc(sujet, corps):
    """Génère l'URL mailto pour ZeenDoc avec copie"""
    
    from urllib.parse import quote
    
    # Nettoyer les caractères spéciaux pour mailto
    corps_clean = corps.replace('é', 'e').replace('è', 'e').replace('à', 'a').replace('ç', 'c')
    corps_clean = corps_clean.replace('ê', 'e').replace('ô', 'o').replace('î', 'i').replace('â', 'a')
    
    # Encoder les paramètres
    sujet_encode = quote(sujet.encode('utf-8'))
    corps_encode = quote(corps_clean.encode('utf-8'))
    
    # mailto avec destinataire principal et copie
    mailto_url = f"mailto:{ZEENDOC_EMAIL}?cc={EMAIL_DESTINATAIRE}&subject={sujet_encode}&body={corps_encode}"
    
    return mailto_url

def format_file_size(bytes_size):
    """Formate la taille des fichiers de manière lisible"""
    
    if bytes_size == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(bytes_size, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_size / p, 2)
    return f"{s} {size_names[i]}"

def generer_corps_email(data):
    """Génère le contenu formaté de l'email principal (inchangé)"""
    
    type_demande = data.get('type', 'Non spécifié').upper()
    
    corps = f"""=== DEMANDE DE {type_demande} ===
Date: {data.get('dateDemande', 'Non spécifiée')}
Client: {data.get('nom', '')} {data.get('prenom', '')}
Nouveau client: {data.get('nouveauClient', 'Non spécifié')}
Urgence: {data.get('urgence', 'Normal')}
Origine: {data.get('origine', 'Non spécifiée')}
Mode signature: {data.get('modeSignature', 'Non spécifié')}
Prochain RDV: {data.get('dateRdv', 'Non programmé')}

"""

    # Informations spécifiques selon le type (code existant)
    if data.get('type') == 'versement':
        corps += f"""=== INFORMATIONS FINANCIÈRES ===
Type de versement: {data.get('typeVersement', 'Non spécifié')}
Montant: {data.get('montantVersement', 'Non spécifié')} €
Allocation: {data.get('allocationVersement', 'Non spécifiée')}
Frais: {data.get('fraisVersement', 'Non spécifiés')}%

=== PROVENANCE ET TRAÇABILITÉ ===
Provenance: {data.get('provenanceFonds', 'Non spécifiée')}
Chemin: {data.get('cheminArgent', 'Non spécifié')}
Justificatif transit: {data.get('justifCompteTransit', 'Non spécifié')}

=== BÉNÉFICIAIRES ===
Type clause: {data.get('clauseBeneficiaireType', 'Non spécifié')}
Spécification: {data.get('clauseBeneficiaireSpec', 'Non spécifiée')}

"""

    elif data.get('type') == 'rachat':
        corps += f"""=== INFORMATIONS FINANCIÈRES ===
Type de rachat: {data.get('typeRachat', 'Non spécifié')}
Montant: {data.get('montantRachat', 'Non spécifié')} €
Fiscalité: {data.get('fiscaliteRachat', 'Non spécifiée')}
Motif: {data.get('motifRachat', 'Non spécifié')}

=== SUPPORTS ET RÉALLOCATION ===
Support à désinvestir: {data.get('supportDesinvestir', 'Non spécifié')}
Pourcentage à réalouer: {data.get('pourcentageReallouer', 'Non spécifié')}%
Nouveau support: {data.get('nouveauSupport', 'Non spécifié')}

"""

    elif data.get('type') == 'arbitrage':
        corps += f"""=== ALLOCATION FINANCIÈRE ===
Montant: {data.get('allocationArbitrage', 'Non spécifié')} €

"""

    corps += f"""

=== DOCUMENTS JOINTS ===
📎 Les pièces justificatives ont été envoyées automatiquement vers ZeenDoc
📧 Adresse de dépôt: {ZEENDOC_EMAIL}
📁 Référence dossier: {data.get('type', '').upper()}_{data.get('nom', '').upper()}_{data.get('prenom', '')}_{datetime.now().strftime('%Y%m%d')}

---
Demande générée automatiquement le {datetime.now().strftime('%d/%m/%Y à %H:%M')}
Demandeur: {data.get('demandeur', 'Non spécifié')}
"""
    
    return corps

def generer_mailto(sujet, corps):
    """Génère l'URL mailto principale"""
    
    from urllib.parse import quote
    
    # Encoder les paramètres pour l'URL
    sujet_encode = quote(sujet)
    corps_encode = quote(corps)
    
    # Générer l'URL mailto
    mailto_url = f"mailto:{EMAIL_DESTINATAIRE}?subject={sujet_encode}&body={corps_encode}"
    
    return mailto_url

if __name__ == '__main__':
    # En production sur Render, utiliser le port fourni par la plateforme
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
