import gzip
import json
import shutil
from pathlib import Path

import shapefile
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid


BASE_DIR = Path(__file__).resolve().parent
PASTA_ORIGEM = BASE_DIR / "Unidades_de_Conservacao"
ARQUIVO_ORIGEM = PASTA_ORIGEM / "Unidades_de_Conservacao.shp"
ARQUIVO_LIMITES = BASE_DIR / "limites_municipios_oeste.json"
ARQUIVO_DESTINO = BASE_DIR / "unidades_conservacao_oeste.geojson"
TOLERANCIA_GRAUS = 0.00008


def carregar_regiao():
    with ARQUIVO_LIMITES.open(encoding="utf-8") as arquivo:
        limites = json.load(arquivo)
    geometrias = [shape(feature["geometry"]) for feature in limites["features"]]
    return unary_union(geometrias)


def normalizar_valor(valor):
    if isinstance(valor, str):
        return valor.strip()
    return valor


def converter():
    regiao = carregar_regiao()
    leitor = shapefile.Reader(str(ARQUIVO_ORIGEM), encoding="utf-8")
    campos = [campo[0] for campo in leitor.fields[1:]]
    gravadas = 0

    with ARQUIVO_DESTINO.open("w", encoding="utf-8") as saida:
        saida.write('{"type":"FeatureCollection","features":[')
        primeira = True

        for registro in leitor.iterShapeRecords():
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

        saida.write('],"metadata":')
        json.dump(
            {
                "fonte": "Unidades de Conservacao",
                "regiao": "Oeste da Bahia",
                "feicoes": gravadas,
                "tolerancia_graus": TOLERANCIA_GRAUS,
            },
            saida,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        saida.write("}")

    arquivo_gzip = ARQUIVO_DESTINO.with_suffix(f"{ARQUIVO_DESTINO.suffix}.gz")
    with ARQUIVO_DESTINO.open("rb") as origem, gzip.open(
        arquivo_gzip, "wb", compresslevel=9
    ) as destino:
        shutil.copyfileobj(origem, destino)

    print(
        f"{ARQUIVO_DESTINO.name}: {gravadas} feicoes, "
        f"{ARQUIVO_DESTINO.stat().st_size / (1024 * 1024):.2f} MB "
        f"({arquivo_gzip.stat().st_size / (1024 * 1024):.2f} MB gzip)"
    )


if __name__ == "__main__":
    converter()
