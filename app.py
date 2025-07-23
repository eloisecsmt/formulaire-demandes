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
        
        # Upload des fichiers vers Swiss Transfer
        download_link = None
        if files and any(file.filename for file in files.values() if file):
            download_link = upload_to_swiss_transfer(files, f"{nom} {prenom} - {type_demande}")
        
        # Ajouter le lien de téléchargement au corps du mail
        if download_link:
            corps += f"\n\n=== DOCUMENTS JOINTS ===\n"
            file_count = len([f for f in files.values() if f.filename])
            corps += f"📎 Tous les documents ({file_count} fichiers) :\n"
            corps += f"{download_link}\n\n"
            corps += f"⚠️ Ce lien expire automatiquement dans 30 jours"
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

def upload_to_swiss_transfer(files, transfer_title):
    """Upload les fichiers vers Swiss Transfer et retourne le lien de téléchargement"""
    
    try:
        # Swiss Transfer utilise une API simple basée sur des requêtes multipart
        
        # Préparer les fichiers pour l'upload
        files_data = []
        form_data = {
            'title': transfer_title,
            'message': 'Documents joints à la demande client',
            'lang': 'fr',
            'duration': '30'  # 30 jours
        }
        
        # Ajouter chaque fichier
        file_index = 0
        for key, file in files.items():
            if file and file.filename:
                # Lire le contenu du fichier
                file_content = file.read()
                files_data.append(
                    ('files[]', (file.filename, file_content, file.content_type or 'application/octet-stream'))
                )
                file_index += 1
        
        if not files_data:
            raise Exception("Aucun fichier à uploader")
        
        # Faire la requête vers Swiss Transfer
        response = requests.post(
            'https://www.swisstransfer.com/api/upload',
            data=form_data,
            files=files_data,
            timeout=300  # 5 minutes de timeout pour les gros fichiers
        )
        
        if response.status_code == 200:
            try:
                result = response.json()
                if 'downloadUrl' in result:
                    return result['downloadUrl']
                elif 'uuid' in result:
                    # Construire l'URL de téléchargement
                    return f"https://www.swisstransfer.com/d/{result['uuid']}"
                else:
                    raise Exception("Réponse inattendue de Swiss Transfer")
            except json.JSONDecodeError:
                # Si la réponse n'est pas du JSON, essayer d'extraire l'URL
                response_text = response.text
                if 'swisstransfer.com/d/' in response_text:
                    # Extraire l'URL de la réponse HTML
                    match = re.search(r'https://www\.swisstransfer\.com/d/([a-zA-Z0-9\-]+)', response_text)
                    if match:
                        return match.group(0)
                
                raise Exception("Impossible d'extraire l'URL de téléchargement")
        else:
            raise Exception(f"Erreur HTTP {response.status_code}: {response.text}")
            
    except requests.exceptions.Timeout:
        raise Exception("Timeout lors de l'upload - fichiers trop volumineux ou connexion lente")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Erreur réseau: {str(e)}")
    except Exception as e:
        print(f"Erreur Swiss Transfer: {str(e)}")
        # En cas d'erreur, essayer la méthode alternative
        return upload_to_swiss_transfer_alternative(files, transfer_title)

def upload_to_swiss_transfer_alternative(files, transfer_title):
    """Méthode alternative utilisant l'API officielle Swiss Transfer"""
    
    try:
        # Utiliser l'API officielle de Swiss Transfer
        # Documentation: https://github.com/infomaniak/swisstransfer
        
        # Étape 1: Créer un container
        container_data = {
            'duration': 30,  # durée en jours
            'downloadLimit': 100,  # limite de téléchargements
            'message': 'Documents joints à la demande client',
            'password': ''
        }
        
        container_response = requests.post(
            'https://api.swisstransfer.com/api/containers',
            json=container_data,
            headers={'Content-Type': 'application/json'}
        )
        
        if not container_response.ok:
            raise Exception(f"Erreur création container: {container_response.status_code}")
        
        container_result = container_response.json()
        container_uuid = container_result.get('uuid')
        upload_host = container_result.get('uploadHost', 'upload.swisstransfer.com')
        
        # Étape 2: Upload des fichiers
        for key, file in files.items():
            if file and file.filename:
                file_content = file.read()
                
                files_payload = {
                    'file': (file.filename, file_content, file.content_type or 'application/octet-stream')
                }
                
                upload_response = requests.post(
                    f'https://{upload_host}/api/containers/{container_uuid}/files',
                    files=files_payload,
                    timeout=300
                )
                
                if not upload_response.ok:
                    raise Exception(f"Erreur upload {file.filename}: {upload_response.status_code}")
        
        # Étape 3: Finaliser le transfert
        finalize_response = requests.post(
            f'https://api.swisstransfer.com/api/containers/{container_uuid}/finish'
        )
        
        if finalize_response.ok:
            # Construire l'URL de téléchargement
            download_url = f"https://www.swisstransfer.com/d/{container_uuid}"
            return download_url
        else:
            raise Exception(f"Erreur finalisation: {finalize_response.status_code}")
            
    except Exception as e:
        print(f"Erreur API alternative: {str(e)}")
        # En dernier recours, utiliser la simulation
        return upload_to_swiss_transfer_simple(files, transfer_title)

def upload_to_swiss_transfer_simple(files, transfer_title):
    """Version de fallback - simulation en cas d'échec des API"""
    
    file_count = len([f for f in files.values() if f and f.filename])
    
    # Si toutes les méthodes échouent, au moins informer l'utilisateur
    print(f"FALLBACK: Simulation pour {file_count} fichiers")
    
    # Simuler un ID de transfert pour que le workflow continue
    fake_id = str(uuid.uuid4())[:8]
    
    # Retourner un message d'erreur informatif
    return f"❌ ERREUR UPLOAD AUTOMATIQUE ❌\n\nVeuillez uploader manuellement vos {file_count} fichiers sur:\nhttps://www.swisstransfer.com\n\nEt joindre le lien dans votre email."

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
