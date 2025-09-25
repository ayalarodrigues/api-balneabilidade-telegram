# src/app.py

from flask import Flask, Response, request
from flasgger import Swagger
import json
from datetime import datetime
import pandas as pd
import os
import requests  # <-- IMPORTAÇÃO QUE FALTAVA

# IMPORTAÇÕES CORRIGIDAS
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
    # Idealmente, o host deve ser dinâmico, mas para a Render pode deixar genérico
    "host": "api-balneabilidade-telegram.onrender.com",
    "basePath": "/",
    "schemes": ["https"]
}
swagger = Swagger(app, template=template)

# --- CHAMA A FUNÇÃO DO SCRAPER DIRETAMENTE ---
try:
    print("Executando scraper para atualizar boletim...")
    run_scraper()
except Exception as e:
    print(f"AVISO: O scraper falhou com o erro: {e}")
    print("A API continuará usando o arquivo CSV existente, se disponível.")

# --- Função para sempre retornar JSON com acentos ---
def json_response(data, status=200):
    return Response(json.dumps(data, ensure_ascii=False, indent=4), status=status, mimetype="application/json")

# --- Carregar os dados gerados pelo scraper ---
# LÓGICA DE CAMINHO CORRIGIDA
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SRC_DIR)
CSV_FILE = os.path.join(BASE_DIR, "boletim_fortaleza.csv")
try:
    df = pd.read_csv(CSV_FILE)
except FileNotFoundError:
    # Cria um DataFrame vazio se o CSV não existir para evitar que a API quebre
    df = pd.DataFrame(columns=["id", "Nome", "Status", "Zona", "Dias_Periodo"])
    print(f"AVISO: O arquivo {CSV_FILE} não foi encontrado. A API iniciará com dados vazios.")

praias = df.to_dict(orient="records")

# --- Função para obter previsão do tempo e marinha (sem alterações) ---
def get_forecast(lat, lon, data, hora=None):
    hora_consulta = hora if hora else "12:00"
    weather_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,apparent_temperature,windspeed_10m,winddirection_10m,precipitation,cloudcover&start_date={data}&end_date={data}&timezone=America/Fortaleza")
    marine_url = (f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,wave_direction,wave_period&start_date={data}&end_date={data}&timezone=America/Fortaleza")
    
    try:
        weather_response = requests.get(weather_url)
        marine_response = requests.get(marine_url)
        weather_data = weather_response.json() if weather_response.status_code == 200 else {}
        marine_data = marine_response.json() if marine_response.status_code == 200 else {}
    except requests.exceptions.RequestException as e:
        print(f"Erro ao conectar com a API de previsão: {e}")
        return {"mensagem": "Não foi possível obter a previsão do tempo.", "data": data, "hora_consulta": hora_consulta}

    forecast = {"data": data, "hora_consulta": hora_consulta, "temperatura_c": None, "sensacao_termica_c": None, "velocidade_vento_kmh": None, "direcao_vento_graus": None, "chuva_mm": None, "cobertura_nuvens_pct": None, "altura_ondas_m": None, "direcao_ondas_graus": None, "periodo_ondas_s": None}
    
    if "hourly" in weather_data:
        times = weather_data["hourly"]["time"]
        alvo = f"{data}T{hora_consulta}"
        if alvo in times:
            idx = times.index(alvo)
            forecast.update({"temperatura_c": weather_data["hourly"]["temperature_2m"][idx], "sensacao_termica_c": weather_data["hourly"]["apparent_temperature"][idx], "velocidade_vento_kmh": weather_data["hourly"]["windspeed_10m"][idx], "direcao_vento_graus": weather_data["hourly"]["winddirection_10m"][idx], "chuva_mm": weather_data["hourly"]["precipitation"][idx], "cobertura_nuvens_pct": weather_data["hourly"]["cloudcover"][idx]})
    
    if "hourly" in marine_data:
        times = marine_data["hourly"]["time"]
        alvo = f"{data}T{hora_consulta}"
        if alvo in times:
            idx = times.index(alvo)
            forecast.update({"altura_ondas_m": marine_data["hourly"]["wave_height"][idx], "direcao_ondas_graus": marine_data["hourly"]["wave_direction"][idx], "periodo_ondas_s": marine_data["hourly"]["wave_period"][idx]})
    
    if all(value is None for key, value in forecast.items() if key not in ["data", "hora_consulta"]):
        forecast = {"mensagem": f"Previsão não disponível para {data} às {hora_consulta}", "data": data, "hora_consulta": hora_consulta}
        
    return forecast

# --- O RESTO DO SEU CÓDIGO DE ROTAS CONTINUA AQUI SEM ALTERAÇÕES ---

# (Cole o restante do seu app.py a partir da função "extrair_codigo")