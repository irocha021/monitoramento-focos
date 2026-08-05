import json
import unicodedata
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ARQUIVOS = [
    "focos_oeste_ba.json",
    "panorama_fogo_oeste_ba.json",
]
MUNICIPIOS_REMOVIDOS = {
    "PARATINGA",
    "IUIU",
}


def normalizar(valor):
    texto = str(valor or "").strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(char for char in texto if unicodedata.category(char) != "Mn")


def nome_municipio(propriedades):
    return (
        propriedades.get("municipio")
        or propriedades.get("NM_MUN")
        or propriedades.get("NM_MUNICIP")
        or propriedades.get("NM_MUNICIPIO")
        or propriedades.get("nome")
        or propriedades.get("NOME")
        or ""
    )


def filtrar_arquivo(caminho):
    if not caminho.exists():
        print(f"{caminho.name}: arquivo nao encontrado")
        return

    with caminho.open(encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    antes = len(dados.get("features", []))
    dados["features"] = [
        feature
        for feature in dados.get("features", [])
        if normalizar(nome_municipio(feature.get("properties", {})))
        not in MUNICIPIOS_REMOVIDOS
    ]
    depois = len(dados["features"])

    metadata = dados.setdefault("metadata", {})
    metadata["municipios_removidos"] = sorted(MUNICIPIOS_REMOVIDOS)

    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, separators=(",", ":"))

    print(f"{caminho.name}: {antes} -> {depois}")


def main():
    for nome in ARQUIVOS:
        filtrar_arquivo(BASE_DIR / nome)


if __name__ == "__main__":
    main()
