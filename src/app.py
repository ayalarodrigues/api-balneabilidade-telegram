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
    
    forecast = {"mensagem": f"Previsão não disponível para {data} às {hora_consulta}", "data": data, "hora_consulta": hora_consulta}
    try:
        weather_response = requests.get(weather_url)
        marine_response = requests.get(marine_url)
        weather_data = weather_response.json() if weather_response.status_code == 200 else {}
        marine_data = marine_response.json() if marine_response.status_code == 200 else {}
        
        target_time = f"{data}T{hora_consulta}"
        
        if "hourly" in weather_data and target_time in weather_data["hourly"]["time"]:
            idx = weather_data["hourly"]["time"].index(target_time)
            forecast.update({
                "temperatura_c": weather_data["hourly"]["temperature_2m"][idx],
                "sensacao_termica_c": weather_data["hourly"]["apparent_temperature"][idx],
                "velocidade_vento_kmh": weather_data["hourly"]["windspeed_10m"][idx],
                "direcao_vento_graus": weather_data["hourly"]["winddirection_10m"][idx],
                "chuva_mm": weather_data["hourly"]["precipitation"][idx],
                "cobertura_nuvens_pct": weather_data["hourly"]["cloudcover"][idx],
                "mensagem": "Previsão obtida com sucesso"
            })
        if "hourly" in marine_data and target_time in marine_data["hourly"]["time"]:
            idx = marine_data["hourly"]["time"].index(target_time)
            forecast.update({
                "altura_ondas_m": marine_data["hourly"]["wave_height"][idx],
                "direcao_ondas_graus": marine_data["hourly"]["wave_direction"][idx],
                "periodo_ondas_s": marine_data["hourly"]["wave_period"][idx],
            })
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        print(f"Erro ao obter previsão: {e}")

    return forecast

def extrair_codigo(praia):
    return (praia.get("Nome", "")[:3] or "").strip().upper()

# --- Definição de TODAS as Rotas da API ---

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
    
@app.route("/praias/<int:id>/data")
def buscar_praia_por_id_e_data(id):
    """Obter dados de uma praia por ID em uma data específica."""
    data = request.args.get("data")
    hora = request.args.get("hora", "12:00")
    if not data:
        return json_response({"message": "É necessário informar a data no formato YYYY-MM-DD"}, status=400)
    
    praia = next((p for p in praias if p.get("id") == id), None)
    if not praia:
        return json_response({"message": f"Nenhuma praia encontrada com id {id}"}, status=404)
        
    codigo = extrair_codigo(praia)
    if not codigo or codigo not in COORDENADAS_POR_CODIGO:
        return json_response({"message": "Coordenadas da praia não disponíveis"}, status=500)
        
    lat_str, lon_str = COORDENADAS_POR_CODIGO[codigo].split(", ")
    lat, lon = float(lat_str), float(lon_str)
    
    forecast = get_forecast(lat, lon, data, hora)
    boletim = praia if data in str(praia.get("Dias_Periodo", "")).split(", ") else f"Não há boletim da Semace disponível para {data}"
    
    resposta = {"boletim": boletim, "previsao": forecast}
    return json_response(resposta)

@app.route("/praias/status/<status>")
def filtrar_por_status(status):
    """Filtrar praias por Status."""
    data = request.args.get("data")
    hora = request.args.get("hora", "12:00")
    status_map = {"propria": "Própria para banho", "impropria": "Imprópria para banho"}
    status_filtrado = status_map.get(status.lower())
    if not status_filtrado:
        return json_response({"message": "Status inválido. Use 'propria' ou 'impropria'."}, status=400)
    
    resultado = [p for p in praias if p.get("Status") == status_filtrado]
    if not resultado:
        return json_response({"message": f"Nenhuma praia encontrada com status {status_filtrado}"}, status=404)

    if not data:
        return json_response(resultado)

    resposta_com_previsao = []
    for praia in resultado:
        item = {"praia": praia}
        codigo = extrair_codigo(praia)
        if codigo and codigo in COORDENADAS_POR_CODIGO:
            lat_str, lon_str = COORDENADAS_POR_CODIGO[codigo].split(", ")
            lat, lon = float(lat_str), float(lon_str)
            item["previsao"] = get_forecast(lat, lon, data, hora)
        else:
            item["previsao"] = {"mensagem": "Coordenadas não disponíveis"}
        resposta_com_previsao.append(item)
        
    return json_response(resposta_com_previsao)

@app.route("/praias/zona/<zona>")
def filtrar_por_zona(zona):
    """Filtrar praias por Zona."""
    data = request.args.get("data")
    hora = request.args.get("hora", "12:00")
    zona_filtrada = zona.capitalize()
    
    resultado = [p for p in praias if p.get("Zona") == zona_filtrada]
    if not resultado:
        return json_response({"message": f"Nenhuma praia encontrada na zona {zona_filtrada}"}, status=404)

    if not data:
        return json_response(resultado)

    resposta_com_previsao = []
    for praia in resultado:
        item = {"praia": praia}
        codigo = extrair_codigo(praia)
        if codigo and codigo in COORDENADAS_POR_CODIGO:
            lat_str, lon_str = COORDENADAS_POR_CODIGO[codigo].split(", ")
            lat, lon = float(lat_str), float(lon_str)
            item["previsao"] = get_forecast(lat, lon, data, hora)
        else:
            item["previsao"] = {"mensagem": "Coordenadas não disponíveis"}
        resposta_com_previsao.append(item)
        
    return json_response(resposta_com_previsao)
