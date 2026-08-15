import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/"
NASA_FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
NASA_FIRMS_BBOX = "-46.6,-15.4,-42.4,-10.0"
NASA_FIRMS_DEFAULT_SOURCES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
]
CSV_PATTERN = r"focos_diario_br_(\d{8})\.csv"
OUTPUT_TEMPO_REAL = "focos_oeste_ba.json"
OUTPUT_PANORAMA = "panorama_fogo_oeste_ba.json"
ARQUIVO_LIMITES = "limites_municipios_oeste.json"
DIAS_TEMPO_REAL_PADRAO = 3

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
    "Ibotirama",
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


def _valor_float(valor):
    numero = pd.to_numeric(valor, errors="coerce")
    if pd.isna(numero):
        return None
    return float(numero)


def _linha_para_feature_inpe(row, colunas, item):
    municipio = str(row.get(colunas["municipio"], "N/A")).strip()
    return {
        "type": "Feature",
        "properties": {
            "fonte": "INPE",
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
            features.append(_linha_para_feature_inpe(row, colunas, item))

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
            "sources": ["INPE"],
            "region": "Oeste da Bahia",
            "period_name": nome_periodo,
            "period_start": periodo_inicio,
            "period_end": periodo_fim,
            "processed_files": len(arquivos_processados),
            "total_features": len(features),
        },
        "features": features,
    }


def _carregar_municipios_geojson(caminho=ARQUIVO_LIMITES):
    if not os.path.exists(caminho):
        logging.warning("Arquivo de limites municipais nao encontrado: %s", caminho)
        return []

    try:
        with open(caminho, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Nao foi possivel carregar limites municipais: %s", exc)
        return []

    municipios_normalizados = {normalizar_texto(nome) for nome in MUNICIPIOS_OESTE}
    municipios = []
    for feature in dados.get("features", []):
        propriedades = feature.get("properties", {})
        nome = _nome_municipio_geojson(propriedades)
        nome_normalizado = normalizar_texto(nome)
        if nome_normalizado not in municipios_normalizados:
            continue

        municipios.append(
            {
                "nome": nome,
                "normalizado": nome_normalizado,
                "geometry": feature.get("geometry", {}),
            }
        )

    return municipios


def _nome_municipio_geojson(propriedades):
    return (
        propriedades.get("NM_MUN")
        or propriedades.get("NM_MUNICIP")
        or propriedades.get("NM_MUNICIPIO")
        or propriedades.get("nome")
        or propriedades.get("NOME")
        or propriedades.get("municipio")
        or "Municipio"
    )


def _ponto_no_anel(lon, lat, anel):
    dentro = False
    total = len(anel)
    if total < 3:
        return False

    j = total - 1
    for i in range(total):
        xi, yi = anel[i][0], anel[i][1]
        xj, yj = anel[j][0], anel[j][1]
        cruza = (yi > lat) != (yj > lat)
        if cruza:
            lon_intersecao = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < lon_intersecao:
                dentro = not dentro
        j = i

    return dentro


def _ponto_no_poligono(lon, lat, poligono):
    if not poligono or not _ponto_no_anel(lon, lat, poligono[0]):
        return False

    for buraco in poligono[1:]:
        if _ponto_no_anel(lon, lat, buraco):
            return False

    return True


def _municipio_por_coordenada(lon, lat, municipios):
    for municipio in municipios:
        geometria = municipio["geometry"]
        tipo = geometria.get("type")
        coordenadas = geometria.get("coordinates", [])

        if tipo == "Polygon":
            poligonos = [coordenadas]
        elif tipo == "MultiPolygon":
            poligonos = coordenadas
        else:
            continue

        if any(_ponto_no_poligono(lon, lat, poligono) for poligono in poligonos):
            return municipio

    return None


def _fontes_nasa():
    fontes = os.getenv("NASA_FIRMS_SOURCES")
    if not fontes:
        return NASA_FIRMS_DEFAULT_SOURCES

    return [fonte.strip() for fonte in fontes.split(",") if fonte.strip()]


def _nasa_firms_map_key():
    chave = os.getenv("NASA_FIRMS_MAP_KEY", "").strip()
    if chave:
        return chave

    caminho_chave = os.getenv("NASA_FIRMS_MAP_KEY_FILE", "nasa_firms_map_key.txt")
    if not os.path.exists(caminho_chave):
        return ""

    try:
        with open(caminho_chave, encoding="utf-8") as arquivo:
            return arquivo.read().strip()
    except OSError as exc:
        logging.warning("Nao foi possivel ler a chave NASA FIRMS: %s", exc)
        return ""


def _normalizar_satelite_nasa(satelite, instrumento):
    satelite_txt = str(satelite or "").strip().upper()
    instrumento_txt = str(instrumento or "").strip().upper()

    mapa = {
        "N": "Suomi NPP",
        "SNPP": "Suomi NPP",
        "NPP": "Suomi NPP",
        "J1": "NOAA-20",
        "N20": "NOAA-20",
        "J2": "NOAA-21",
        "N21": "NOAA-21",
        "T": "Terra",
        "A": "Aqua",
    }
    nome_satelite = mapa.get(satelite_txt, satelite_txt or "N/A")
    nome_instrumento = instrumento_txt or "FIRMS"
    return f"NASA {nome_instrumento} {nome_satelite}".strip()


def _data_hora_nasa(row):
    data = str(row.get("acq_date", "")).strip()
    hora = str(row.get("acq_time", "")).strip().zfill(4)
    if not data or len(hora) != 4:
        return "N/A"

    return f"{data} {hora[:2]}:{hora[2:]}:00"


def _linha_para_feature_nasa(row, municipio, fonte):
    lat = _valor_float(row.get("latitude"))
    lon = _valor_float(row.get("longitude"))
    if lat is None or lon is None:
        return None

    instrumento = row.get("instrument") or fonte.split("_")[0]
    satelite = row.get("satellite")
    municipio_nome = municipio["nome"]

    return {
        "type": "Feature",
        "properties": {
            "fonte": "NASA FIRMS",
            "fonte_dados": fonte,
            "satelite": _normalizar_satelite_nasa(satelite, instrumento),
            "data_hora": _data_hora_nasa(row),
            "municipio": municipio_nome,
            "municipio_normalizado": municipio["normalizado"],
            "estado": "BA",
            "risco_fogo": None,
            "bioma": "N/A",
            "frp": _valor_json(row.get("frp"), None),
            "confianca": _valor_json(row.get("confidence"), None),
            "brilho": _valor_json(row.get("brightness") or row.get("bright_ti4"), None),
            "arquivo_origem": f"NASA_FIRMS_{fonte}",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
    }


def _baixar_focos_nasa(dias, nome_periodo):
    chave = _nasa_firms_map_key()
    if not chave:
        logging.info("Chave NASA FIRMS nao configurada. Integracao NASA FIRMS ignorada.")
        return []

    municipios = _carregar_municipios_geojson()
    if not municipios:
        logging.warning("Sem limites municipais carregados. NASA FIRMS ignorado.")
        return []

    features = []
    dias = max(1, min(int(dias), 10))
    for fonte in _fontes_nasa():
        url = f"{NASA_FIRMS_AREA_URL}/{chave}/{fonte}/{NASA_FIRMS_BBOX}/{dias}"
        logging.info("Baixando NASA FIRMS (%s) para %s: %s", fonte, nome_periodo, url)
        try:
            df = pd.read_csv(url)
        except Exception as exc:
            logging.warning("NASA FIRMS ignorado para %s: %s", fonte, exc)
            continue

        for _, row in df.iterrows():
            lat = _valor_float(row.get("latitude"))
            lon = _valor_float(row.get("longitude"))
            if lat is None or lon is None:
                continue

            municipio = _municipio_por_coordenada(lon, lat, municipios)
            if not municipio:
                continue

            feature = _linha_para_feature_nasa(row, municipio, fonte)
            if feature:
                features.append(feature)

    logging.info("Encontrados %s focos NASA FIRMS para %s.", len(features), nome_periodo)
    return features


def _mesclar_fontes(geojson_data, features_nasa):
    if not features_nasa:
        return geojson_data

    geojson_data["features"].extend(features_nasa)
    metadata = geojson_data.setdefault("metadata", {})
    fontes = set(metadata.get("sources", []))
    fontes.add("INPE")
    fontes.add("NASA FIRMS")
    metadata["sources"] = sorted(fontes)
    metadata["nasa_firms_features"] = len(features_nasa)
    metadata["total_features"] = len(geojson_data["features"])
    return geojson_data


def _janela_tempo_real_inpe(arquivos, ultimo_arquivo):
    dias = os.getenv("INPE_DIAS_TEMPO_REAL", str(DIAS_TEMPO_REAL_PADRAO))
    try:
        dias = max(1, int(dias))
    except ValueError:
        dias = DIAS_TEMPO_REAL_PADRAO

    return sorted(arquivos, key=lambda item: item["data"])[-dias:]


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

    arquivos_tempo_real = _janela_tempo_real_inpe(arquivos, ultimo_arquivo)
    tempo_real = _processar_arquivos(
        arquivos_tempo_real,
        MUNICIPIOS_OESTE,
        "Focos incendio em tempo real",
    )
    panorama = _processar_arquivos(
        arquivos_panorama,
        MUNICIPIOS_OESTE,
        "Panorama do Fogo desde junho",
    )

    focos_nasa_tempo_real = _baixar_focos_nasa(
        os.getenv("NASA_FIRMS_DIAS_TEMPO_REAL", "1"),
        "Focos incendio em tempo real",
    )
    focos_nasa_panorama = _baixar_focos_nasa(
        os.getenv("NASA_FIRMS_DIAS_PANORAMA", "5"),
        "Panorama do Fogo desde junho",
    )

    tempo_real = _mesclar_fontes(tempo_real, focos_nasa_tempo_real)
    panorama = _mesclar_fontes(panorama, focos_nasa_panorama)

    _save_geojson(tempo_real, OUTPUT_TEMPO_REAL)
    _save_geojson(panorama, OUTPUT_PANORAMA)
    logging.info("Processo de atualizacao finalizado com sucesso.")


if __name__ == "__main__":
    main()
