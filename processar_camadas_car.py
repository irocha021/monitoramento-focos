import gzip
import json
import shutil
from pathlib import Path

import shapefile
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid


BASE_DIR = Path(__file__).resolve().parent
PASTA_ORIGEM = BASE_DIR / "Focos_incendio_add"
ARQUIVO_LIMITES = BASE_DIR / "limites_municipios_oeste.json"
TOLERANCIA_GRAUS = 0.00015

CAMADAS = {
    "Imovel_Rural_APP.shp": BASE_DIR / "imovel_rural_app_oeste.geojson",
    "Imovel_Rural_Reserva_Legal.shp": BASE_DIR / "imovel_rural_reserva_legal_oeste.geojson",
}


def carregar_regiao():
    with ARQUIVO_LIMITES.open(encoding="utf-8") as arquivo:
        limites = json.load(arquivo)
    geometrias = [shape(feature["geometry"]) for feature in limites["features"]]
    return unary_union(geometrias)


def normalizar_valor(valor):
    if isinstance(valor, str):
        return valor.strip()
    return valor


def converter_camada(arquivo_origem, arquivo_destino, regiao):
    leitor = shapefile.Reader(str(arquivo_origem), encoding="utf-8")
    campos = [campo[0] for campo in leitor.fields[1:]]
    total = len(leitor)
    gravadas = 0

    with arquivo_destino.open("w", encoding="utf-8") as saida:
        saida.write('{"type":"FeatureCollection","features":[')
        primeira = True

        for indice, registro in enumerate(leitor.iterShapeRecords(), start=1):
            geometria = shape(registro.shape.__geo_interface__)
            if geometria.is_empty or not geometria.intersects(regiao):
                continue

            if not geometria.is_valid:
                geometria = make_valid(geometria)

            if not regiao.covers(geometria):
                geometria = geometria.intersection(regiao)

            geometria = geometria.simplify(TOLERANCIA_GRAUS, preserve_topology=True)
            if geometria.is_empty:
                continue

            propriedades = {
                campo.lower(): normalizar_valor(valor)
                for campo, valor in zip(campos, registro.record)
            }
            feature = {
                "type": "Feature",
                "properties": propriedades,
                "geometry": mapping(geometria),
            }

            if not primeira:
                saida.write(",")
            json.dump(feature, saida, ensure_ascii=False, separators=(",", ":"))
            primeira = False
            gravadas += 1

            if indice % 10000 == 0:
                print(f"{arquivo_origem.name}: {indice}/{total}")

        saida.write('],"metadata":')
        json.dump(
            {
                "fonte": "Cadastro Ambiental Rural",
                "regiao": "Oeste da Bahia",
                "feicoes": gravadas,
                "tolerancia_graus": TOLERANCIA_GRAUS,
            },
            saida,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        saida.write("}")

    tamanho_mb = arquivo_destino.stat().st_size / (1024 * 1024)
    arquivo_gzip = arquivo_destino.with_suffix(f"{arquivo_destino.suffix}.gz")
    with arquivo_destino.open("rb") as origem, gzip.open(
        arquivo_gzip, "wb", compresslevel=9
    ) as destino:
        shutil.copyfileobj(origem, destino)

    tamanho_gzip_mb = arquivo_gzip.stat().st_size / (1024 * 1024)
    print(
        f"{arquivo_destino.name}: {gravadas} feicoes, "
        f"{tamanho_mb:.1f} MB ({tamanho_gzip_mb:.1f} MB gzip)"
    )


def main():
    regiao = carregar_regiao()
    for nome_origem, arquivo_destino in CAMADAS.items():
        converter_camada(PASTA_ORIGEM / nome_origem, arquivo_destino, regiao)


if __name__ == "__main__":
    main()
