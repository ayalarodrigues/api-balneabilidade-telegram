# src/scraper.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pdfplumber
import unicodedata
from datetime import datetime, timedelta
import camelot
import pandas as pd
import os

# Importação direta, pois este arquivo pode ser executado de forma independente
from coordenadas import COORDENADAS_POR_CODIGO

def extract_point_code(nome: str) -> str:
    return (nome[:3] or "").strip().upper()

def expand_periodo(periodo_str: str):
    try:
        inicio_str, fim_str = [p.strip() for p in periodo_str.split("a")]
        dt_inicio = datetime.strptime(inicio_str, "%d/%m/%Y")
        dt_fim = datetime.strptime(fim_str, "%d/%m/%Y")
        dias = []
        atual = dt_inicio
        while atual <= dt_fim:
            dias.append(atual.strftime("%Y-%m-%d"))
            atual += timedelta(days=1)
        return dias
    except Exception:
        return []

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def classify_zona(nome: str) -> str:
    n = strip_accents((nome or "").lower())
    leste_kw = ["futuro", "caca e pesca", "abreulandia", "sabiaguaba", "titanzinho"]
    centro_kw = ["iracema", "meireles", "mucuripe", "volta da jurema", "beira mar", "estressados"]
    oeste_kw = ["barra do ceara", "pirambu", "cristo redentor", "leste oeste", "formosa", "colonia"]

    if any(k in n for k in leste_kw): return "Leste"
    if any(k in n for k in centro_kw): return "Centro"
    if any(k in n for k in oeste_kw): return "Oeste"
    return "Desconhecida"

# A LÓGICA PRINCIPAL AGORA ESTÁ DENTRO DESTA FUNÇÃO
def run_scraper():
    print("Iniciando o processo de scraping...")
    url_base = "https://www.semace.ce.gov.br/boletim-de-balneabilidade/"
    res = requests.get(url_base)
    soup = BeautifulSoup(res.text, "html.parser")

    links_boletim = [
        a['href'] for a in soup.find_all('a', href=True)
        if "Boletim das Praias de Fortaleza" in a.get_text()
    ]

    if not links_boletim:
        raise ValueError("Nenhum boletim encontrado.")

    ultimo_boletim_url = urljoin(url_base, links_boletim[0])
    
    # Define o caminho do PDF dentro do diretório src
    SRC_DIR = os.path.dirname(os.path.abspath(__file__))
    arquivo_pdf = os.path.join(SRC_DIR, "boletim_fortaleza.pdf")

    res = requests.get(ultimo_boletim_url, stream=True)
    with open(arquivo_pdf, "wb") as f:
        for chunk in res.iter_content(8192):
            f.write(chunk)
    print(f"PDF salvo em {arquivo_pdf}")

    with pdfplumber.open(arquivo_pdf) as pdf:
        texto_pg1 = pdf.pages[0].extract_text() or ""
        texto_pg1 = " ".join(texto_pg1.split())

    periodo = ""
    numero_boletim = ""
    tipos_amostragem = ""

    if "Nº" in texto_pg1 and "Período:" in texto_pg1 and "Tipos de amostras:" in texto_pg1:
        bol_index = texto_pg1.find("Nº")
        per_index = texto_pg1.find("Período:", bol_index)
        tipos_index = texto_pg1.find("Tipos de amostras:", per_index)
        numero_boletim = texto_pg1[bol_index + 2:per_index].strip()
        periodo = texto_pg1[per_index + len("Período:"):tipos_index].strip()
        resto = texto_pg1[tipos_index + len("Tipos de amostras:"):].strip()
        tipos_amostragem = resto.split(".")[0].strip()

    dias_periodo = expand_periodo(periodo)
    data_extracao = datetime.today().strftime("%Y-%m-%d")

    tables = camelot.read_pdf(arquivo_pdf, pages="1-end", flavor="stream")
    
    def clean_status_token(tok: str) -> str:
        tok = tok.strip().upper()
        return tok if tok in ("P", "I") else ""

    def is_noise_row(nome: str, status: str) -> bool:
        txt = f"{str(nome)} {str(status)}".lower()
        noise_terms = ["nome", "status", "trecho", "ponto", "boletim", "semace"]
        if len(txt.strip()) < 3: return True
        return any(term in txt for term in noise_terms)

    dfs_norm = []
    for t in tables:
        df_raw = t.df.copy()
        if df_raw.shape[1] < 2: continue
        df_raw = df_raw.iloc[:, :2]
        df_raw.columns = ["Nome", "Status"]
        linhas = []
        for _, row in df_raw.iterrows():
            nomes = [x.strip() for x in row["Nome"].split("\n") if x.strip()]
            status_tokens = [clean_status_token(x) for x in row["Status"].split("\n")]
            status_tokens = [x for x in status_tokens if x]
            if not nomes or not status_tokens: continue
            if len(status_tokens) == 1 and len(nomes) > 1:
                for n in nomes:
                    if not is_noise_row(n, status_tokens[0]):
                        linhas.append({"Nome": n, "Status": status_tokens[0]})
            else:
                for n, s in zip(nomes, status_tokens):
                    if not is_noise_row(n, s):
                        linhas.append({"Nome": n, "Status": s})
        if linhas:
            dfs_norm.append(pd.DataFrame(linhas))
    
    df = pd.concat(dfs_norm, ignore_index=True) if dfs_norm else pd.DataFrame(columns=["Nome","Status"])
    df["Nome"] = df["Nome"].apply(lambda x: " ".join(x.split()))
    df = df.drop_duplicates(subset=["Nome"]).reset_index(drop=True)

    df["Zona"] = df["Nome"].apply(classify_zona)
    df["Periodo"] = periodo
    df["Dias_Periodo"] = [", ".join(dias_periodo)] * len(df)
    df["Numero_Boletim"] = numero_boletim
    df["Tipos_Amostragem"] = tipos_amostragem
    df["Data_Extração"] = data_extracao
    df["Status"] = df["Status"].map({"P": "Própria para banho", "I": "Imprópria para banho"})
    df.insert(0, "id", range(1, len(df) + 1))
    df["Coordenadas"] = df["Nome"].apply(lambda n: COORDENADAS_POR_CODIGO.get(extract_point_code(n), None))

    BASE_DIR = os.path.dirname(SRC_DIR)
    caminho_csv = os.path.join(BASE_DIR, "boletim_fortaleza.csv")
    df.to_csv(caminho_csv, index=False, encoding="utf-8")
    print(f"Scraping concluído. CSV salvo em: {caminho_csv}")

# Bloco para permitir que o script seja executado de forma independente para testes
if __name__ == "__main__":
    run_scraper()