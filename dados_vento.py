import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

OUTPUT_VENTO = "vento_oeste_ba.json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

PONTOS_VENTO = [
    {"nome": "Barreiras", "lat": -12.1528, "lon": -44.99},
    {"nome": "Luís Eduardo Magalhães", "lat": -12.0956, "lon": -45.7866},
    {"nome": "São Desidério", "lat": -12.3633, "lon": -44.9736},
    {"nome": "Riachao das Neves", "lat": -11.7461, "lon": -44.91},
    {"nome": "Formosa do Rio Preto", "lat": -11.0483, "lon": -45.1931},
    {"nome": "Correntina", "lat": -13.3475, "lon": -44.6367},
    {"nome": "Santa Maria da Vitoria", "lat": -13.3972, "lon": -44.1986},
    {"nome": "Bom Jesus da Lapa", "lat": -13.255, "lon": -43.4186},
    {"nome": "Ibotirama", "lat": -12.1853, "lon": -43.2206},
    {"nome": "Barra", "lat": -11.0894, "lon": -43.1417},
    {"nome": "Cocos", "lat": -14.1814, "lon": -44.535},
    {"nome": "Jaborandi", "lat": -13.6231, "lon": -44.4597},
]


def obter_vento_ponto(ponto):
    params = urllib.parse.urlencode(
        {
            "latitude": ponto["lat"],
            "longitude": ponto["lon"],
            "current": "wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "kmh",
            "timezone": "America/Sao_Paulo",
        }
    )
    url = f"{OPEN_METEO_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "monitoramento-aiba/1.0"})

    with urllib.request.urlopen(req, timeout=30) as response:
        dados = json.loads(response.read().decode("utf-8"))

    atual = dados.get("current", {})
    velocidade = float(atual["wind_speed_10m"])
    direcao = float(atual["wind_direction_10m"])

    return {
        **ponto,
        "velocidade": velocidade,
        "direcao": direcao,
        "horario": atual.get("time"),
    }


def main():
    pontos = []
    for ponto in PONTOS_VENTO:
        try:
            pontos.append(obter_vento_ponto(ponto))
            logging.info("Vento atualizado para %s.", ponto["nome"])
        except Exception as exc:
            logging.warning("Falha ao atualizar vento para %s: %s", ponto["nome"], exc)

    dados_saida = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo",
            "region": "Oeste da Bahia",
            "total_points": len(pontos),
        },
        "pontos": pontos,
    }

    with open(OUTPUT_VENTO, "w", encoding="utf-8") as arquivo:
        json.dump(dados_saida, arquivo, ensure_ascii=False, indent=2)

    logging.info("Arquivo %s criado com %s pontos.", OUTPUT_VENTO, len(pontos))


if __name__ == "__main__":
    main()
