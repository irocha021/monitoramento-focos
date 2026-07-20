import json
import logging
import math
import re
import tempfile
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LIMITES_FILENAME = "limites_municipios_oeste.json"
OUTPUT_FILENAME = "risco_meteorologico_oeste_ba.json"

BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/riscofogo_meteorologia/previsto"

CAMADAS = {
    "risco_fogo": {
        "titulo": "Risco de Fogo",
        "diretorio": "risco_fogo",
        "prefixo": "RF.PREV",
        "unidade": "indice",
    },
    "temperatura": {
        "titulo": "Temperatura",
        "diretorio": "temperatura",
        "prefixo": "TEMP.PREV",
        "unidade": "C",
    },
    "precipitacao": {
        "titulo": "Precipitacao",
        "diretorio": "precipitacao",
        "prefixo": "PREC.PREV",
        "unidade": "mm",
    },
    "umidade_relativa": {
        "titulo": "Umidade Relativa",
        "diretorio": "umidade_relativa",
        "prefixo": "UR.PREV",
        "unidade": "%",
    },
}

HORIZONTES = {
    "T0": "Hoje",
    "T1": "1 dia",
    "T2": "2 dias",
    "T3": "3 dias",
}


def normalizar_texto(valor):
    texto = str(valor or "").strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(char for char in texto if unicodedata.category(char) != "Mn")


def iterar_pontos(geometry):
    tipo = geometry.get("type")
    coords = geometry.get("coordinates", [])

    if tipo == "Polygon":
        for ring in coords:
            for lon, lat, *_ in ring:
                yield lon, lat
    elif tipo == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for lon, lat, *_ in ring:
                    yield lon, lat


def centroide_aproximado(geometry):
    pontos = list(iterar_pontos(geometry))
    if not pontos:
        return None

    lon = sum(ponto[0] for ponto in pontos) / len(pontos)
    lat = sum(ponto[1] for ponto in pontos) / len(pontos)
    return lat, lon


def carregar_municipios():
    with open(LIMITES_FILENAME, encoding="utf-8") as file:
        geojson = json.load(file)

    municipios = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        nome = props.get("NM_MUN") or props.get("municipio") or "Municipio"
        centroide = centroide_aproximado(feature.get("geometry", {}))
        if not centroide:
            continue

        municipios.append(
            {
                "municipio": nome,
                "municipio_normalizado": normalizar_texto(nome),
                "lat": centroide[0],
                "lon": centroide[1],
            }
        )

    return municipios


def baixar_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read().decode("utf-8", errors="replace")


def arquivos_disponiveis(camada):
    url = f"{BASE_URL}/{camada['diretorio']}/"
    html = baixar_html(url)
    arquivos = {}

    for nome_arquivo in re.findall(r'href="([^"]+\.tif)"', html):
        match = re.search(r"\.T([0-3])\.tif$", nome_arquivo)
        if not match:
            continue
        horizonte = f"T{match.group(1)}"
        arquivos[horizonte] = url + nome_arquivo

    return arquivos


def baixar_arquivo(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def classificar_valor(tipo, valor):
    if valor is None:
        return "Sem dado", "#9ca3af"

    if tipo == "risco_fogo":
        if valor < 0.15:
            return "Baixo", "#2fa84f"
        if valor < 0.4:
            return "Medio", "#f2c94c"
        if valor < 0.7:
            return "Alto", "#f2994a"
        if valor < 0.95:
            return "Critico", "#eb5757"
        return "Muito critico", "#7f1d1d"

    if tipo == "temperatura":
        if valor < 24:
            return "Amena", "#2d9cdb"
        if valor < 30:
            return "Quente", "#f2c94c"
        if valor < 36:
            return "Muito quente", "#f2994a"
        return "Extrema", "#eb5757"

    if tipo == "precipitacao":
        if valor <= 0.2:
            return "Sem chuva", "#a16207"
        if valor < 5:
            return "Baixa", "#7dd3fc"
        if valor < 20:
            return "Moderada", "#2d9cdb"
        return "Alta", "#1d4ed8"

    if tipo == "umidade_relativa":
        if valor < 20:
            return "Critica", "#eb5757"
        if valor < 30:
            return "Baixa", "#f2994a"
        if valor < 60:
            return "Moderada", "#f2c94c"
        return "Alta", "#2fa84f"

    return "Valor", "#1767a6"


def normalizar_valor(tipo, valor):
    if valor is None or math.isnan(valor):
        return None

    valor = float(valor)
    if tipo == "temperatura" and valor > 100:
        valor -= 273.15

    if tipo in {"risco_fogo", "precipitacao"} and valor < 0:
        return None

    if tipo == "umidade_relativa" and (valor < 0 or valor > 1000):
        return None

    return round(valor, 3)


def amostrar_raster(tipo, horizonte, url, municipios):
    import rasterio
    from rasterio.warp import transform

    logging.info("Baixando raster %s %s: %s", tipo, horizonte, url)
    dados = baixar_arquivo(url)

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as temp:
        temp.write(dados)
        temp_path = temp.name

    features = []
    try:
        with rasterio.open(temp_path) as dataset:
            pontos = [(municipio["lon"], municipio["lat"]) for municipio in municipios]
            if dataset.crs and dataset.crs.to_epsg() != 4326:
                xs, ys = transform("EPSG:4326", dataset.crs, [p[0] for p in pontos], [p[1] for p in pontos])
                pontos_amostra = list(zip(xs, ys))
            else:
                pontos_amostra = pontos

            valores = list(dataset.sample(pontos_amostra))
            for municipio, valor_array in zip(municipios, valores):
                valor = normalizar_valor(tipo, float(valor_array[0]))
                classe, cor = classificar_valor(tipo, valor)
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "tipo": tipo,
                            "horizonte": horizonte,
                            "horizonte_label": HORIZONTES[horizonte],
                            "municipio": municipio["municipio"],
                            "municipio_normalizado": municipio["municipio_normalizado"],
                            "valor": valor,
                            "classe": classe,
                            "cor": cor,
                            "unidade": CAMADAS[tipo]["unidade"],
                            "arquivo_origem": url.split("/")[-1],
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [municipio["lon"], municipio["lat"]],
                        },
                    }
                )
    finally:
        Path(temp_path).unlink(missing_ok=True)

    return features


def gerar_risco_meteorologico():
    municipios = carregar_municipios()
    features = []
    fontes = {}

    for tipo, camada in CAMADAS.items():
        arquivos = arquivos_disponiveis(camada)
        fontes[tipo] = arquivos
        for horizonte, url in sorted(arquivos.items()):
            features.extend(amostrar_raster(tipo, horizonte, url, municipios))

    return {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "region": "Oeste da Bahia",
            "total_municipios": len(municipios),
            "total_features": len(features),
            "fontes": fontes,
            "camadas": CAMADAS,
            "horizontes": HORIZONTES,
        },
        "features": features,
    }


def main():
    dados = gerar_risco_meteorologico()
    with open(OUTPUT_FILENAME, "w", encoding="utf-8") as file:
        json.dump(dados, file, ensure_ascii=False, indent=2, allow_nan=False)
    logging.info("Arquivo %s criado com %s amostras.", OUTPUT_FILENAME, dados["metadata"]["total_features"])


if __name__ == "__main__":
    main()
