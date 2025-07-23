from flask import Flask, request, send_from_directory, jsonify
from flask_cors import CORS
import requests
import os
from datetime import datetime
import tempfile
import json
import uuid
import re

app = Flask(__name__)
CORS(app)

# Configuration
EMAIL_DESTINATAIRE = os.environ.get('EMAIL_DESTINATAIRE', 'eloise.csmt@gmail.com')
SMASH_API_TOKEN = os.environ.get('SMASH_API_TOKEN', '')  # Votre clé API Smash
SMASH_REGION = os.environ.get('SMASH_REGION', 'eu-west-3')  # Région la plus proche de la France

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
        
        sujet = f"Demande {type_demande.title()} - {nom} {prenom} - {date_demande}"
        
        # Construire le corps du mail
        corps = generer_corps_email(data)
        
        # Upload des fichiers vers Smash
        download_link = None
        if files and any(file.filename for file in files.values() if file):
            transfer_title = f"{nom} {prenom} - {type_demande}"
            download_link = upload_to_smash(files, transfer_title)
        
        # Ajouter le lien de téléchargement au corps du mail
        if download_link and not download_link.startswith('❌'):
            corps += f"\n\n=== DOCUMENTS JOINTS ===\n"
            file_count = len([f for f in files.values() if f.filename])
            corps += f"📎 Tous les documents ({file_count} fichiers) :\n"
            corps += f"{download_link}\n\n"
            corps += f"⚠️ Ce lien expire automatiquement dans 30 jours"
        elif download_link:
            # En cas d'erreur d'upload
            corps += f"\n\n=== DOCUMENTS JOINTS ===\n{download_link}"
        else:
            corps += "\n\n=== DOCUMENTS JOINTS ===\nAucun document joint"
        
        # Générer le lien mailto
        mailto_url = generer_mailto(sujet, corps)
        
        return jsonify({
            "status": "success", 
            "message": "Lien de téléchargement généré!",
            "mailto_url": mailto_url,
            "download_link": download_link
        })
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"status": "error", "message": f"Erreur lors de l'envoi: {str(e)}"}), 500

def upload_to_smash(files, transfer_title):
    """Upload les fichiers vers Smash et retourne le lien de téléchargement"""
    
    if not SMASH_API_TOKEN:
        return "❌ ERREUR: Clé API Smash manquante\n\nVeuillez configurer SMASH_API_TOKEN dans les variables d'environnement."
    
    try:
        # Préparer les fichiers pour l'upload
        upload_files = []
        file_names = []
        
        for key, file in files.items():
            if file and file.filename:
                # Lire le contenu du fichier
                file_content = file.read()
                file.seek(0)  # Remettre le curseur au début
                
                # Ajouter à la liste des fichiers à uploader
                upload_files.append(('files', (file.filename, file_content, file.content_type or 'application/octet-stream')))
                file_names.append(file.filename)
        
        if not upload_files:
            raise Exception("Aucun fichier à uploader")
        
        # En attendant la documentation complète de l'API REST, 
        # nous devons reproduire le comportement du SDK Node.js
        # Étape 1: Créer un transfert
        transfer_data = {
            'title': transfer_title,
            'description': 'Documents joints à la demande client',
            'availabilityDuration': 2592000,  # 30 jours en secondes
            'region': SMASH_REGION
        }
        
        headers = {
            'Authorization': f'Bearer {SMASH_API_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Créer le transfert d'abord
        create_response = requests.post(
            'https://api.fromsmash.com/transfers',
            json=transfer_data,
            headers=headers,
            timeout=60
        )
        
        if create_response.status_code == 201:
            transfer_info = create_response.json()
            transfer_id = transfer_info.get('id')
            
            if not transfer_id:
                raise Exception("Impossible de créer le transfert")
            
            # Étape 2: Uploader les fichiers
            upload_headers = {
                'Authorization': f'Bearer {SMASH_API_TOKEN}'
            }
            
            upload_response = requests.post(
                f'https://api.fromsmash.com/transfers/{transfer_id}/files',
                files=upload_files,
                headers=upload_headers,
                timeout=600  # 10 minutes pour les gros fichiers
            )
            
            if upload_response.status_code in [200, 201]:
                # Étape 3: Finaliser le transfert
                finalize_response = requests.post(
                    f'https://api.fromsmash.com/transfers/{transfer_id}/finish',
                    headers=headers,
                    timeout=60
                )
                
                if finalize_response.status_code == 200:
                    # Récupérer l'URL de téléchargement
                    transfer_url = transfer_info.get('transferUrl') or f"https://fromsmash.com/{transfer_id}"
                    return transfer_url
                else:
                    raise Exception(f"Erreur finalisation: {finalize_response.status_code}")
            else:
                raise Exception(f"Erreur upload fichiers: {upload_response.status_code} - {upload_response.text}")
        else:
            raise Exception(f"Erreur création transfert: {create_response.status_code} - {create_response.text}")
            
    except requests.exceptions.Timeout:
        return upload_to_smash_fallback(files, transfer_title, "timeout")
    except requests.exceptions.RequestException as e:
        return upload_to_smash_fallback(files, transfer_title, f"réseau: {str(e)}")
    except Exception as e:
        print(f"Erreur Smash: {str(e)}")
        return upload_to_smash_fallback(files, transfer_title, str(e))

def upload_to_smash_fallback(files, transfer_title, error_reason):
    """Méthode de fallback en cas d'échec de l'API Smash"""
    
    file_count = len([f for f in files.values() if f and f.filename])
    
    return f"""❌ ERREUR UPLOAD AUTOMATIQUE ❌

Raison: {error_reason}

Veuillez uploader manuellement vos {file_count} fichiers sur:
https://fromsmash.com

Puis joindre le lien dans votre email.

Fichiers à uploader:
{chr(10).join([f"- {f.filename}" for f in files.values() if f and f.filename])}"""

def generer_corps_email(data):
    """Génère le contenu formaté de l'email"""
    
    type_demande = data.get('type', 'Non spécifié').upper()
    
    corps = f"""=== DEMANDE DE {type_demande} ===
Date: {data.get('dateDemande', 'Non spécifiée')}
Client: {data.get('nom', '')} {data.get('prenom', '')}
Urgence: {data.get('urgence', 'Normal')}
Origine: {data.get('origine', 'Non spécifiée')}
Mode signature: {data.get('modeSignature', 'Non spécifié')}
Prochain RDV: {data.get('dateRdv', 'Non programmé')}

"""

    # Informations spécifiques selon le type
    if data.get('type') == 'versement':
        corps += f"""=== INFORMATIONS FINANCIÈRES ===
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

    corps += f"\n---\nDemande générée automatiquement le {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
    
    return corps

def generer_mailto(sujet, corps):
    """Génère l'URL mailto"""
    
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
