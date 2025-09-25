# src/app.py

from flask import Flask, Response, request
from flasgger import Swagger
import json
from datetime import datetime
import pandas as pd
import os
import requests

# Importações relativas para funcionar no ambiente de produção
from .scraper import run_scraper
from .coordenadas import COORDENADAS_POR_CODIGO

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# --- Configuração do Swagger ---
template = {
    "swagger": "2.0",
    "info": {
        "title": "API de Balneabilidade e Previsão do Tempo - Fortaleza",
        "description": "API que integra dados da SEMACE com previsões da Open-Meteo.",
        "version": "1.0.0"
    },
    "host": "api-balneabilidade-telegram.onrender.com",
    "basePath": "/",
    "schemes": ["https"]
}
swagger = Swagger(app, template=template)

# --- Executa o scraper na inicialização da API ---
try:
    print("Executando scraper para atualizar boletim...")
    run_scraper()
except Exception as e:
    print(f"AVISO: O scraper falhou com o erro: {e}")
    print("A API continuará usando o arquivo CSV existente, se disponível.")

# --- Função de resposta JSON ---
def json_response(data, status=200):
    return Response(json.dumps(data, ensure_ascii=False, indent=4), status=status, mimetype="application/json")

# --- Carregamento dos dados do CSV ---
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SRC_DIR)
CSV_FILE = os.path.join(BASE_DIR, "boletim_fortaleza.csv")

try:
    df = pd.read_csv(CSV_FILE)
except FileNotFoundError:
    df = pd.DataFrame() # Inicia com um DataFrame vazio se o arquivo não existir
    print(f"AVISO: O arquivo {CSV_FILE} não foi encontrado. A API iniciará com dados vazios.")

praias = df.to_dict(orient="records")

# --- Funções auxiliares ---
def get_forecast(lat, lon, data, hora=None):
    hora_consulta = hora if hora else "12:00"
    weather_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,apparent_temperature,windspeed_10m,winddirection_10m,precipitation,cloudcover&start_date={data}&end_date={data}&timezone=America/Fortaleza")
    marine_url = (f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,wave_direction,wave_period&start_date={data}&end_date={data}&timezone=America/Fortaleza")
    
    forecast = {"mensagem": "Previsão não disponível"}
    try:
        weather_response = requests.get(weather_url)
        marine_response = requests.get(marine_url)
        weather_data = weather_response.json() if weather_response.status_code == 200 else {}
        marine_data = marine_response.json() if marine_response.status_code == 200 else {}
        
        forecast = {"data": data, "hora_consulta": hora_consulta}
        if "hourly" in weather_data:
            idx = weather_data["hourly"]["time"].index(f"{data}T{hora_consulta}")
            forecast.update({
                "temperatura_c": weather_data["hourly"]["temperature_2m"][idx],
                "velocidade_vento_kmh": weather_data["hourly"]["windspeed_10m"][idx],
            })
        if "hourly" in marine_data:
            idx = marine_data["hourly"]["time"].index(f"{data}T{hora_consulta}")
            forecast.update({
                "altura_ondas_m": marine_data["hourly"]["wave_height"][idx],
            })
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        print(f"Erro ao obter previsão: {e}")

    return forecast

def extrair_codigo(praia):
    return (praia.get("Nome", "")[:3] or "").strip().upper()

# --- Definição das Rotas da API ---

@app.route('/')
def home():
    """Endpoint Raiz da API."""
    data = { "message": "Bem-vindo à API de Balneabilidade de Fortaleza!", "documentacao": "/apidocs" }
    return json_response(data)

@app.route("/praias")
def listar_praias():
    """Listar todas as praias (Resumo)."""
    if not praias:
        return json_response({"message": "Nenhum dado de praias disponível no momento."}, status=404)
    praias_resumo = [{"id": p.get("id"), "nome": p.get("Nome"), "zona": p.get("Zona")} for p in praias]
    return json_response(praias_resumo)

@app.route("/praias/<int:id>")
def buscar_praia_por_id(id):
    """Buscar praia por ID."""
    praia = next((p for p in praias if p.get("id") == id), None)
    if not praia:
        return json_response({"message": f"Nenhuma praia encontrada com id {id}"}, status=404)
    return json_response(praia)

@app.route("/praias/status/<status>")
def filtrar_por_status(status):
    """Filtrar praias por Status."""
    status_map = {"propria": "Própria para banho", "impropria": "Imprópria para banho"}
    status_filtrado = status_map.get(status.lower())
    if not status_filtrado:
        return json_response({"message": "Status inválido. Use 'propria' ou 'impropria'."}, status=400)
    
    resultado = [p for p in praias if p.get("Status") == status_filtrado]
    if not resultado:
        return json_response({"message": f"Nenhuma praia encontrada com status {status_filtrado}"}, status=404)
    
    return json_response(resultado)

# (Você pode adicionar as outras rotas aqui se desejar, como /praias/zona/<zona>)
