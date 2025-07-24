from flask import Flask, request, send_from_directory, jsonify
from flask_cors import CORS
import requests
import os
from datetime import datetime
import tempfile
import json
import uuid
import base64

app = Flask(__name__)
CORS(app)

# Configuration Uploadcare
EMAIL_DESTINATAIRE = os.environ.get('EMAIL_DESTINATAIRE', 'eloise.csmt@gmail.com')
UPLOADCARE_PUBLIC_KEY = os.environ.get('UPLOADCARE_PUBLIC_KEY', '5a750c530fdc3fe958c8')
UPLOADCARE_SECRET_KEY = os.environ.get('UPLOADCARE_SECRET_KEY', 'ad1a9f46fa1c732bfebc')

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
        
        # Upload des fichiers vers Uploadcare
        uploaded_files = []
        if files and any(file.filename for file in files.values() if file):
            transfer_title = f"{nom} {prenom} - {type_demande}"
            uploaded_files = upload_to_uploadcare(files, transfer_title)
        
        # Ajouter les liens de téléchargement au corps du mail
        if uploaded_files and not any(file.get('error') for file in uploaded_files):
            corps += f"\n\n=== DOCUMENTS JOINTS ===\n"
            file_count = len(uploaded_files)
            corps += f"📎 Documents uploadés ({file_count} fichiers) :\n\n"
            
            for i, file_info in enumerate(uploaded_files, 1):
                corps += f"{i}. {file_info['filename']}\n"
                corps += f"   Lien: {file_info['url']}\n"
                corps += f"   Taille: {file_info['size']}\n\n"
            
            corps += f"🔒 Hébergé de manière sécurisée sur Uploadcare (conforme RGPD)\n"
            corps += f"🌍 Données stockées en Europe\n"
            corps += f"⚠️ Liens permanents - archivage sécurisé"
            
        elif uploaded_files and any(file.get('error') for file in uploaded_files):
            # En cas d'erreur partielle
            corps += f"\n\n=== DOCUMENTS JOINTS ===\n"
            
            successful_files = [f for f in uploaded_files if not f.get('error')]
            failed_files = [f for f in uploaded_files if f.get('error')]
            
            if successful_files:
                corps += f"✅ FICHIERS UPLOADÉS ({len(successful_files)}):\n"
                for file_info in successful_files:
                    corps += f"• {file_info['filename']}: {file_info['url']}\n"
                corps += "\n"
            
            if failed_files:
                corps += f"❌ FICHIERS EN ÉCHEC ({len(failed_files)}):\n"
                for file_info in failed_files:
                    corps += f"• {file_info['filename']}: {file_info['error']}\n"
                corps += "\nVeuillez réessayer l'upload de ces fichiers.\n"
                
        else:
            corps += "\n\n=== DOCUMENTS JOINTS ===\nAucun document joint"
        
        # Générer le lien mailto
        mailto_url = generer_mailto(sujet, corps)
        
        return jsonify({
            "status": "success", 
            "message": "Documents uploadés sur Uploadcare!",
            "mailto_url": mailto_url,
            "uploaded_files": uploaded_files
        })
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"status": "error", "message": f"Erreur lors de l'envoi: {str(e)}"}), 500

def upload_to_uploadcare(files, transfer_title):
    """Upload les fichiers vers Uploadcare et retourne les informations des fichiers"""
    
    if not UPLOADCARE_SECRET_KEY:
        return [{"error": "Clé API privée Uploadcare manquante", "filename": "Configuration"}]
    
    uploaded_files = []
    
    try:
        for key, file in files.items():
            if file and file.filename:
                try:
                    # Lire le contenu du fichier
                    file_content = file.read()
                    file.seek(0)  # Remettre le curseur au début
                    file_size = len(file_content)
                    
                    # Upload direct vers Uploadcare
                    upload_result = upload_file_to_uploadcare(
                        file_content, 
                        file.filename, 
                        file.content_type or 'application/octet-stream'
                    )
                    
                    if upload_result.get('success'):
                        uploaded_files.append({
                            'filename': file.filename,
                            'url': upload_result['url'],
                            'uuid': upload_result['uuid'],
                            'size': format_file_size(file_size),
                            'content_type': file.content_type
                        })
                    else:
                        uploaded_files.append({
                            'filename': file.filename,
                            'error': upload_result.get('error', 'Erreur inconnue')
                        })
                        
                except Exception as e:
                    uploaded_files.append({
                        'filename': file.filename,
                        'error': f"Erreur upload: {str(e)}"
                    })
        
        return uploaded_files
        
    except Exception as e:
        print(f"Erreur générale Uploadcare: {str(e)}")
        return [{"error": f"Erreur générale: {str(e)}", "filename": "System"}]

def upload_file_to_uploadcare(file_content, filename, content_type):
    """Upload un fichier individuel vers Uploadcare"""
    
    try:
        # Méthode 1: Upload direct API
        files_payload = {
            'UPLOADCARE_PUB_KEY': (None, UPLOADCARE_PUBLIC_KEY),
            'file': (filename, file_content, content_type)
        }
        
        response = requests.post(
            'https://upload.uploadcare.com/base/',
            files=files_payload,
            timeout=300  # 5 minutes
        )
        
        if response.status_code == 200:
            result = response.json()
            
            if 'file' in result:
                file_uuid = result['file']
                
                # Construire l'URL de téléchargement
                download_url = f"https://ucarecdn.com/{file_uuid}/{filename}"
                
                return {
                    'success': True,
                    'uuid': file_uuid,
                    'url': download_url
                }
            else:
                return {
                    'success': False,
                    'error': 'UUID de fichier manquant dans la réponse'
                }
        else:
            return {
                'success': False,
                'error': f"Erreur HTTP {response.status_code}: {response.text}"
            }
            
    except requests.exceptions.Timeout:
        return upload_file_to_uploadcare_multipart(file_content, filename, content_type)
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f"Erreur réseau: {str(e)}"
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Erreur: {str(e)}"
        }

def upload_file_to_uploadcare_multipart(file_content, filename, content_type):
    """Méthode alternative avec upload multipart pour gros fichiers"""
    
    try:
        # Pour les gros fichiers, utiliser l'API multipart
        if len(file_content) > 10 * 1024 * 1024:  # > 10MB
            
            # Étape 1: Initier l'upload multipart
            init_data = {
                'UPLOADCARE_PUB_KEY': UPLOADCARE_PUBLIC_KEY,
                'filename': filename,
                'size': len(file_content),
                'content_type': content_type
            }
            
            auth_header = generate_uploadcare_auth('POST', '/multipart/start/', init_data)
            headers = {
                'Authorization': auth_header,
                'Content-Type': 'application/json'
            }
            
            init_response = requests.post(
                'https://upload.uploadcare.com/multipart/start/',
                json=init_data,
                headers=headers,
                timeout=60
            )
            
            if init_response.status_code == 200:
                init_result = init_response.json()
                parts = init_result.get('parts', [])
                uuid = init_result.get('uuid')
                
                # Étape 2: Upload des parts
                for part in parts:
                    part_url = part['url']
                    part_size = part['size']
                    part_number = part['partNumber']
                    
                    # Calculer l'offset pour cette part
                    offset = (part_number - 1) * part_size
                    part_data = file_content[offset:offset + part_size]
                    
                    part_response = requests.put(
                        part_url,
                        data=part_data,
                        timeout=300
                    )
                    
                    if part_response.status_code not in [200, 201]:
                        return {
                            'success': False,
                            'error': f"Erreur upload part {part_number}: {part_response.status_code}"
                        }
                
                # Étape 3: Finaliser l'upload
                complete_data = {'UPLOADCARE_PUB_KEY': UPLOADCARE_PUBLIC_KEY, 'uuid': uuid}
                complete_auth = generate_uploadcare_auth('POST', '/multipart/complete/', complete_data)
                
                complete_response = requests.post(
                    'https://upload.uploadcare.com/multipart/complete/',
                    json=complete_data,
                    headers={'Authorization': complete_auth},
                    timeout=60
                )
                
                if complete_response.status_code == 200:
                    download_url = f"https://ucarecdn.com/{uuid}/{filename}"
                    return {
                        'success': True,
                        'uuid': uuid,
                        'url': download_url
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Erreur finalisation: {complete_response.status_code}"
                    }
            else:
                return {
                    'success': False,
                    'error': f"Erreur initialisation multipart: {init_response.status_code}"
                }
        else:
            # Fichier trop petit pour multipart, erreur précédente
            return {
                'success': False,
                'error': "Échec upload direct et fichier trop petit pour multipart"
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f"Erreur multipart: {str(e)}"
        }

def generate_uploadcare_auth(method, uri, data=None):
    """Génère l'en-tête d'authentification pour Uploadcare"""
    
    import hashlib
    import hmac
    from datetime import datetime
    
    try:
        # Timestamp actuel
        timestamp = str(int(datetime.now().timestamp()))
        
        # Construire la chaîne à signer
        content_md5 = ""
        content_type = "application/json" if data else ""
        
        if data and isinstance(data, dict):
            import json
            data_str = json.dumps(data, sort_keys=True)
            content_md5 = hashlib.md5(data_str.encode()).hexdigest()
        
        sign_string = f"{method}\n{content_md5}\n{content_type}\n{timestamp}\n{uri}"
        
        # Signer avec HMAC-SHA1
        signature = hmac.new(
            UPLOADCARE_SECRET_KEY.encode(),
            sign_string.encode(),
            hashlib.sha1
        ).hexdigest()
        
        return f"Uploadcare {UPLOADCARE_PUBLIC_KEY}:{signature}:{timestamp}"
        
    except Exception as e:
        print(f"Erreur génération auth: {str(e)}")
        return f"Uploadcare {UPLOADCARE_PUBLIC_KEY}:error:0"

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
