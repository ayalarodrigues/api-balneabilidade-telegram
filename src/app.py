# src/app.py

from flask import Flask, Response, request
from flasgger import Swagger
import json
from datetime import datetime
import pandas as pd
import subprocess
import os
import sys
import requests
from .coordenadas import COORDENADAS_POR_CODIGO

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False #para suportar acentos

# --- Configuração do Swagger ---
template = {
    "swagger": "2.0",
    "info": {
        "title": "API de Balneabilidade e Previsão do Tempo - Fortaleza",
        "description": "API que integra dados da SEMACE com previsões da Open-Meteo.",
        "version": "1.0.0"
    },
    "host": "127.0.0.1:5000",
    "basePath": "/",
    "schemes": ["http"]
}
swagger = Swagger(app, template=template)

# --- Rodar scraper.py automaticamente antes de carregar os dados ---
# Constrói os caminhos de forma robusta para funcionar na estrutura src/
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_FILE = os.path.join(SRC_DIR, "scraper.py")
if os.path.exists(SCRAPER_FILE):
    print("Executando scraper para atualizar boletim...")
    subprocess.run([sys.executable, SCRAPER_FILE], check=True, cwd=SRC_DIR)
else:
    print(f"Arquivo scraper.py não encontrado em {SCRAPER_FILE}. Usando CSV existente.")

# --- Função para sempre retornar JSON com acentos ---
def json_response(data, status=200):
    return Response(json.dumps(data, ensure_ascii=False, indent=4), status=status, mimetype="application/json")

# --- Carregar os dados gerados pelo scraper ---
# Constrói o caminho para o CSV na pasta raiz do projeto
BASE_DIR = os.path.dirname(SRC_DIR)
CSV_FILE = os.path.join(BASE_DIR, "boletim_fortaleza.csv")
try:
    df = pd.read_csv(CSV_FILE)
except FileNotFoundError:
    raise FileNotFoundError(f"O arquivo {CSV_FILE} não foi encontrado. Execute o scraper primeiro.")

#converter o df para lista de dicionário
praias = df.to_dict(orient="records")

# --- Função para obter previsão do tempo e marinha ---
def get_forecast(lat, lon, data, hora=None):
    """
    Retorna previsão meteorológica e marinha para a latitude/longitude fornecida
    na data e hora desejadas.
    
    Unidades:
        - temperatura: °C
        - sensação térmica: °C
        - velocidade do vento: km/h
        - direção do vento: graus
        - chuva: mm
        - cobertura de nuvens: %
        - altura das ondas: metros
        - direção das ondas: graus
        - período das ondas: segundos
    """
    hora_consulta = hora if hora else "12:00"  # padrão meio-dia
    weather_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,apparent_temperature,windspeed_10m,winddirection_10m,precipitation,cloudcover&start_date={data}&end_date={data}&timezone=America/Fortaleza")
    marine_url = (f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,wave_direction,wave_period&start_date={data}&end_date={data}&timezone=America/Fortaleza")
    weather_response = requests.get(weather_url)
    marine_response = requests.get(marine_url)
    weather_data = weather_response.json() if weather_response.status_code == 200 else {}
    marine_data = marine_response.json() if marine_response.status_code == 200 else {}
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

# --- Função para extrair código da praia ---
def extrair_codigo(praia):
    # Caso exista campo 'Codigo', usa ele; senão extrai do Nome (ex: "05L - P. do Futuro")
    return (praia.get("Nome", "")[:3] or "").strip().upper()

# --- Rotas ---

#rota raiz
@app.route('/') #a função home será executada quando a raíz for chamada
def home():
    """
    Endpoint Raiz da API
    Retorna uma mensagem de boas-vindas e um resumo de todos os endpoints disponíveis.
    ---
    tags:
      - Geral
    responses:
      200:
        description: Mensagem de boas-vindas e estrutura da API.
    """
    data = {
        "message": "API de Balneabilidade e Previsão do Tempo - Fortaleza",
        "info": "Bem-vindo! Explore os endpoints abaixo ou use a documentação interativa para testar a API em tempo real.",
        "documentacao_interativa": {
            "descricao": "Acesse o Swagger UI para uma documentação completa, interativa e com capacidade de testes.",
            "url": "/apidocs"
        },
        "endpoints_resumo": {
            "/praias": {
                "descricao": "Lista um resumo de todas as praias (id, nome, zona).",
                "metodo": "GET"
            },
            "/praias/<id>": {
                "descricao": "Busca informações detalhadas de uma praia pelo seu ID.",
                "metodo": "GET",
                "exemplo": "/praias/5"
            },
            "/praias/<id>/data": {
                "descricao": "Busca o boletim e a previsão do tempo para uma praia em uma data específica.",
                "metodo": "GET",
                "parametros": "?data=YYYY-MM-DD (obrigatório) &hora=HH:MM (opcional)",
                "exemplo": "/praias/5/data?data=2025-09-13&hora=14:00"
            },
            "/praias/status/<status>": {
                "descricao": "Filtra praias pelo status ('propria' ou 'impropria').",
                "metodo": "GET",
                "parametros_opcionais": "?data=YYYY-MM-DD&hora=HH:MM",
                "exemplo_simples": "/praias/status/propria",
                "exemplo_com_previsao": "/praias/status/propria?data=2025-09-13&hora=15:00"
            },
            "/praias/zona/<zona>": {
                "descricao": "Filtra praias pela zona ('Leste', 'Centro', 'Oeste').",
                "metodo": "GET",
                "parametros_opcionais": "?data=YYYY-MM-DD&hora=HH:MM",
                "exemplo_simples": "/praias/zona/Leste",
                "exemplo_com_previsao": "/praias/zona/Leste?data=2025-09-13&hora=09:00"
            }
        }
    }
    return json_response(data)

#rota para listar todas as praias
@app.route("/praias")
def listar_praias():
    """
    Listar todas as praias (Resumo)
    Retorna uma lista resumida de todas as praias monitoradas, contendo ID, nome e zona.
    ---
    tags:
      - Praias
    responses:
      200:
        description: Lista de praias resumida.
    """
    praias_resumo = [{"id": p["id"], "nome": p["Nome"], "zona": p["Zona"]} for p in praias]
    return json_response(praias_resumo)

#buscar praia pelo id
@app.route("/praias/<int:id>")
def buscar_praia_por_id(id):
    """
    Buscar praia por ID
    Retorna os detalhes completos de uma praia específica com base no seu ID numérico.
    ---
    tags:
      - Praias
    parameters:
      - name: id
        in: path
        type: integer
        required: true
        description: O ID numérico da praia a ser consultada.
    responses:
      200:
        description: Detalhes da praia encontrada.
      404:
        description: Praia não encontrada para o ID fornecido.
    """
    praia = next((p for p in praias if p["id"] == id), None)
    if not praia:
        return json_response({"message": f"Nenhuma praia encontrada com id {id}"}, status=404)
    return json_response(praia)

#buscar informações das praias pelo id e data
@app.route("/praias/<int:id>/data")
def buscar_praia_por_id_e_data(id):
    """
    Obter dados de uma praia por ID em uma data específica
    Retorna os dados do boletim da SEMACE e a previsão do tempo para uma praia em uma data.
    ---
    tags:
      - Previsão do Tempo
    parameters:
      - name: id
        in: path
        type: integer
        required: true
        description: O ID numérico da praia.
      - name: data
        in: query
        type: string
        required: true
        description: Data para a consulta (formato YYYY-MM-DD).
      - name: hora
        in: query
        type: string
        required: false
        description: Hora para a consulta (formato HH:MM, padrão 12:00).
    responses:
      200:
        description: Dados do boletim e previsão do tempo para a praia e data.
      400:
        description: Parâmetro 'data' não foi fornecido.
      404:
        description: Praia não encontrada para o ID fornecido.
    """
    #query params: ?data=YYYY-MM-DD&hora=HH:MM 
    data = request.args.get("data")
    hora = request.args.get("hora", "12:00")
    if not data:
        return json_response({"message": "É necessário informar a data no formato YYYY-MM-DD"}, status=400)
    praia = next((p for p in praias if p["id"] == id), None)
    if not praia:
        return json_response({"message": f"Nenhuma praia encontrada com id {id}"}, status=404)
    codigo = extrair_codigo(praia)
    if not codigo or codigo not in COORDENADAS_POR_CODIGO:
        return json_response({"message": "Coordenadas da praia não disponíveis"}, status=500)
    lat_str, lon_str = COORDENADAS_POR_CODIGO[codigo].split(", ")
    lat, lon = float(lat_str), float(lon_str)
    forecast = get_forecast(lat, lon, data, hora)
    boletim_disponivel = data in str(praia["Dias_Periodo"]).split(", ")
    boletim = praia if boletim_disponivel else f"Não há boletim da Semace disponível para {data}"
    resposta = {"boletim": boletim, "previsao": forecast}
    return json_response(resposta)

#buscar praia por status com data opcional e previsão meteorológica
@app.route("/praias/status/<status>")
def filtrar_por_status(status):
    """
    Filtrar praias por Status
    Retorna uma lista de praias filtradas por status. Se uma data (?data=...) for fornecida, a previsão do tempo é incluída. Opcionalmente, uma hora (?hora=...) pode ser especificada, caso contrário, o padrão é 12:00.
    ---
    tags:
      - Filtros
    parameters:
      - name: status
        in: path
        type: string
        required: true
        description: O status de balneabilidade para filtrar.
        enum: [propria, impropria]
      - name: data
        in: query
        type: string
        required: false
        description: Data para incluir a previsão (formato YYYY-MM-DD).
      - name: hora
        in: query
        type: string
        required: false
        description: Hora para refinar a previsão (formato HH:MM).
    responses:
      200:
        description: Lista de praias com o status especificado.
      400:
        description: Status inválido.
      404:
        description: Nenhuma praia encontrada para os critérios.
    """
    """
    Filtra praias por status (propria/impropria).
    - Se 'data' for informada, tenta incluir 'previsao' (Open-Meteo).
    - Se 'data' não for informada, não inclui 'previsao' para evitar retornos com null.
    """
    data = request.args.get("data")
    hora = request.args.get("hora", "12:00")
    status_map = {"propria": "Própria para banho", "impropria": "Imprópria para banho"}
    status_filtrado = status_map.get(status.lower())
    if not status_filtrado:
        return json_response({"message": "Status inválido. Use 'propria' ou 'impropria'."}, status=400)
    resultado = [p for p in praias if p["Status"] == status_filtrado]
    if data:
        resultado = [p for p in resultado if data in str(p["Dias_Periodo"]).split(", ")]
    if not resultado and not data:
        return json_response({"message": f"Nenhuma praia encontrada com status {status_filtrado}"}, status=404)
    resposta = []
    for praia in resultado:
        if not data:
            resposta.append({"praia": praia, "info": "Para obter previsão, informe ?data=YYYY-MM-DD."})
            continue
        codigo = extrair_codigo(praia)
        if codigo and codigo in COORDENADAS_POR_CODIGO:
            lat_str, lon_str = COORDENADAS_POR_CODIGO[codigo].split(", ")
            lat, lon = float(lat_str), float(lon_str)
            forecast = get_forecast(lat, lon, data, hora)
        else:
            forecast = {"mensagem": "Coordenadas não disponíveis"}
        resposta.append({"praia": praia, "previsao": forecast})
    return json_response(resposta)

#buscar praias por zona geográfica e data opcional com previsão meteorológica
@app.route("/praias/zona/<zona>")
def filtrar_por_zona(zona):
    """
    Filtrar praias por Zona
    Retorna uma lista de praias filtradas por zona. Se uma data (?data=...) for fornecida, a previsão do tempo é incluída. Opcionalmente, uma hora (?hora=...) pode ser especificada, caso contrário, o padrão é 12:00.
    ---
    tags:
      - Filtros
    parameters:
      - name: zona
        in: path
        type: string
        required: true
        description: A zona geográfica para filtrar.
        enum: [Leste, Centro, Oeste]
      - name: data
        in: query
        type: string
        required: false
        description: Data para incluir a previsão (formato YYYY-MM-DD).
      - name: hora
        in: query
        type: string
        required: false
        description: Hora para refinar a previsão (formato HH:MM).
    responses:
      200:
        description: Lista de praias na zona especificada.
      404:
        description: Nenhuma praia encontrada para os critérios.
    """
    """
    Filtra praias por zona. Comportamento similar a /praias/status:
    - Se 'data' for informada, inclui 'previsao' quando possível.
    - Se 'data' não for informada, não inclui 'previsao' (evita null).
    """
    data = request.args.get("data")
    hora = request.args.get("hora", "12:00")
    zona_filtrada = zona.capitalize()
    resultado = [p for p in praias if p["Zona"] == zona_filtrada]
    if data:
        resultado = [p for p in resultado if data in str(p["Dias_Periodo"]).split(", ")]
    if not resultado and not data:
        return json_response({"message": f"Nenhuma praia encontrada na zona {zona_filtrada}"}, status=404)
    resposta = []
    for praia in resultado:
        if not data:
            resposta.append({"praia": praia, "info": "Para obter previsão, informe ?data=YYYY-MM-DD."})
            continue
        codigo = extrair_codigo(praia)
        if codigo and codigo in COORDENADAS_POR_CODIGO:
            lat_str, lon_str = COORDENADAS_POR_CODIGO[codigo].split(", ")
            lat, lon = float(lat_str), float(lon_str)
            forecast = get_forecast(lat, lon, data, hora)
        else:
            forecast = {"mensagem": "Coordenadas não disponíveis"}
        resposta.append({"praia": praia, "previsao": forecast})
    return json_response(resposta)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)