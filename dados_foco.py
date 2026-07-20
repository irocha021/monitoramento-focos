import json
import logging
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/"
CSV_PATTERN = r"focos_diario_br_(\d{8})\.csv"
OUTPUT_TEMPO_REAL = "focos_oeste_ba.json"
OUTPUT_PANORAMA = "panorama_fogo_oeste_ba.json"

MUNICIPIOS_OESTE = [
    "Barreiras",
    "Bom Jesus da Lapa",
    "Luis Eduardo Magalhaes",
    "Barra",
    "Santa Maria da Vitoria",
    "Serra do Ramalho",
    "Correntina",
    "Carinhanha",
    "Sao Desiderio",
    "Santa Rita de Cassia",
    "Santana",
    "Formosa do Rio Preto",
    "Riachao das Neves",
    "Buritirama",
    "Cocos",
    "Serra Dourada",
    "Malhada",
    "Coribe",
    "Angical",
    "Baianopolis",
    "Cotegipe",
    "Cristopolis",
    "Sao Felix do Coribe",
    "Mansidao",
    "Wanderley",
    "Sitio do Mato",
    "Tabocas do Brejo Velho",
    "Brejolandia",
    "Muquem do Sao Francisco",
    "Canapolis",
    "Jaborandi",
    "Feira da Mata",
    "Catolandia",
]


def normalizar_texto(valor):
    if pd.isna(valor):
        return ""

    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    return texto


def _listar_arquivos_inpe(base_url):
    logging.info("Acessando o diretorio do INPE para encontrar arquivos diarios...")
    try:
        req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        logging.error("Erro de rede ao acessar a URL do INPE: %s", exc)
        return []

    arquivos = []
    for data_txt in sorted(set(re.findall(CSV_PATTERN, html))):
        data_arquivo = datetime.strptime(data_txt, "%Y%m%d").date()
        nome_arquivo = f"focos_diario_br_{data_txt}.csv"
        arquivos.append({"data": data_arquivo, "url": base_url + nome_arquivo})

    if not arquivos:
        logging.warning("Nenhum arquivo CSV encontrado na pagina do INPE.")

    return arquivos


def _primeira_coluna_existente(df, nomes):
    for nome in nomes:
        if nome in df.columns:
            return nome
    return None


def _valor_json(valor, padrao=None):
    if pd.isna(valor):
        return padrao
    return valor


def _filtrar_df(df, municipios_foco):
    coluna_municipio = _primeira_coluna_existente(df, ["municipio", "municipio_nome", "mun"])
    coluna_estado = _primeira_coluna_existente(df, ["estado", "uf", "sigla_uf", "estado_id"])
    coluna_data = _primeira_coluna_existente(df, ["data_hora_gmt", "datahora", "data_hora", "data"])
    coluna_risco = _primeira_coluna_existente(df, ["risco_fogo", "riscofogo"])
    coluna_lat = _primeira_coluna_existente(df, ["lat", "latitude"])
    coluna_lon = _primeira_coluna_existente(df, ["lon", "longitude"])

    if not coluna_municipio or not coluna_lat or not coluna_lon:
        raise ValueError(f"CSV sem colunas esperadas. Colunas recebidas: {list(df.columns)}")

    municipios_normalizados = {normalizar_texto(nome) for nome in municipios_foco}
    df = df.copy()
    df["municipio_normalizado"] = df[coluna_municipio].apply(normalizar_texto)
    df[coluna_lat] = pd.to_numeric(df[coluna_lat], errors="coerce")
    df[coluna_lon] = pd.to_numeric(df[coluna_lon], errors="coerce")

    df_filtrado = df[df["municipio_normalizado"].isin(municipios_normalizados)].copy()
    if coluna_estado:
        if coluna_estado == "estado_id":
            df_filtrado = df_filtrado[pd.to_numeric(df_filtrado[coluna_estado], errors="coerce") == 29]
        else:
            estado_normalizado = df_filtrado[coluna_estado].apply(normalizar_texto)
            df_filtrado = df_filtrado[estado_normalizado.isin({"BA", "BAHIA"})]

    df_filtrado = df_filtrado.dropna(subset=[coluna_lat, coluna_lon])
    return df_filtrado, {
        "municipio": coluna_municipio,
        "estado": coluna_estado,
        "data": coluna_data,
        "risco": coluna_risco,
        "lat": coluna_lat,
        "lon": coluna_lon,
    }


def _processar_arquivos(arquivos, municipios_foco, nome_periodo):
    features = []
    arquivos_processados = []

    for item in arquivos:
        logging.info("Baixando dados de: %s", item["url"])
        try:
            df = pd.read_csv(item["url"])
            df_filtrado, colunas = _filtrar_df(df, municipios_foco)
        except Exception as exc:
            logging.warning("Arquivo ignorado por falha no processamento: %s | %s", item["url"], exc)
            continue

        arquivos_processados.append(item)
        for _, row in df_filtrado.iterrows():
            municipio = str(row.get(colunas["municipio"], "N/A")).strip()
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "satelite": _valor_json(row.get("satelite"), "N/A"),
                        "data_hora": _valor_json(row.get(colunas["data"]), "N/A")
                        if colunas["data"]
                        else "N/A",
                        "municipio": municipio,
                        "municipio_normalizado": normalizar_texto(municipio),
                        "estado": _valor_json(row.get(colunas["estado"]), "N/A")
                        if colunas["estado"]
                        else "N/A",
                        "risco_fogo": _valor_json(row.get(colunas["risco"]), None)
                        if colunas["risco"]
                        else None,
                        "bioma": _valor_json(row.get("bioma"), "N/A"),
                        "frp": _valor_json(row.get("frp"), None),
                        "arquivo_origem": item["url"].split("/")[-1],
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row[colunas["lon"]]), float(row[colunas["lat"]])],
                    },
                }
            )

    if arquivos_processados:
        periodo_inicio = min(item["data"] for item in arquivos_processados).isoformat()
        periodo_fim = max(item["data"] for item in arquivos_processados).isoformat()
    else:
        periodo_inicio = None
        periodo_fim = None

    logging.info(
        "Encontrados %s focos de calor para %s.",
        len(features),
        nome_periodo,
    )

    return {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": BASE_URL,
            "region": "Oeste da Bahia",
            "period_name": nome_periodo,
            "period_start": periodo_inicio,
            "period_end": periodo_fim,
            "processed_files": len(arquivos_processados),
            "total_features": len(features),
        },
        "features": features,
    }


def _save_geojson(geojson_data, output_path):
    try:
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(geojson_data, file, ensure_ascii=False, indent=2, allow_nan=False)
        logging.info("Arquivo %s criado com sucesso.", output_path)
    except OSError as exc:
        logging.error("Erro ao salvar o arquivo JSON: %s", exc)


def main():
    logging.info("Iniciando a atualizacao dos dados de focos de calor do INPE.")
    arquivos = _listar_arquivos_inpe(BASE_URL)
    if not arquivos:
        logging.error("Processo interrompido: nao foi possivel obter arquivos do INPE.")
        return

    ultimo_arquivo = max(arquivos, key=lambda item: item["data"])
    ano_referencia = ultimo_arquivo["data"].year
    inicio_panorama = date(ano_referencia, 6, 1)
    arquivos_panorama = [
        item for item in arquivos if inicio_panorama <= item["data"] <= ultimo_arquivo["data"]
    ]

    tempo_real = _processar_arquivos([ultimo_arquivo], MUNICIPIOS_OESTE, "Focos incendio em tempo real")
    panorama = _processar_arquivos(
        arquivos_panorama,
        MUNICIPIOS_OESTE,
        "Panorama do Fogo desde junho",
    )

    _save_geojson(tempo_real, OUTPUT_TEMPO_REAL)
    _save_geojson(panorama, OUTPUT_PANORAMA)
    logging.info("Processo de atualizacao finalizado com sucesso.")


if __name__ == "__main__":
    main()
