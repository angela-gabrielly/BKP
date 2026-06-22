from pathlib import Path
import csv
import re
import unicodedata

import pandas as pd


# ============================================================
# CONFIGURAÇÃO
# ============================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_RAW = PASTA_PROJETO / "data" / "raw"
PASTA_INTERIM = PASTA_PROJETO / "data" / "interim"

PASTA_INTERIM.mkdir(parents=True, exist_ok=True)

N_LINHAS_AMOSTRA = 5_000

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 120)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def normalizar_texto(valor):
    """
    Padroniza textos para uso em nomes de colunas e comparações.
    Exemplo:
    'Prêmio Total (R$)' -> 'premio_total_r'
    """
    valor = str(valor).strip().lower()

    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(
        caractere
        for caractere in valor
        if not unicodedata.combining(caractere)
    )

    valor = re.sub(r"[^a-z0-9]+", "_", valor)
    valor = re.sub(r"_+", "_", valor)

    return valor.strip("_")


def detectar_codificacao(caminho_arquivo, tamanho_amostra_bytes=500_000):
    """
    Tenta identificar uma codificação compatível com o arquivo.
    """
    codificacoes_teste = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1",
    ]

    with open(caminho_arquivo, "rb") as arquivo:
        conteudo = arquivo.read(tamanho_amostra_bytes)

    for codificacao in codificacoes_teste:
        try:
            texto = conteudo.decode(codificacao)

            # Evita aceitar uma decodificação muito corrompida.
            if texto.count("\ufffd") == 0:
                return codificacao

        except UnicodeDecodeError:
            continue

    return "latin1"


def detectar_separador(caminho_arquivo, codificacao, tamanho_amostra_bytes=500_000):
    """
    Detecta o separador mais provável entre ; , | ou tab.
    """
    with open(caminho_arquivo, "rb") as arquivo:
        conteudo = arquivo.read(tamanho_amostra_bytes)

    texto = conteudo.decode(codificacao, errors="replace")

    try:
        dialecto = csv.Sniffer().sniff(
            texto,
            delimiters=";,\t|"
        )
        return dialecto.delimiter

    except csv.Error:
        candidatos = [";", ",", "\t", "|"]

        contagens = {
            separador: texto.count(separador)
            for separador in candidatos
        }

        return max(contagens, key=contagens.get)


def extrair_periodo_arquivo(nome_arquivo):
    """
    Extrai um identificador de período a partir do nome do arquivo.
    """
    nome = nome_arquivo.lower()

    anos = re.findall(r"\d{4}", nome)

    if len(anos) >= 2:
        return f"{anos[0]}_{anos[1]}"

    if len(anos) == 1:
        return anos[0]

    return "nao_identificado"


def gerar_exemplos_serie(serie, limite=5):
    """
    Gera alguns exemplos não nulos de uma coluna.
    """
    valores = (
        serie.dropna()
        .astype(str)
        .str.strip()
    )

    valores = valores[
        valores.ne("")
    ].drop_duplicates()

    return " | ".join(valores.head(limite).tolist())


# ============================================================
# LOCALIZA OS CSVs
# ============================================================

arquivos_csv = sorted(PASTA_RAW.glob("*.csv"))

if not arquivos_csv:
    raise FileNotFoundError(
        f"Nenhum CSV encontrado em: {PASTA_RAW}"
    )

print("Arquivos localizados:\n")

for arquivo in arquivos_csv:
    tamanho_mb = arquivo.stat().st_size / (1024 ** 2)
    print(f"- {arquivo.name} | {tamanho_mb:,.2f} MB")


# ============================================================
# INSPEÇÃO DOS ARQUIVOS
# ============================================================

lista_metadados = []
lista_colunas = []
lista_perfis = []
lista_amostras = []

for caminho_csv in arquivos_csv:

    print("\n" + "=" * 90)
    print(f"INSPECIONANDO: {caminho_csv.name}")
    print("=" * 90)

    codificacao = detectar_codificacao(caminho_csv)
    separador = detectar_separador(
        caminho_arquivo=caminho_csv,
        codificacao=codificacao
    )

    print(f"Codificação detectada: {codificacao}")
    print(f"Separador detectado: {repr(separador)}")

    try:
        df_amostra = pd.read_csv(
            caminho_csv,
            sep=separador,
            encoding=codificacao,
            nrows=N_LINHAS_AMOSTRA,
            dtype="string",
            low_memory=False,
            on_bad_lines="warn",
        )

    except Exception as erro:
        raise RuntimeError(
            f"Erro ao ler o arquivo {caminho_csv.name}"
        ) from erro

    colunas_originais = df_amostra.columns.tolist()
    colunas_normalizadas = [
        normalizar_texto(coluna)
        for coluna in colunas_originais
    ]

    duplicadas_normalizadas = (
        pd.Series(colunas_normalizadas)
        .duplicated()
        .sum()
    )

    print(f"Linhas lidas na amostra: {len(df_amostra):,}")
    print(f"Quantidade de colunas: {len(colunas_originais)}")
    print(f"Colunas normalizadas duplicadas: {duplicadas_normalizadas}")

    print("\nColunas originais:")
    for indice, coluna in enumerate(colunas_originais, start=1):
        print(f"{indice:02d}. {coluna}")

    tamanho_mb = caminho_csv.stat().st_size / (1024 ** 2)
    periodo = extrair_periodo_arquivo(caminho_csv.name)

    lista_metadados.append(
        {
            "arquivo": caminho_csv.name,
            "periodo_origem": periodo,
            "tamanho_mb": round(tamanho_mb, 2),
            "codificacao": codificacao,
            "separador": repr(separador),
            "linhas_amostra": len(df_amostra),
            "quantidade_colunas": len(colunas_originais),
            "colunas_normalizadas_duplicadas": duplicadas_normalizadas,
        }
    )

    for ordem, (coluna_original, coluna_normalizada) in enumerate(
        zip(colunas_originais, colunas_normalizadas),
        start=1
    ):
        lista_colunas.append(
            {
                "arquivo": caminho_csv.name,
                "periodo_origem": periodo,
                "ordem_coluna": ordem,
                "coluna_original": coluna_original,
                "coluna_normalizada": coluna_normalizada,
            }
        )

        lista_perfis.append(
    {
        "arquivo": caminho_csv.name,
        "periodo_origem": periodo,
        "ordem_coluna": ordem,
        "coluna_original": coluna_original,
        "coluna_normalizada": coluna_normalizada,
        "tipo_lido_amostra": str(df_amostra[coluna_original].dtype),
        "quantidade_nulos_amostra": int(
            df_amostra[coluna_original].isna().sum()
        ),
        "percentual_nulos_amostra": round(
            df_amostra[coluna_original].isna().mean() * 100,
            2
        ),
        "exemplos_valores": gerar_exemplos_serie(
            df_amostra[coluna_original]
        ),
    }

        )

    # Salva amostra bruta, preservando as colunas do arquivo original.
    df_amostra.insert(0, "arquivo_origem", caminho_csv.name)
    df_amostra.insert(1, "periodo_origem", periodo)

    lista_amostras.append(df_amostra)


# ============================================================
# CONSOLIDA E SALVA OS DIAGNÓSTICOS
# ============================================================

df_metadados = pd.DataFrame(lista_metadados)

df_colunas = (
    pd.DataFrame(lista_colunas)
    .sort_values(
        ["arquivo", "ordem_coluna"]
    )
    .reset_index(drop=True)
)

df_perfis = (
    pd.DataFrame(lista_perfis)
    .sort_values(
        ["arquivo", "ordem_coluna"]
    )
    .reset_index(drop=True)
)

df_amostra_consolidada = pd.concat(
    lista_amostras,
    ignore_index=True,
    sort=False
)

caminho_metadados = (
    PASTA_INTERIM / "psr_metadados_arquivos.csv"
)

caminho_colunas = (
    PASTA_INTERIM / "psr_dicionario_colunas_origem.csv"
)

caminho_perfis = (
    PASTA_INTERIM / "psr_perfil_colunas_amostra.csv"
)

caminho_amostra = (
    PASTA_INTERIM / "psr_amostra_consolidada.csv"
)

df_metadados.to_csv(
    caminho_metadados,
    index=False,
    encoding="utf-8-sig"
)

df_colunas.to_csv(
    caminho_colunas,
    index=False,
    encoding="utf-8-sig"
)

df_perfis.to_csv(
    caminho_perfis,
    index=False,
    encoding="utf-8-sig"
)

df_amostra_consolidada.to_csv(
    caminho_amostra,
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# RESUMO FINAL
# ============================================================

print("\n" + "=" * 90)
print("INSPEÇÃO FINALIZADA")
print("=" * 90)

print("\nResumo dos arquivos:")
print(df_metadados.to_string(index=False))

print("\nArquivos gerados:")

for caminho_saida in [
    caminho_metadados,
    caminho_colunas,
    caminho_perfis,
    caminho_amostra,
]:
    tamanho_mb = caminho_saida.stat().st_size / (1024 ** 2)
    print(f"- {caminho_saida.name} | {tamanho_mb:,.2f} MB")

print(f"\nPasta de saída: {PASTA_INTERIM}")