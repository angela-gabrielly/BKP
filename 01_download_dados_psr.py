from pathlib import Path
import re
import time
import requests
from tqdm.auto import tqdm


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# Altere para a pasta onde deseja armazenar o projeto
PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_RAW = PASTA_PROJETO / "data" / "raw"
PASTA_DOCUMENTACAO = PASTA_PROJETO / "data" / "documentacao"
PASTA_LOGS = PASTA_PROJETO / "logs"

PASTA_RAW.mkdir(parents=True, exist_ok=True)
PASTA_DOCUMENTACAO.mkdir(parents=True, exist_ok=True)
PASTA_LOGS.mkdir(parents=True, exist_ok=True)


# API oficial CKAN do Portal de Dados Abertos do MAPA
URL_API_CKAN = (
    "https://dados.agricultura.gov.br/api/3/action/"
    "package_show?id=sisser3"
)

TIMEOUT = 120
TENTATIVAS = 3
TAMANHO_BLOCO = 1024 * 1024  # 1 MB


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def limpar_nome_arquivo(nome):
    """
    Remove caracteres inválidos para nomes de arquivos no Windows.
    """
    nome = str(nome).strip()
    nome = re.sub(r'[\\/:*?"<>|]+', "_", nome)
    nome = re.sub(r"\s+", "_", nome)
    return nome.lower()


def obter_extensao_recurso(recurso):
    """
    Define a extensão com base no formato informado pelo CKAN
    ou, caso necessário, pela URL do recurso.
    """
    formato = str(recurso.get("format", "")).strip().lower()

    if formato:
        return f".{formato}"

    url = str(recurso.get("url", "")).split("?")[0]

    if "." in url.rsplit("/", 1)[-1]:
        return "." + url.rsplit(".", 1)[-1].lower()

    return ""


def baixar_arquivo(url, destino, sobrescrever=False):
    """
    Baixa arquivos grandes por streaming, com barra de progresso
    e tentativas automáticas em caso de falha.
    """
    destino = Path(destino)

    if destino.exists() and not sobrescrever:
        tamanho_mb = destino.stat().st_size / (1024 ** 2)
        print(f"Arquivo já existe: {destino.name} ({tamanho_mb:,.2f} MB)")
        return destino

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            print(f"\nBaixando: {destino.name}")
            print(f"Tentativa {tentativa}/{TENTATIVAS}")

            with requests.get(
                url,
                stream=True,
                timeout=TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resposta:

                resposta.raise_for_status()

                tamanho_total = int(
                    resposta.headers.get("content-length", 0)
                )

                with open(destino, "wb") as arquivo, tqdm(
                    total=tamanho_total,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=destino.name,
                ) as barra:

                    for bloco in resposta.iter_content(
                        chunk_size=TAMANHO_BLOCO
                    ):
                        if bloco:
                            arquivo.write(bloco)
                            barra.update(len(bloco))

            tamanho_mb = destino.stat().st_size / (1024 ** 2)
            print(f"Concluído: {destino.name} ({tamanho_mb:,.2f} MB)")

            return destino

        except requests.RequestException as erro:
            print(f"Erro ao baixar {destino.name}: {erro}")

            if destino.exists():
                destino.unlink()

            if tentativa == TENTATIVAS:
                raise RuntimeError(
                    f"Não foi possível baixar o arquivo: {url}"
                ) from erro

            time.sleep(3)

    return None


# ============================================================
# CONSULTA AO CATÁLOGO OFICIAL DO MAPA
# ============================================================

def obter_recursos_psr():
    """
    Consulta o catálogo oficial do MAPA e retorna os recursos
    disponíveis do conjunto SISSER / PSR.
    """
    resposta = requests.get(
        URL_API_CKAN,
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    resposta.raise_for_status()

    dados = resposta.json()

    if not dados.get("success"):
        raise RuntimeError(
            "A API do Portal de Dados Abertos retornou sucesso=False."
        )

    recursos = dados["result"]["resources"]

    return recursos


def selecionar_recursos_interesse(recursos):
    """
    Mantém:
    - todos os CSVs do PSR;
    - o PDF do dicionário de dados.

    Ignora XLSX para evitar download duplicado e arquivos
    maiores sem necessidade nesta primeira etapa.
    """
    recursos_selecionados = []

    for recurso in recursos:
        nome = str(recurso.get("name", "")).strip()
        formato = str(recurso.get("format", "")).strip().lower()

        nome_lower = nome.lower()

        eh_csv_psr = (
            formato == "csv"
            and "psr" in nome_lower
        )

        eh_dicionario = (
            "dicion" in nome_lower
            and formato == "pdf"
        )

        if eh_csv_psr or eh_dicionario:
            recursos_selecionados.append(recurso)

    return recursos_selecionados


# ============================================================
# DOWNLOAD DOS DADOS
# ============================================================

recursos = obter_recursos_psr()
recursos_selecionados = selecionar_recursos_interesse(recursos)

print("Recursos encontrados no catálogo oficial:\n")

for recurso in recursos_selecionados:
    print(
        f"- {recurso.get('name')} | "
        f"Formato: {recurso.get('format')} | "
        f"Atualizado em: {recurso.get('last_modified')}"
    )

if not recursos_selecionados:
    raise RuntimeError(
        "Nenhum recurso CSV/PDF do PSR foi encontrado no catálogo."
    )

arquivos_baixados = []

for recurso in recursos_selecionados:
    nome_recurso = recurso.get("name", "arquivo_psr")
    url_recurso = recurso.get("url")

    if not url_recurso:
        print(f"Recurso ignorado sem URL: {nome_recurso}")
        continue

    extensao = obter_extensao_recurso(recurso)

    nome_arquivo = limpar_nome_arquivo(nome_recurso)

    if extensao and not nome_arquivo.endswith(extensao):
        nome_arquivo += extensao

    formato = str(recurso.get("format", "")).lower()

    if formato == "pdf":
        destino = PASTA_DOCUMENTACAO / nome_arquivo
    else:
        destino = PASTA_RAW / nome_arquivo

    arquivo = baixar_arquivo(
        url=url_recurso,
        destino=destino,
        sobrescrever=False
    )

    arquivos_baixados.append(arquivo)


# ============================================================
# RESUMO FINAL
# ============================================================

print("\n" + "=" * 70)
print("DOWNLOAD FINALIZADO")
print("=" * 70)

for arquivo in arquivos_baixados:
    if arquivo is not None and arquivo.exists():
        tamanho_mb = arquivo.stat().st_size / (1024 ** 2)
        print(f"{arquivo.name} | {tamanho_mb:,.2f} MB")

print("\nEstrutura criada:")
print(f"- Dados brutos: {PASTA_RAW}")
print(f"- Documentação: {PASTA_DOCUMENTACAO}")
print(f"- Logs: {PASTA_LOGS}")

