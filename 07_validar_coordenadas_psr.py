from pathlib import Path
import re

import pandas as pd


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_RAW = PASTA_PROJETO / "data" / "raw"

PASTA_QUALIDADE = (
    PASTA_PROJETO
    / "data"
    / "qualidade"
    / "coordenadas"
)

PASTA_QUALIDADE.mkdir(parents=True, exist_ok=True)

ANOS_ANALISE = [2020, 2021, 2022, 2023, 2024]

CHUNKSIZE = 100_000

N_AMOSTRAS_POR_ANO = 30


# =============================================================================
# FUNÇÕES
# =============================================================================

def converter_numero_ptbr(serie):
    """
    Converte números em formatos brasileiros ou internacionais.
    """
    serie = serie.astype("string").str.strip()

    serie = serie.mask(
        serie.isin(
            [
                "",
                "-",
                "NAN",
                "NULL",
                "NONE",
                "<NA>",
                "N/A",
                "NA",
            ]
        ),
        pd.NA,
    )

    serie = serie.str.replace(
        r"^\((.*)\)$",
        r"-\1",
        regex=True,
    )

    serie = serie.str.replace(
        r"R\$",
        "",
        regex=True,
    )

    serie = serie.str.replace(
        r"\s+",
        "",
        regex=True,
    )

    serie = serie.str.replace(
        r"[^0-9,.\-]",
        "",
        regex=True,
    )

    tem_virgula = serie.str.contains(
        ",",
        regex=False,
        na=False,
    )

    tem_ponto = serie.str.contains(
        ".",
        regex=False,
        na=False,
    )

    ambos = tem_virgula & tem_ponto

    pos_virgula = serie.str.rfind(",")
    pos_ponto = serie.str.rfind(".")

    formato_br = ambos & (
        pos_virgula > pos_ponto
    )

    formato_int = ambos & (
        pos_ponto > pos_virgula
    )

    serie.loc[formato_br] = (
        serie.loc[formato_br]
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )

    serie.loc[formato_int] = (
        serie.loc[formato_int]
        .str.replace(",", "", regex=False)
    )

    apenas_virgula = tem_virgula & ~tem_ponto

    serie.loc[apenas_virgula] = (
        serie.loc[apenas_virgula]
        .str.replace(",", ".", regex=False)
    )

    apenas_ponto = tem_ponto & ~tem_virgula

    padrao_milhar = r"^-?\d{1,3}(\.\d{3})+$"

    somente_milhar = (
        apenas_ponto
        & serie.str.match(
            padrao_milhar,
            na=False,
        )
    )

    serie.loc[somente_milhar] = (
        serie.loc[somente_milhar]
        .str.replace(".", "", regex=False)
    )

    return pd.to_numeric(
        serie,
        errors="coerce",
    )


def limpar_texto(serie):
    """
    Limpa texto para diagnóstico.
    """
    serie = serie.astype("string")

    return (
        serie
        .str.replace("\ufffd", "", regex=False)
        .str.replace(
            r"[\x00-\x1F\x7F-\x9F]",
            "",
            regex=True,
        )
        .str.strip()
        .str.replace(
            r"\s+",
            " ",
            regex=True,
        )
        .str.upper()
    )


# =============================================================================
# COLUNAS NECESSÁRIAS
# =============================================================================

COLUNAS = [
    "ANO_APOLICE",
    "DT_APOLICE",
    "SG_UF_PROPRIEDADE",
    "CD_GEOCMU",
    "NM_MUNICIPIO_PROPRIEDADE",
    "NM_CULTURA_GLOBAL",
    "NM_RAZAO_SOCIAL",
    "NR_AREA_TOTAL",
    "VL_LIMITE_GARANTIA",
    "VL_PREMIO_LIQUIDO",
    "VALOR_INDENIZAÇÃO",
    "EVENTO_PREPONDERANTE",
    "LATITUDE",
    "LONGITUDE",
    "NR_GRAU_LAT",
    "NR_MIN_LAT",
    "NR_SEG_LAT",
    "NR_GRAU_LONG",
    "NR_MIN_LONG",
    "NR_SEG_LONG",
    "NR_DECIMAL_LATITUDE",
    "NR_DECIMAL_LONGITUDE",
]


# =============================================================================
# LEITURA DOS ARQUIVOS
# =============================================================================

arquivos_csv = sorted(
    PASTA_RAW.glob("*.csv")
)

if not arquivos_csv:
    raise FileNotFoundError(
        f"Nenhum CSV encontrado em: {PASTA_RAW}"
    )

lista_resumos = []
lista_amostras_validas = []
lista_amostras_invalidas = []

for arquivo in arquivos_csv:

    print("\n" + "=" * 90)
    print(f"PROCESSANDO: {arquivo.name}")
    print("=" * 90)

    leitor = pd.read_csv(
        arquivo,
        sep=";",
        encoding="cp1252",
        encoding_errors="replace",
        dtype="string",
        usecols=COLUNAS,
        chunksize=CHUNKSIZE,
        low_memory=False,
        on_bad_lines="warn",
    )

    for numero_chunk, df in enumerate(
        leitor,
        start=1,
    ):

        print(
            f"Bloco {numero_chunk:,} | "
            f"linhas: {len(df):,}"
        )

        df["ano_apolice"] = (
            converter_numero_ptbr(
                df["ANO_APOLICE"]
            )
            .round()
            .astype("Int64")
        )

        df = df[
            df["ano_apolice"].isin(
                ANOS_ANALISE
            )
        ].copy()

        if df.empty:
            continue

        df["uf"] = limpar_texto(
            df["SG_UF_PROPRIEDADE"]
        )

        df["municipio"] = limpar_texto(
            df["NM_MUNICIPIO_PROPRIEDADE"]
        )

        df["cultura"] = limpar_texto(
            df["NM_CULTURA_GLOBAL"]
        )

        df["seguradora"] = limpar_texto(
            df["NM_RAZAO_SOCIAL"]
        )

        df["latitude_decimal"] = (
            converter_numero_ptbr(
                df["NR_DECIMAL_LATITUDE"]
            )
        )

        df["longitude_decimal"] = (
            converter_numero_ptbr(
                df["NR_DECIMAL_LONGITUDE"]
            )
        )

        # Envelope amplo do território brasileiro.
        # É apenas uma validação inicial, não substitui a checagem
        # se o ponto está dentro do município informado.
        df["coord_decimal_preenchida"] = (
            df["latitude_decimal"].notna()
            & df["longitude_decimal"].notna()
        )

        df["coord_decimal_valida_brasil"] = (
            df["coord_decimal_preenchida"]
            & df["latitude_decimal"].between(-35, 6)
            & df["longitude_decimal"].between(-75, -30)
        )

        df["latitude_decimal_positiva"] = (
            df["latitude_decimal"].gt(0)
        )

        df["longitude_decimal_positiva"] = (
            df["longitude_decimal"].gt(0)
        )

        for ano, grupo in df.groupby(
            "ano_apolice",
            dropna=False,
        ):

            lista_resumos.append(
                {
                    "arquivo_origem": arquivo.name,
                    "ano_apolice": ano,
                    "registros_total": len(grupo),
                    "coord_decimal_preenchida": int(
                        grupo[
                            "coord_decimal_preenchida"
                        ].sum()
                    ),
                    "coord_decimal_valida_brasil": int(
                        grupo[
                            "coord_decimal_valida_brasil"
                        ].sum()
                    ),
                    "latitude_decimal_positiva": int(
                        grupo[
                            "latitude_decimal_positiva"
                        ].sum()
                    ),
                    "longitude_decimal_positiva": int(
                        grupo[
                            "longitude_decimal_positiva"
                        ].sum()
                    ),
                    "tem_latitude_texto": int(
                        grupo["LATITUDE"]
                        .notna()
                        .sum()
                    ),
                    "tem_longitude_texto": int(
                        grupo["LONGITUDE"]
                        .notna()
                        .sum()
                    ),
                    "tem_dms_latitude": int(
                        (
                            grupo["NR_GRAU_LAT"].notna()
                            & grupo["NR_MIN_LAT"].notna()
                            & grupo["NR_SEG_LAT"].notna()
                        ).sum()
                    ),
                    "tem_dms_longitude": int(
                        (
                            grupo["NR_GRAU_LONG"].notna()
                            & grupo["NR_MIN_LONG"].notna()
                            & grupo["NR_SEG_LONG"].notna()
                        ).sum()
                    ),
                }
            )

        campos_amostra = [
            "ano_apolice",
            "uf",
            "CD_GEOCMU",
            "municipio",
            "cultura",
            "seguradora",
            "NR_DECIMAL_LATITUDE",
            "NR_DECIMAL_LONGITUDE",
            "latitude_decimal",
            "longitude_decimal",
            "LATITUDE",
            "LONGITUDE",
            "NR_GRAU_LAT",
            "NR_MIN_LAT",
            "NR_SEG_LAT",
            "NR_GRAU_LONG",
            "NR_MIN_LONG",
            "NR_SEG_LONG",
            "NR_AREA_TOTAL",
            "VL_PREMIO_LIQUIDO",
            "VALOR_INDENIZAÇÃO",
            "EVENTO_PREPONDERANTE",
        ]

        amostra_valida = df.loc[
            df["coord_decimal_valida_brasil"],
            campos_amostra,
        ].copy()

        amostra_invalida = df.loc[
            df["coord_decimal_preenchida"]
            & ~df["coord_decimal_valida_brasil"],
            campos_amostra,
        ].copy()

        if not amostra_valida.empty:
            lista_amostras_validas.append(
                amostra_valida.head(20)
            )

        if not amostra_invalida.empty:
            lista_amostras_invalidas.append(
                amostra_invalida.head(20)
            )


# =============================================================================
# CONSOLIDA RESULTADOS
# =============================================================================

df_resumo = pd.DataFrame(
    lista_resumos
)

df_resumo = (
    df_resumo
    .groupby(
        "ano_apolice",
        as_index=False,
    )
    .sum(
        numeric_only=True
    )
    .sort_values("ano_apolice")
)

for coluna in [
    "coord_decimal_preenchida",
    "coord_decimal_valida_brasil",
    "latitude_decimal_positiva",
    "longitude_decimal_positiva",
    "tem_latitude_texto",
    "tem_longitude_texto",
    "tem_dms_latitude",
    "tem_dms_longitude",
]:
    df_resumo[
        f"pct_{coluna}"
    ] = (
        df_resumo[coluna]
        / df_resumo["registros_total"]
        * 100
    ).round(2)

if lista_amostras_validas:
    df_amostras_validas = (
        pd.concat(
            lista_amostras_validas,
            ignore_index=True,
        )
        .drop_duplicates()
        .groupby(
            "ano_apolice",
            group_keys=False,
        )
        .head(N_AMOSTRAS_POR_ANO)
        .reset_index(drop=True)
    )
else:
    df_amostras_validas = pd.DataFrame()

if lista_amostras_invalidas:
    df_amostras_invalidas = (
        pd.concat(
            lista_amostras_invalidas,
            ignore_index=True,
        )
        .drop_duplicates()
        .groupby(
            "ano_apolice",
            group_keys=False,
        )
        .head(N_AMOSTRAS_POR_ANO)
        .reset_index(drop=True)
    )
else:
    df_amostras_invalidas = pd.DataFrame()


# =============================================================================
# SALVA RESULTADOS
# =============================================================================

CAMINHO_RESUMO = (
    PASTA_QUALIDADE
    / "psr_resumo_coordenadas_2020_2024.csv"
)

CAMINHO_AMOSTRA_VALIDA = (
    PASTA_QUALIDADE
    / "psr_amostra_coordenadas_validas.csv"
)

CAMINHO_AMOSTRA_INVALIDA = (
    PASTA_QUALIDADE
    / "psr_amostra_coordenadas_invalidas.csv"
)

df_resumo.to_csv(
    CAMINHO_RESUMO,
    index=False,
    encoding="utf-8-sig",
)

df_amostras_validas.to_csv(
    CAMINHO_AMOSTRA_VALIDA,
    index=False,
    encoding="utf-8-sig",
)

df_amostras_invalidas.to_csv(
    CAMINHO_AMOSTRA_INVALIDA,
    index=False,
    encoding="utf-8-sig",
)


# =============================================================================
# RESULTADO
# =============================================================================

print("\n" + "=" * 90)
print("VALIDAÇÃO PRELIMINAR DE COORDENADAS FINALIZADA")
print("=" * 90)

print("\nResumo por ano:")
print(
    df_resumo.to_string(
        index=False
    )
)

print("\nArquivos gerados:")
print(f"- {CAMINHO_RESUMO}")
print(f"- {CAMINHO_AMOSTRA_VALIDA}")
print(f"- {CAMINHO_AMOSTRA_INVALIDA}")