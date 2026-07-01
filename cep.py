import re
import unicodedata
from io import StringIO

import pandas as pd
import requests


# ============================================================
# CONFIGURAÇÕES
# ============================================================

ARQUIVO_SAIDA = r"C:\Users\User\Downloads\municipios_brasil_cep_referencia.csv"

# Base pública de municípios brasileiros
URL_MUNICIPIOS = (
    "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/"
    "main/csv/municipios.csv"
)

# Base pública de faixas de CEP por município
URL_FAIXAS_CEP = (
    "https://gist.githubusercontent.com/hugosenari/"
    "ec1a7d88f5bdd01844424dbc9aff9590/raw/ceps.csv"
)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def normalizar_texto(valor):
    """
    Normaliza nomes para permitir o cruzamento entre as bases.

    Exemplos:
    'São João d'Aliança' -> 'SAO JOAO D ALIANCA'
    'Santa Bárbara'       -> 'SANTA BARBARA'
    """
    if pd.isna(valor):
        return ""

    valor = str(valor).strip().upper()

    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(
        caractere
        for caractere in valor
        if not unicodedata.combining(caractere)
    )

    valor = re.sub(r"[^A-Z0-9]+", " ", valor)
    valor = re.sub(r"\s+", " ", valor).strip()

    return valor


def padronizar_cep(valor):
    """
    Mantém somente os números do CEP e garante 8 dígitos.
    """
    if pd.isna(valor):
        return pd.NA

    numeros = re.sub(r"\D", "", str(valor))

    if not numeros:
        return pd.NA

    return numeros.zfill(8)


def formatar_cep(valor):
    """
    Converte 74000000 em 74000-000.
    """
    if pd.isna(valor):
        return pd.NA

    valor = str(valor).zfill(8)
    return f"{valor[:5]}-{valor[5:]}"


def baixar_csv(url, nome_base):
    """
    Baixa uma base CSV e retorna um DataFrame.
    """
    print(f"Baixando: {nome_base}")

    resposta = requests.get(url, timeout=60)
    resposta.raise_for_status()

    texto = resposta.content.decode("utf-8-sig", errors="replace")

    try:
        df = pd.read_csv(StringIO(texto))
    except Exception:
        df = pd.read_csv(
            StringIO(texto),
            sep=";",
            engine="python"
        )

    print(f"Registros encontrados em {nome_base}: {len(df):,}")
    return df


# ============================================================
# 1. BAIXAR MUNICÍPIOS
# ============================================================

municipios = baixar_csv(URL_MUNICIPIOS, "Municípios brasileiros")

print("\nColunas da base de municípios:")
print(municipios.columns.tolist())

# Mantém apenas as colunas necessárias.
municipios = municipios[
    ["codigo_ibge", "nome", "codigo_uf"]
].copy()

# A base de municípios possui código UF; vamos buscar a sigla UF
# em outra tabela pública do mesmo repositório.
URL_ESTADOS = (
    "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/"
    "main/csv/estados.csv"
)

estados = baixar_csv(URL_ESTADOS, "Estados brasileiros")

print("\nColunas da base de estados:")
print(estados.columns.tolist())

estados = estados[
    ["codigo_uf", "uf", "nome"]
].copy()

estados = estados.rename(
    columns={
        "nome": "estado"
    }
)

municipios = municipios.merge(
    estados,
    on="codigo_uf",
    how="left"
)

municipios = municipios.rename(
    columns={
        "nome": "municipio"
    }
)

municipios["codigo_ibge"] = municipios["codigo_ibge"].astype("Int64")
municipios["municipio_normalizado"] = municipios["municipio"].apply(
    normalizar_texto
)


# ============================================================
# 2. BAIXAR FAIXAS DE CEP
# ============================================================

faixas_cep = baixar_csv(URL_FAIXAS_CEP, "Faixas de CEP")

print("\nColunas encontradas na base de CEP:")
print(faixas_cep.columns.tolist())

# Ajusta nomes esperados.
faixas_cep.columns = [
    str(coluna).strip().upper()
    for coluna in faixas_cep.columns
]

# A base normalmente possui:
# UF | CIDADE | CEP DE | CEP ATÉ
#
# O bloco abaixo tenta localizar as colunas mesmo se houver
# pequenas variações no nome.

mapa_colunas = {}

for coluna in faixas_cep.columns:
    coluna_limpa = coluna.strip().upper()

    if coluna_limpa == "UF":
        mapa_colunas[coluna] = "uf"

    elif "CIDADE" in coluna_limpa or "MUNICIP" in coluna_limpa:
        mapa_colunas[coluna] = "municipio_cep"

    elif "CEP DE" in coluna_limpa or "CEP_INICIAL" in coluna_limpa:
        mapa_colunas[coluna] = "cep_inicial"

    elif "CEP AT" in coluna_limpa or "CEP_FINAL" in coluna_limpa:
        mapa_colunas[coluna] = "cep_final"

faixas_cep = faixas_cep.rename(columns=mapa_colunas)

colunas_necessarias = [
    "uf",
    "municipio_cep",
    "cep_inicial",
    "cep_final"
]

colunas_ausentes = [
    coluna
    for coluna in colunas_necessarias
    if coluna not in faixas_cep.columns
]

if colunas_ausentes:
    raise ValueError(
        "Não foi possível identificar estas colunas na base de CEP: "
        f"{colunas_ausentes}\n\n"
        f"Colunas disponíveis: {faixas_cep.columns.tolist()}"
    )

faixas_cep = faixas_cep[colunas_necessarias].copy()

# Remove linhas que representam apenas a faixa geral de uma UF,
# sem nome de município.
faixas_cep["municipio_cep"] = faixas_cep["municipio_cep"].fillna("").astype(str)
faixas_cep = faixas_cep[
    faixas_cep["municipio_cep"].str.strip().ne("")
].copy()

faixas_cep["uf"] = faixas_cep["uf"].astype(str).str.strip().str.upper()

faixas_cep["cep_inicial"] = faixas_cep["cep_inicial"].apply(
    padronizar_cep
)

faixas_cep["cep_final"] = faixas_cep["cep_final"].apply(
    padronizar_cep
)

faixas_cep["municipio_normalizado"] = faixas_cep["municipio_cep"].apply(
    normalizar_texto
)


# ============================================================
# 3. CONSOLIDAR UMA LINHA POR MUNICÍPIO
# ============================================================

# Alguns municípios podem possuir mais de uma faixa.
# Para cada município, mantemos:
# - menor CEP inicial;
# - maior CEP final;
# - CEP de referência = menor CEP inicial.

faixas_consolidadas = (
    faixas_cep
    .groupby(
        ["uf", "municipio_normalizado"],
        as_index=False
    )
    .agg(
        cep_inicial=("cep_inicial", "min"),
        cep_final=("cep_final", "max"),
        quantidade_faixas_cep=("cep_inicial", "size")
    )
)

faixas_consolidadas["cep_referencia"] = (
    faixas_consolidadas["cep_inicial"]
)

resultado = municipios.merge(
    faixas_consolidadas,
    on=["uf", "municipio_normalizado"],
    how="left"
)

# Formata CEPs para apresentação.
for coluna in ["cep_referencia", "cep_inicial", "cep_final"]:
    resultado[f"{coluna}_formatado"] = resultado[coluna].apply(
        formatar_cep
    )

resultado["situacao_cep"] = resultado["cep_referencia"].notna().map(
    {
        True: "Encontrado na base de faixas",
        False: "Não encontrado automaticamente"
    }
)

# Seleciona e ordena as colunas finais.
resultado_final = resultado[
    [
        "codigo_ibge",
        "municipio",
        "uf",
        "estado",
        "cep_referencia_formatado",
        "cep_inicial_formatado",
        "cep_final_formatado",
        "quantidade_faixas_cep",
        "situacao_cep"
    ]
].rename(
    columns={
        "cep_referencia_formatado": "cep_referencia",
        "cep_inicial_formatado": "cep_inicial",
        "cep_final_formatado": "cep_final"
    }
)

resultado_final = resultado_final.sort_values(
    ["uf", "municipio"]
).reset_index(drop=True)


# ============================================================
# 4. EXPORTAR CSV
# ============================================================

resultado_final.to_csv(
    ARQUIVO_SAIDA,
    index=False,
    encoding="utf-8-sig",
    sep=";"
)

print("\n" + "=" * 60)
print("ARQUIVO GERADO COM SUCESSO")
print("=" * 60)
print(f"Arquivo: {ARQUIVO_SAIDA}")
print(f"Total de municípios: {len(resultado_final):,}")
print(
    "Municípios com CEP encontrado: "
    f"{resultado_final['cep_referencia'].notna().sum():,}"
)
print(
    "Municípios sem CEP encontrado: "
    f"{resultado_final['cep_referencia'].isna().sum():,}"
)

print("\nExemplo das primeiras linhas:")
print(resultado_final.head(10).to_string(index=False))