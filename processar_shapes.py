import argparse
import gzip
import json
import logging
import unicodedata
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DEFAULT_SHAPEFILE_PATH = "BR_Municipios_2022.shp"
OUTPUT_FILENAME = "limites_municipios_oeste.json"
IBGE_MALHAS_BA_URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados/29"
    "?formato=application/vnd.geo+json&qualidade=intermediaria&intrarregiao=municipio"
)
IBGE_MUNICIPIOS_BA_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/29/municipios"

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
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    return texto


def escolher_coluna(gdf, candidatas):
    for coluna in candidatas:
        if coluna in gdf.columns:
            return coluna
    return None


def processar_shapefile(shapefile_path, output_filename):
    """Le shapefile de municipios, filtra o oeste da Bahia e salva em GeoJSON."""
    import geopandas as gpd

    caminho = Path(shapefile_path)
    if not caminho.exists():
        raise FileNotFoundError(
            f"Shapefile nao encontrado: {caminho}. Informe o caminho com --shapefile."
        )

    logging.info("Lendo o shapefile de: %s", caminho)
    gdf = gpd.read_file(caminho)

    coluna_nome = escolher_coluna(gdf, ["NM_MUN", "NM_MUNICIP", "NM_MUNICIPIO", "nome", "NOME"])
    if not coluna_nome:
        raise ValueError(f"Nenhuma coluna de nome de municipio encontrada. Colunas: {list(gdf.columns)}")

    coluna_uf = escolher_coluna(gdf, ["SIGLA_UF", "UF", "CD_UF"])
    if coluna_uf:
        valores_bahia = {"BA", "29", 29}
        gdf = gdf[gdf[coluna_uf].isin(valores_bahia)]

    municipios_normalizados = {normalizar_texto(nome) for nome in MUNICIPIOS_OESTE}
    gdf = gdf.copy()
    gdf["municipio_normalizado"] = gdf[coluna_nome].apply(normalizar_texto)
    gdf_filtrado = gdf[gdf["municipio_normalizado"].isin(municipios_normalizados)].copy()

    faltantes = sorted(municipios_normalizados - set(gdf_filtrado["municipio_normalizado"]))
    if faltantes:
        logging.warning("Municipios nao encontrados no shapefile: %s", ", ".join(faltantes))

    if gdf_filtrado.empty:
        raise ValueError("Nenhum municipio da lista foi encontrado no shapefile informado.")

    if gdf_filtrado.crs and gdf_filtrado.crs.to_epsg() != 4326:
        gdf_filtrado = gdf_filtrado.to_crs(epsg=4326)

    gdf_filtrado.to_file(output_filename, driver="GeoJSON", encoding="utf-8")
    logging.info("Arquivo '%s' criado com %s municipios.", output_filename, len(gdf_filtrado))


def baixar_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()

    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)

    return json.loads(raw.decode("utf-8"))


def processar_ibge_online(output_filename):
    """Baixa malhas municipais da Bahia pela API do IBGE e filtra o oeste."""
    logging.info("Baixando lista de municipios da Bahia pelo IBGE...")
    municipios = baixar_json(IBGE_MUNICIPIOS_BA_URL)

    nomes_por_codigo = {str(item["id"]): item["nome"] for item in municipios}
    codigos_por_nome = {normalizar_texto(nome): codigo for codigo, nome in nomes_por_codigo.items()}
    municipios_normalizados = {normalizar_texto(nome) for nome in MUNICIPIOS_OESTE}
    codigos_oeste = {
        codigos_por_nome[nome]
        for nome in municipios_normalizados
        if nome in codigos_por_nome
    }

    faltantes = sorted(municipios_normalizados - set(codigos_por_nome))
    if faltantes:
        logging.warning("Municipios nao encontrados na API de localidades: %s", ", ".join(faltantes))

    logging.info("Baixando malha municipal da Bahia pelo IBGE...")
    geojson = baixar_json(IBGE_MALHAS_BA_URL)
    features = []

    for feature in geojson.get("features", []):
        codigo = str(feature.get("properties", {}).get("codarea", ""))
        if codigo not in codigos_oeste:
            continue

        nome = nomes_por_codigo.get(codigo, "Municipio")
        feature["properties"] = {
            **feature.get("properties", {}),
            "NM_MUN": nome,
            "municipio_normalizado": normalizar_texto(nome),
        }
        features.append(feature)

    if not features:
        raise ValueError("Nenhum municipio do oeste foi encontrado na malha online do IBGE.")

    saida = {"type": "FeatureCollection", "features": features}
    with open(output_filename, "w", encoding="utf-8") as file:
        json.dump(saida, file, ensure_ascii=False)

    logging.info("Arquivo '%s' criado com %s municipios.", output_filename, len(features))


def main():
    parser = argparse.ArgumentParser(description="Gera GeoJSON dos municipios do oeste da Bahia.")
    parser.add_argument(
        "--shapefile",
        default=None,
        help="Caminho do .shp de municipios do IBGE. Se omitido, usa a API oficial do IBGE.",
    )
    parser.add_argument(
        "--saida",
        default=OUTPUT_FILENAME,
        help="Arquivo GeoJSON de saida.",
    )
    args = parser.parse_args()

    try:
        if args.shapefile:
            processar_shapefile(args.shapefile, args.saida)
        elif Path(DEFAULT_SHAPEFILE_PATH).exists():
            processar_shapefile(DEFAULT_SHAPEFILE_PATH, args.saida)
        else:
            processar_ibge_online(args.saida)
    except Exception as exc:
        logging.error("Falha ao processar o shapefile: %s", exc)


if __name__ == "__main__":
    main()
