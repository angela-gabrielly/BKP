from pathlib import Path
import re
import shutil
import warnings

import pandas as pd


# ============================================================
# CONFIGURAÇÃO
# ============================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_RAW = PASTA_PROJETO / "data" / "raw"
PASTA_PROCESSED = PASTA_PROJETO / "data" / "processed"
PASTA_QUALIDADE = PASTA_PROJETO / "data" / "qualidade"

PASTA_PARTES = PASTA_PROCESSED / "psr_base_analitica_partes"

PASTA_PROCESSED.mkdir(parents=True, exist_ok=True)
PASTA_QUALIDADE.mkdir(parents=True, exist_ok=True)

# Quantidade de linhas lidas por vez.
# Caso seu computador tenha pouca memória, reduza para 50_000.
CHUNKSIZE = 100_000

# Se True, remove as partes parquet geradas anteriormente
# antes de uma nova execução, evitando duplicação de registros.
LIMPAR_SAIDAS_ANTERIORES = True

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 250)

warnings.filterwarnings("ignore", category=FutureWarning)


# ============================================================
# ARQUIVOS E CONFIGURAÇÕES DOS CSVs
# ============================================================

ARQUIVOS_CSV = sorted(PASTA_RAW.glob("*.csv"))

if not ARQUIVOS_CSV:
    raise FileNotFoundError(
        f"Nenhum arquivo CSV foi encontrado em: {PASTA_RAW}"
    )

COLUNAS_LEITURA = [
    "NM_RAZAO_SOCIAL",
    "CD_PROCESSO_SUSEP",
    "NR_PROPOSTA",
    "ID_PROPOSTA",
    "DT_PROPOSTA",
    "DT_INICIO_VIGENCIA",
    "DT_FIM_VIGENCIA",
    "NM_MUNICIPIO_PROPRIEDADE",
    "SG_UF_PROPRIEDADE",
    "NM_CLASSIF_PRODUTO",
    "NM_CULTURA_GLOBAL",
    "NR_AREA_TOTAL",
    "NR_ANIMAL",
    "NR_PRODUTIVIDADE_ESTIMADA",
    "NR_PRODUTIVIDADE_SEGURADA",
    "NivelDeCobertura",
    "VL_LIMITE_GARANTIA",
    "VL_PREMIO_LIQUIDO",
    "PE_TAXA",
    "VL_SUBVENCAO_FEDERAL",
    "NR_APOLICE",
    "DT_APOLICE",
    "ANO_APOLICE",
    "CD_GEOCMU",
    "VALOR_INDENIZAÇÃO",
    "EVENTO_PREPONDERANTE",
]

MAPA_COLUNAS = {
    "NM_RAZAO_SOCIAL": "seguradora",
    "CD_PROCESSO_SUSEP": "processo_susep",
    "NR_PROPOSTA": "numero_proposta",
    "ID_PROPOSTA": "id_proposta",
    "DT_PROPOSTA": "data_proposta",
    "DT_INICIO_VIGENCIA": "data_inicio_vigencia",
    "DT_FIM_VIGENCIA": "data_fim_vigencia",
    "NM_MUNICIPIO_PROPRIEDADE": "municipio",
    "SG_UF_PROPRIEDADE": "uf",
    "NM_CLASSIF_PRODUTO": "classificacao_produto",
    "NM_CULTURA_GLOBAL": "cultura",
    "NR_AREA_TOTAL": "area_total",
    "NR_ANIMAL": "quantidade_animais",
    "NR_PRODUTIVIDADE_ESTIMADA": "produtividade_estimada",
    "NR_PRODUTIVIDADE_SEGURADA": "produtividade_segurada",
    "NivelDeCobertura": "nivel_cobertura",
    "VL_LIMITE_GARANTIA": "limite_garantia",
    "VL_PREMIO_LIQUIDO": "premio_liquido",
    "PE_TAXA": "taxa",
    "VL_SUBVENCAO_FEDERAL": "subvencao_federal",
    "NR_APOLICE": "numero_apolice",
    "DT_APOLICE": "data_apolice",
    "ANO_APOLICE": "ano_apolice",
    "CD_GEOCMU": "codigo_municipio",
    "VALOR_INDENIZAÇÃO": "valor_indenizacao",
    "EVENTO_PREPONDERANTE": "evento_preponderante",
}

COLUNAS_TEXTO = [
    "seguradora",
    "processo_susep",
    "numero_proposta",
    "id_proposta",
    "municipio",
    "uf",
    "classificacao_produto",
    "cultura",
    "numero_apolice",
    "codigo_municipio",
    "evento_preponderante",
]

COLUNAS_NUMERICAS = [
    "area_total",
    "quantidade_animais",
    "produtividade_estimada",
    "produtividade_segurada",
    "nivel_cobertura",
    "limite_garantia",
    "premio_liquido",
    "taxa",
    "subvencao_federal",
    "valor_indenizacao",
]

COLUNAS_DATAS = [
    "data_proposta",
    "data_inicio_vigencia",
    "data_fim_vigencia",
    "data_apolice",
]


# ============================================================
# FUNÇÕES DE PADRONIZAÇÃO
# ============================================================

def limpar_texto(serie):
    """
    Remove espaços excedentes, padroniza valores vazios e converte
    categorias para letras maiúsculas, preservando acentos.
    """
    serie = serie.astype("string")

    serie = (
        serie
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

    valores_nulos = {
        "",
        "-",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "N/A",
        "NA",
    }

    serie = serie.mask(
        serie.str.upper().isin(valores_nulos),
        pd.NA
    )

    return serie.str.upper()


def converter_numero_ptbr(serie):
    """
    Converte números armazenados em formato brasileiro ou internacional.

    Exemplos tratados:
    1.234,56  -> 1234.56
    1234,56   -> 1234.56
    1,234.56  -> 1234.56
    1234.56   -> 1234.56
    """
    serie = serie.astype("string").str.strip()

    serie = serie.mask(
        serie.isin(["", "-", "NAN", "NULL", "NONE", "<NA>"]),
        pd.NA
    )

    # Trata valores negativos escritos entre parênteses.
    serie = serie.str.replace(
        r"^\((.*)\)$",
        r"-\1",
        regex=True
    )

    # Remove R$, espaços e caracteres estranhos.
    serie = serie.str.replace(r"R\$", "", regex=True)
    serie = serie.str.replace(r"\s+", "", regex=True)
    serie = serie.str.replace(r"[^0-9,.\-]", "", regex=True)

    tem_virgula = serie.str.contains(",", regex=False, na=False)
    tem_ponto = serie.str.contains(".", regex=False, na=False)

    # Valores com ponto e vírgula:
    # identifica qual separador aparece por último.
    ambos = tem_virgula & tem_ponto

    pos_ultima_virgula = serie.str.rfind(",")
    pos_ultimo_ponto = serie.str.rfind(".")

    formato_brasileiro = ambos & (
        pos_ultima_virgula > pos_ultimo_ponto
    )

    formato_internacional = ambos & (
        pos_ultimo_ponto > pos_ultima_virgula
    )

    # Exemplo: 1.234,56
    serie.loc[formato_brasileiro] = (
        serie.loc[formato_brasileiro]
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )

    # Exemplo: 1,234.56
    serie.loc[formato_internacional] = (
        serie.loc[formato_internacional]
        .str.replace(",", "", regex=False)
    )

    # Apenas vírgula: considera vírgula como separador decimal.
    apenas_virgula = tem_virgula & ~tem_ponto

    serie.loc[apenas_virgula] = (
        serie.loc[apenas_virgula]
        .str.replace(",", ".", regex=False)
    )

    # Apenas ponto: identifica casos claramente com milhar.
    apenas_ponto = tem_ponto & ~tem_virgula

    padrao_milhar = (
        r"^-?\d{1,3}(\.\d{3})+$"
    )

    somente_milhar = (
        apenas_ponto
        & serie.str.match(padrao_milhar, na=False)
    )

    serie.loc[somente_milhar] = (
        serie.loc[somente_milhar]
        .str.replace(".", "", regex=False)
    )

    return pd.to_numeric(
        serie,
        errors="coerce"
    )


def converter_data_br(serie):
    """
    Converte datas prioritariamente no formato brasileiro DD/MM/AAAA,
    com tentativas adicionais para formatos alternativos.
    """
    serie_original = serie.astype("string").str.strip()

    resultado = pd.to_datetime(
        serie_original,
        format="%d/%m/%Y",
        errors="coerce"
    )

    formatos_adicionais = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for formato in formatos_adicionais:
        pendentes = resultado.isna() & serie_original.notna()

        if pendentes.any():
            resultado.loc[pendentes] = pd.to_datetime(
                serie_original.loc[pendentes],
                format=formato,
                errors="coerce"
            )

    return resultado


def normalizar_codigo_municipio(serie):
    """
    Preserva somente dígitos do código municipal.

    Não força automaticamente sete dígitos, pois a validação do código
    será feita depois contra uma base oficial de municípios do IBGE.
    """
    serie = serie.astype("string").str.strip()

    serie = (
        serie
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
    )

    serie = serie.mask(
        serie.isin(["", "0", "0000000"]),
        pd.NA
    )

    return serie


def criar_identificador_anonimo(df):
    """
    Cria uma chave anônima para contagem de apólices sem manter o número
    original da apólice, proposta ou identificador interno.

    Ordem de preferência:
    1. Número da apólice
    2. ID da proposta
    3. Número da proposta
    4. Identificador de linha de origem
    """
    identificador_base = (
        df["numero_apolice"]
        .fillna(df["id_proposta"])
        .fillna(df["numero_proposta"])
    )

    identificador_base = identificador_base.fillna(
        df["arquivo_origem"].astype("string")
        + "_"
        + df["linha_origem"].astype("string")
    )

    chave = (
        df["seguradora"].fillna("SEM_SEGURADORA")
        + "|"
        + identificador_base.astype("string")
        + "|"
        + df["ano_apolice"].astype("string")
    )

    # Hash vetorizado; evita salvar o identificador original.
    hash_serie = pd.util.hash_pandas_object(
        chave,
        index=False
    )

    return hash_serie.astype("uint64").astype("string")


def extrair_periodo_arquivo(nome_arquivo):
    """
    Extrai período de referência a partir do nome do arquivo.
    """
    anos = re.findall(r"\d{4}", nome_arquivo)

    if len(anos) >= 2:
        return f"{anos[0]}_{anos[1]}"

    if len(anos) == 1:
        return anos[0]

    return "nao_identificado"


# ============================================================
# PREPARA A PASTA DE SAÍDA
# ============================================================

if LIMPAR_SAIDAS_ANTERIORES and PASTA_PARTES.exists():
    print(
        "Removendo partes parquet anteriores para evitar duplicação..."
    )
    shutil.rmtree(PASTA_PARTES)

PASTA_PARTES.mkdir(parents=True, exist_ok=True)


# ============================================================
# PROCESSAMENTO EM BLOCOS
# ============================================================

lista_resumos_chunks = []
lista_qualidade_chunks = []
contador_partes = 0

print("\nArquivos que serão processados:")

for arquivo in ARQUIVOS_CSV:
    tamanho_mb = arquivo.stat().st_size / (1024 ** 2)
    print(f"- {arquivo.name} | {tamanho_mb:,.2f} MB")

for arquivo in ARQUIVOS_CSV:

    print("\n" + "=" * 100)
    print(f"PROCESSANDO: {arquivo.name}")
    print("=" * 100)

    periodo_origem = extrair_periodo_arquivo(
        arquivo.name
    )

    leitor = pd.read_csv(
    arquivo,
    sep=";",
    encoding="cp1252",
    encoding_errors="replace",
    dtype="string",
    usecols=COLUNAS_LEITURA,
    chunksize=CHUNKSIZE,
    low_memory=False,
    on_bad_lines="warn",
)

    linha_inicial = 1

    for numero_chunk, df in enumerate(leitor, start=1):

        quantidade_linhas_chunk = len(df)

        print(
            f"Arquivo: {arquivo.name} | "
            f"Bloco {numero_chunk:,} | "
            f"Linhas: {quantidade_linhas_chunk:,}"
        )

        # ----------------------------------------------------
        # Rastreabilidade de origem
        # ----------------------------------------------------

        df.insert(
            0,
            "arquivo_origem",
            arquivo.name
        )

        df.insert(
            1,
            "periodo_origem",
            periodo_origem
        )

        df.insert(
            2,
            "linha_origem",
            range(
                linha_inicial,
                linha_inicial + quantidade_linhas_chunk
            )
        )

        linha_inicial += quantidade_linhas_chunk

        # ----------------------------------------------------
        # Renomeia colunas
        # ----------------------------------------------------

        df = df.rename(columns=MAPA_COLUNAS)

        # ----------------------------------------------------
        # Padroniza campos textuais
        # ----------------------------------------------------

        for coluna in COLUNAS_TEXTO:
            df[coluna] = limpar_texto(df[coluna])

        # UF precisa ficar sempre com duas letras.
        df["uf"] = df["uf"].str.extract(
            r"([A-Z]{2})",
            expand=False
        )

        # Código do município é preservado como texto.
        df["codigo_municipio"] = normalizar_codigo_municipio(
            df["codigo_municipio"]
        )

        # ----------------------------------------------------
        # Padroniza números
        # ----------------------------------------------------

        for coluna in COLUNAS_NUMERICAS:
            df[coluna] = converter_numero_ptbr(
                df[coluna]
            )

        # Ano da apólice: campo original + complemento pela data.
        df["ano_apolice"] = converter_numero_ptbr(
            df["ano_apolice"]
        )

        df["ano_apolice"] = (
            df["ano_apolice"]
            .round()
            .astype("Int64")
        )

        # ----------------------------------------------------
        # Padroniza datas
        # ----------------------------------------------------

        for coluna in COLUNAS_DATAS:
            df[coluna] = converter_data_br(
                df[coluna]
            )

        # Preenche ano com a data da apólice quando ANO_APOLICE estiver vazio.
        ano_extraido_data = (
            df["data_apolice"]
            .dt.year
            .astype("Int64")
        )

        df["ano_apolice"] = df["ano_apolice"].fillna(
            ano_extraido_data
        )

        # Marca anos improváveis, sem excluir registros.
        df["flag_ano_invalido"] = (
            df["ano_apolice"].notna()
            & ~df["ano_apolice"].between(2000, 2030)
        )

        # ----------------------------------------------------
        # Cria identificador anonimizado e indicadores simples
        # ----------------------------------------------------

        df["id_apolice_anon"] = criar_identificador_anonimo(df)

        df["tem_indenizacao"] = (
            df["valor_indenizacao"]
            .fillna(0)
            .gt(0)
        )

        df["tem_subvencao"] = (
            df["subvencao_federal"]
            .fillna(0)
            .gt(0)
        )

        # ----------------------------------------------------
        # Flags de qualidade
        # ----------------------------------------------------

        df["flag_municipio_ausente"] = (
            df["municipio"].isna()
            & df["codigo_municipio"].isna()
        )

        df["flag_cultura_ausente"] = (
            df["cultura"].isna()
        )

        df["flag_seguradora_ausente"] = (
            df["seguradora"].isna()
        )

        df["flag_area_negativa"] = (
            df["area_total"].notna()
            & df["area_total"].lt(0)
        )

        df["flag_premio_negativo"] = (
            df["premio_liquido"].notna()
            & df["premio_liquido"].lt(0)
        )

        df["flag_indenizacao_negativa"] = (
            df["valor_indenizacao"].notna()
            & df["valor_indenizacao"].lt(0)
        )

        # ----------------------------------------------------
        # Remove identificadores sensíveis/originais
        # ----------------------------------------------------

        colunas_remover = [
            "numero_apolice",
            "id_proposta",
            "numero_proposta",
        ]

        df = df.drop(
            columns=colunas_remover,
            errors="ignore"
        )

        # ----------------------------------------------------
        # Resumo anual preliminar
        # ----------------------------------------------------

        resumo_chunk = (
            df.groupby(
                ["ano_apolice", "uf"],
                dropna=False
            )
            .agg(
                registros_psr=(
                    "id_apolice_anon",
                    "size"
                ),
                area_total=(
                    "area_total",
                    "sum"
                ),
                limite_garantia=(
                    "limite_garantia",
                    "sum"
                ),
                premio_liquido=(
                    "premio_liquido",
                    "sum"
                ),
                subvencao_federal=(
                    "subvencao_federal",
                    "sum"
                ),
                valor_indenizacao=(
                    "valor_indenizacao",
                    "sum"
                ),
                registros_com_indenizacao=(
                    "tem_indenizacao",
                    "sum"
                ),
                registros_com_subvencao=(
                    "tem_subvencao",
                    "sum"
                ),
            )
            .reset_index()
        )

        lista_resumos_chunks.append(
            resumo_chunk
        )

        # ----------------------------------------------------
        # Qualidade por bloco
        # ----------------------------------------------------

        lista_qualidade_chunks.append(
            {
                "arquivo_origem": arquivo.name,
                "periodo_origem": periodo_origem,
                "numero_chunk": numero_chunk,
                "registros": len(df),
                "ano_ausente": int(
                    df["ano_apolice"].isna().sum()
                ),
                "ano_invalido": int(
                    df["flag_ano_invalido"].sum()
                ),
                "municipio_ausente": int(
                    df["flag_municipio_ausente"].sum()
                ),
                "cultura_ausente": int(
                    df["flag_cultura_ausente"].sum()
                ),
                "seguradora_ausente": int(
                    df["flag_seguradora_ausente"].sum()
                ),
                "area_negativa": int(
                    df["flag_area_negativa"].sum()
                ),
                "premio_negativo": int(
                    df["flag_premio_negativo"].sum()
                ),
                "indenizacao_negativa": int(
                    df["flag_indenizacao_negativa"].sum()
                ),
            }
        )

        # ----------------------------------------------------
        # Salva o bloco em parquet
        # ----------------------------------------------------

        contador_partes += 1

        caminho_parquet = (
            PASTA_PARTES
            / f"part_{contador_partes:05d}.parquet"
        )

        df.to_parquet(
            caminho_parquet,
            index=False,
            engine="pyarrow",
            compression="snappy"
        )


# ============================================================
# CONSOLIDA RESUMOS E AUDITORIAS
# ============================================================

df_resumo_anual = (
    pd.concat(
        lista_resumos_chunks,
        ignore_index=True
    )
    .groupby(
        ["ano_apolice", "uf"],
        dropna=False,
        as_index=False
    )
    .sum(numeric_only=True)
    .sort_values(
        ["ano_apolice", "uf"]
    )
    .reset_index(drop=True)
)

df_resumo_anual["percentual_registros_indenizados"] = (
    df_resumo_anual["registros_com_indenizacao"]
    / df_resumo_anual["registros_psr"]
    * 100
)

df_resumo_anual["premio_medio_por_registro"] = (
    df_resumo_anual["premio_liquido"]
    / df_resumo_anual["registros_psr"]
)

df_resumo_anual["limite_garantia_medio_por_registro"] = (
    df_resumo_anual["limite_garantia"]
    / df_resumo_anual["registros_psr"]
)

df_qualidade = (
    pd.DataFrame(lista_qualidade_chunks)
    .groupby(
        ["arquivo_origem", "periodo_origem"],
        as_index=False
    )
    .sum(numeric_only=True)
)

df_qualidade["percentual_ano_ausente"] = (
    df_qualidade["ano_ausente"]
    / df_qualidade["registros"]
    * 100
)

df_qualidade["percentual_municipio_ausente"] = (
    df_qualidade["municipio_ausente"]
    / df_qualidade["registros"]
    * 100
)

df_qualidade["percentual_cultura_ausente"] = (
    df_qualidade["cultura_ausente"]
    / df_qualidade["registros"]
    * 100
)

df_qualidade["percentual_seguradora_ausente"] = (
    df_qualidade["seguradora_ausente"]
    / df_qualidade["registros"]
    * 100
)


# ============================================================
# DICIONÁRIO DA BASE ANALÍTICA
# ============================================================

dicionario_base = pd.DataFrame(
    [
        ["arquivo_origem", "Arquivo CSV de origem do registro."],
        ["periodo_origem", "Período identificado a partir do nome do arquivo original."],
        ["linha_origem", "Número sequencial da linha dentro do arquivo de origem."],
        ["seguradora", "Razão social da seguradora, padronizada em maiúsculas."],
        ["processo_susep", "Código de processo SUSEP informado na base."],
        ["data_proposta", "Data da proposta."],
        ["data_inicio_vigencia", "Data de início de vigência."],
        ["data_fim_vigencia", "Data de término de vigência."],
        ["municipio", "Município da propriedade."],
        ["uf", "Unidade da Federação da propriedade."],
        ["codigo_municipio", "Código municipal informado na base, preservado como texto."],
        ["classificacao_produto", "Classificação de produto do SISSER."],
        ["cultura", "Cultura global informada no SISSER."],
        ["area_total", "Campo NR_AREA_TOTAL do arquivo de origem; definição deverá ser validada no dicionário SISSER."],
        ["quantidade_animais", "Campo NR_ANIMAL do arquivo de origem."],
        ["produtividade_estimada", "Produtividade estimada informada na apólice."],
        ["produtividade_segurada", "Produtividade segurada informada na apólice."],
        ["nivel_cobertura", "Nível de cobertura informado."],
        ["limite_garantia", "Campo VL_LIMITE_GARANTIA do arquivo de origem."],
        ["premio_liquido", "Campo VL_PREMIO_LIQUIDO do arquivo de origem."],
        ["taxa", "Campo PE_TAXA do arquivo de origem."],
        ["subvencao_federal", "Campo VL_SUBVENCAO_FEDERAL do arquivo de origem."],
        ["data_apolice", "Data da apólice."],
        ["ano_apolice", "Ano da apólice, preenchido pela data quando ausente."],
        ["valor_indenizacao", "Valor da indenização informado."],
        ["evento_preponderante", "Evento preponderante informado."],
        ["id_apolice_anon", "Identificador anonimizado para contagem de apólices sem expor números originais."],
        ["tem_indenizacao", "Indicador: valor de indenização maior que zero."],
        ["tem_subvencao", "Indicador: subvenção federal maior que zero."],
        ["flag_ano_invalido", "Ano fora do intervalo de 2000 a 2030."],
        ["flag_municipio_ausente", "Município e código municipal ausentes simultaneamente."],
        ["flag_cultura_ausente", "Cultura ausente."],
        ["flag_seguradora_ausente", "Seguradora ausente."],
        ["flag_area_negativa", "Área total menor que zero."],
        ["flag_premio_negativo", "Prêmio líquido menor que zero."],
        ["flag_indenizacao_negativa", "Valor de indenização menor que zero."],
    ],
    columns=["coluna", "descricao"]
)


# ============================================================
# SALVA RESULTADOS
# ============================================================

CAMINHO_RESUMO_ANUAL = (
    PASTA_PROCESSED
    / "psr_resumo_anual_uf_preliminar.csv"
)

CAMINHO_QUALIDADE = (
    PASTA_QUALIDADE
    / "psr_qualidade_consolidacao.csv"
)

CAMINHO_DICIONARIO = (
    PASTA_PROCESSED
    / "psr_dicionario_base_analitica.csv"
)

df_resumo_anual.to_csv(
    CAMINHO_RESUMO_ANUAL,
    index=False,
    encoding="utf-8-sig"
)

df_qualidade.to_csv(
    CAMINHO_QUALIDADE,
    index=False,
    encoding="utf-8-sig"
)

dicionario_base.to_csv(
    CAMINHO_DICIONARIO,
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# RESUMO FINAL
# ============================================================

print("\n" + "=" * 100)
print("CONSOLIDAÇÃO FINALIZADA")
print("=" * 100)

print(f"\nQuantidade de partes parquet geradas: {contador_partes:,}")
print(f"Pasta da base analítica: {PASTA_PARTES}")

print("\nResumo de qualidade por arquivo:")
print(
    df_qualidade.to_string(
        index=False
    )
)

print("\nResumo anual preliminar — primeiras linhas:")
print(
    df_resumo_anual.head(20).to_string(
        index=False
    )
)

print("\nArquivos gerados:")
print(f"- {CAMINHO_RESUMO_ANUAL}")
print(f"- {CAMINHO_QUALIDADE}")
print(f"- {CAMINHO_DICIONARIO}")
print(f"- {PASTA_PARTES}")