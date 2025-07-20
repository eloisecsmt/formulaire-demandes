from flask import Flask, request, send_from_directory, jsonify, redirect, session, url_for
from flask_cors import CORS
import requests
import os
from datetime import datetime
import tempfile
import base64
import json
from urllib.parse import urlencode

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'votre-clé-secrète-changez-moi')

# Configuration Microsoft Graph API
CLIENT_ID = os.environ.get('MICROSOFT_CLIENT_ID', 'votre-client-id')
CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET', 'votre-client-secret')
TENANT_ID = os.environ.get('MICROSOFT_TENANT_ID', 'common')
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'http://localhost:5000/auth/callback')

# URLs Microsoft Graph
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

# Email destinataire (peut être configuré via variable d'environnement)
EMAIL_DESTINATAIRE = os.environ.get('EMAIL_DESTINATAIRE', 'eloise.csmt@gmail.com')

# Servir les fichiers statiques (HTML, CSS)
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/styles.css')
def css():
    return send_from_directory('.', 'styles.css')

@app.route('/auth/login')
def login():
    """Redirection vers Microsoft pour l'authentification"""
    auth_url = f"{AUTHORITY}/oauth2/v2.0/authorize?" + urlencode({
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': 'https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read',
        'response_mode': 'query'
    })
    return redirect(auth_url)

@app.route('/auth/callback')
def auth_callback():
    """Callback après authentification Microsoft"""
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Code d'autorisation manquant"}), 400
    
    # Échanger le code contre un token
    token_url = f"{AUTHORITY}/oauth2/v2.0/token"
    token_data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, data=token_data)
    token_info = response.json()
    
    if 'access_token' in token_info:
        session['access_token'] = token_info['access_token']
        session['refresh_token'] = token_info.get('refresh_token')
        return redirect('/?auth=success')
    else:
        return jsonify({"error": "Erreur lors de l'obtention du token"}), 400

@app.route('/auth/status')
def auth_status():
    """Vérifier si l'utilisateur est connecté"""
    if 'access_token' in session:
        # Vérifier que le token est encore valide
        headers = {'Authorization': f'Bearer {session["access_token"]}'}
        response = requests.get(f"{GRAPH_API_ENDPOINT}/me", headers=headers)
        
        if response.status_code == 200:
            user_info = response.json()
            return jsonify({
                "authenticated": True,
                "user": {
                    "name": user_info.get('displayName'),
                    "email": user_info.get('mail') or user_info.get('userPrincipalName')
                }
            })
    
    return jsonify({"authenticated": False})

@app.route('/auth/logout')
def logout():
    """Déconnexion"""
    session.clear()
    return redirect('/')

@app.route('/envoyer-demande', methods=['POST'])
def envoyer_demande():
    """Envoyer la demande via Microsoft Graph API"""
    
    # Vérifier l'authentification
    if 'access_token' not in session:
        return jsonify({"status": "error", "message": "Non authentifié. Veuillez vous connecter."}), 401
    
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
        corps = generer_corps_email(data, files)
        
        # Préparer les pièces jointes
        attachments = []
        if files:
            for key, file in files.items():
                if file and file.filename:
                    # Lire le contenu du fichier et l'encoder en base64
                    file_content = file.read()
                    file_base64 = base64.b64encode(file_content).decode('utf-8')
                    
                    attachments.append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": file.filename,
                        "contentBytes": file_base64
                    })
        
        # Envoyer l'email via Graph API
        envoyer_email_graph(sujet, corps, attachments)
        
        return jsonify({"status": "success", "message": "Email envoyé avec succès!"})
        
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return jsonify({"status": "error", "message": f"Erreur lors de l'envoi: {str(e)}"}), 500

def generer_corps_email(data, files):
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

    # Liste des documents joints
    corps += "=== DOCUMENTS JOINTS ===\n"
    if files:
        doc_names = {
            'majProfil_doc': 'MAJ & profil signés',
            'etudeSignee_doc': 'Etude signée',
            'cniValide_doc': 'CNI en cours de validité',
            'justifDom_doc': 'Justificatif de domicile et avis d\'imposition',
            'ribJour_doc': 'RIB à jour',
            'justifProvenance_doc': 'Justificatif de provenance des fonds',
            'justifDomImpot_doc': 'Justificatif domicile et impôt (copie)',
            'clauseBeneficiaire_doc': 'Clause bénéficiaire',
            'majProfilRachat_doc': 'MAJ & profil signée',
            'ribJourRachat_doc': 'RIB à jour',
            'majProfilArbitrage_doc': 'MAJ & profil signée',
            'ficheRenseignement_doc': 'Fiche de renseignement signée',
            'profilClientSigne_doc': 'Profil client signé',
            'cartoClientSigne_doc': 'Cartographie client signée',
            'lettreMiseRelation_doc': 'Lettre de mise en relation signée',
            'filSigne_doc': 'FIL signé',
            'justifDomCreation_doc': 'Justificatif domicile et avis d\'imposition',
            'cniValideCreation_doc': 'CNI en cours de validité'
        }
        
        for key, file in files.items():
            if file and file.filename:
                doc_name = doc_names.get(key, key.replace('_doc', ''))
                corps += f"• {doc_name}: {file.filename}\n"
        
        corps += f"({len([f for f in files.values() if f and f.filename])} fichiers joints)\n"
    else:
        corps += "Aucun document joint\n"
    
    corps += f"\n---\nDemande générée automatiquement le {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
    
    return corps

def envoyer_email_graph(sujet, corps, attachments):
    """Envoie l'email via Microsoft Graph API"""
    
    headers = {
        'Authorization': f'Bearer {session["access_token"]}',
        'Content-Type': 'application/json'
    }
    
    email_data = {
        "message": {
            "subject": sujet,
            "body": {
                "contentType": "Text",
                "content": corps
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": EMAIL_DESTINATAIRE
                    }
                }
            ],
            "attachments": attachments
        }
    }
    
    response = requests.post(
        f"{GRAPH_API_ENDPOINT}/me/sendMail",
        headers=headers,
        json=email_data
    )
    
    if response.status_code != 202:
        raise Exception(f"Erreur Graph API: {response.status_code} - {response.text}")

if __name__ == '__main__':
    # En production sur Render, utiliser le port fourni par la plateforme
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)