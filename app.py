from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth, firestore
from openai import OpenAI
import os
from dotenv import load_dotenv
import json

app = Flask(__name__)

# CORS global: acepta cualquier origen dinámicamente
CORS(app, resources={r"/*": {
    "origins": ["https://lumi-ai-front.vercel.app"],  # Tu frontend en Vercel
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
    "supports_credentials": True  # Esto es clave para las cookies
}})

# Cargar variables de entorno
load_dotenv()
google_creds = {
    "type": "service_account",
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL"),
    "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN")
}

openai_api_key = os.getenv("OPENAI_API_KEY")

if not google_creds or not openai_api_key:
    print("¡Error! No se pudo cargar las credenciales de Firebase o la API de OpenAI.")

# Inicializar Firebase
cred = credentials.Certificate(google_creds)
firebase_admin.initialize_app(cred)
db = firestore.client()

client = OpenAI(api_key=openai_api_key)

@app.route("/test")
def test():
    return jsonify({"message": "ok"})

@app.route("/protected", methods=["GET", "OPTIONS"])
def protected_route():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Token no proporcionado"}), 401

    id_token = auth_header.split(" ")[1]

    try:
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token["uid"]
        return jsonify({
            "uid": uid,
            "token": id_token,
        }), 200
    except Exception as e:
        return jsonify({"error": f"Token inválido: {str(e)}"}), 401

@app.route("/recuperar", methods=["GET", "OPTIONS"])
def recuperar_informacion_usuario():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Token no proporcionado"}), 401

    try:
        id_token = auth_header.split(" ")[1]
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token["uid"]

        doc = db.collection('usuarios').document(uid).get()
        if doc.exists:
            usuario_data = doc.to_dict()
            nombre_usuario = usuario_data.get("nombre", "Nombre no definido")
        else:
            nombre_usuario = "Usuario no encontrado en base de datos"

        return jsonify({
            "uid": uid,
            "token": id_token,
            "nombre": nombre_usuario
        }), 200

    except Exception as e:
        return jsonify({"error": f"Token inválido o error al recuperar usuario: {str(e)}"}), 401

@app.route('/api/preferencias', methods=['POST', 'OPTIONS'])
def guardar_preferencias():
    token = request.headers.get('Authorization').split(' ')[1]

    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        data = request.json
        doc_ref = db.collection('preferencias').document(uid)
        doc_ref.set(data)
        return jsonify({"message": "Preferencias guardadas correctamente"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "No autorizado o error al guardar preferencias"}), 401

@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header:
        return jsonify({"error": "Token no proporcionado"}), 401
    try:
        token = auth_header.split(" ")[1]
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token["uid"]
    except Exception as e:
        return jsonify({"error": "Token inválido o no autorizado", "detail": str(e)}), 401

    data = request.json
    user_input = data.get("mensaje")
    if not user_input:
        return jsonify({"error": "No se envió ningún mensaje"}), 400

    try:
        doc_ref = db.collection('preferencias').document(uid)
        doc = doc_ref.get()
        if doc.exists:
            preferencias = doc.to_dict()
            contexto = generar_contexto_desde_preferencias(preferencias)
        else:
            contexto = "Eres un asistente amigable y útil. Altamente empático. Tu propósito principal es el bienestar emocional de los demás. Te llamas Lumi."
    except Exception as e:
        return jsonify({"error": "Error al obtener preferencias", "detail": str(e)}), 500

    for intento in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": contexto}, {"role": "user", "content": user_input}]
            )
            respuesta = response.choices[0].message.content
            return jsonify({"respuesta": respuesta}), 200
        except Exception as e:
            print(f"[Intento {intento+1}] Error al llamar a OpenAI: {e}")
            if intento == 2:
                return jsonify({"error": "Error al generar respuesta", "detail": str(e)}), 500

def generar_contexto_desde_preferencias(preferencias):
    nombre = preferencias.get("nombre", "usuario")
    tono = preferencias.get("tono", "amigable")
    intereses = preferencias.get("intereses", [])
    objetivo = preferencias.get("objetivo", "ayuda general")
    pronombres = preferencias.get("pronombre", "femenino")

    intereses_str = ", ".join(intereses) if isinstance(intereses, list) else intereses

    return (
        f"El nombre de usuario es: {nombre}. "
        f"Eres un asistente con tono {tono}. "
        f"Este usuario está interesado en {intereses_str}. "
        f"Su objetivo es {objetivo}. "
        f"Pronombres del usuario: {pronombres}. "
        "Responde de forma personalizada, empática y brinda apoyo emocional. Altamente empático. Tu propósito principal es el bienestar emocional de los demás. Te llamas Lumi."
    )

@app.route("/api/test_openai", methods=["GET", "OPTIONS"])
def test_openai_simple():
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Eres un asistente útil"}, {"role": "user", "content": "Dime un dato curioso"}]
        )
        mensaje = response.choices[0].message.content
        return jsonify({"respuesta": mensaje}), 200
    except Exception as e:
        return jsonify({"error": f"Fallo al conectar con OpenAI: {str(e)}"}), 500

@app.route("/recuperarinfouser", methods=["GET", "OPTIONS"])
def recuperar_info_user():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Token no proporcionado"}), 401

    try:
        id_token = auth_header.split(" ")[1]
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token["uid"]

        doc_ref = db.collection('preferencias').document(uid)
        doc = doc_ref.get()

        if doc.exists:
            preferencias = doc.to_dict()
            return jsonify({
                "uid": uid,
                "preferencias": preferencias
            }), 200
        else:
            return jsonify({"error": "Preferencias no encontradas para este usuario"}), 404

    except Exception as e:
        return jsonify({"error": "Token inválido o error al recuperar preferencias", "detail": str(e)}), 401


if __name__ == "__main__":
    app.run(debug=True)
