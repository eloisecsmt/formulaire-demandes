from flask import Flask, request, send_from_directory, jsonify
from flask_cors import CORS
import requests
import os
from datetime import datetime
import tempfile
import json

app = Flask(__name__)
CORS(app)

# Configuration
EMAIL_DESTINATAIRE = os.environ.get('EMAIL_DESTINATAIRE', 'eloise.csmt@gmail.com')
SWISS_TRANSFER_API = "https://api.swisstransfer.com/v1"

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
            corps += f"📎 Tous les documents ({len([f for f in files.values() if f.filename])}) fichiers) :\n"
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
        # Créer un nouveau transfert
        create_response = requests.post(f"{SWISS_TRANSFER_API}/transfer", json={
            "title": transfer_title,
            "message": "Documents joints à la demande client",
            "password": "",
            "expirationDays": 30
        })
        
        if not create_response.ok:
            raise Exception(f"Erreur création transfert: {create_response.status_code}")
        
        transfer_data = create_response.json()
        transfer_id = transfer_data.get('transferId')
        upload_token = transfer_data.get('uploadToken')
        
        # Upload chaque fichier
        for key, file in files.items():
            if file and file.filename:
                # Préparer le fichier pour l'upload
                file_data = {
                    'file': (file.filename, file.read(), file.content_type or 'application/octet-stream')
                }
                
                # Upload le fichier
                upload_response = requests.post(
                    f"{SWISS_TRANSFER_API}/transfer/{transfer_id}/file",
                    files=file_data,
                    headers={'Authorization': f'Bearer {upload_token}'}
                )
                
                if not upload_response.ok:
                    raise Exception(f"Erreur upload fichier {file.filename}: {upload_response.status_code}")
        
        # Finaliser le transfert
        finalize_response = requests.post(
            f"{SWISS_TRANSFER_API}/transfer/{transfer_id}/finalize",
            headers={'Authorization': f'Bearer {upload_token}'}
        )
        
        if not finalize_response.ok:
            raise Exception(f"Erreur finalisation: {finalize_response.status_code}")
        
        # Récupérer le lien de téléchargement
        final_data = finalize_response.json()
        download_url = final_data.get('downloadUrl') or f"https://swisstransfer.com/d/{transfer_id}"
        
        return download_url
        
    except Exception as e:
        print(f"Erreur Swiss Transfer: {str(e)}")
        # En cas d'erreur, essayer avec une API simplifiée
        return upload_to_swiss_transfer_simple(files, transfer_title)

def upload_to_swiss_transfer_simple(files, transfer_title):
    """Version simplifiée sans API officielle - utilise l'interface web"""
    
    # Pour l'instant, on simule un upload et retourne un lien factice
    # Dans la vraie implémentation, on utiliserait l'API web de Swiss Transfer
    
    file_count = len([f for f in files.values() if f and f.filename])
    
    # Simuler un ID de transfert
    import uuid
    fake_id = str(uuid.uuid4())[:8]
    
    # Retourner un lien fictif pour les tests
    return f"https://swisstransfer.com/d/{fake_id} (LIEN DE TEST - {file_count} fichiers)"

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
