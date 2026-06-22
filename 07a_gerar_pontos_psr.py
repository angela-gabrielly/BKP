# -*- coding: utf-8 -*-
"""
07a_gerar_pontos_psr.py

Gera pontos georreferenciados do PSR para 2020 a 2024.

Saídas:
- data/interim/pontos_psr_partes/*.parquet
- data/vetores/psr_pontos_2020_2024.gpkg
- data/qualidade/pontos_psr/psr_auditoria_pontos_2020_2024.csv

IMPORTANTE:
Os pontos representam coordenadas informadas na base PSR.
Eles NÃO representam o polígono ou limite real da propriedade.
"""

from pathlib import Path
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_RAW = PASTA_PROJETO / "data" / "raw"

PASTA_PARTES_PONTOS = (
    PASTA_PROJETO / "data" / "interim" / "pontos_psr_partes"
)

PASTA_QUALIDADE = (
    PASTA_PROJETO / "data" / "qualidade" / "pontos_psr"
)

PASTA_VETORES = PASTA_PROJETO / "data" / "vetores"

# AJUSTE PARA O CAMINHO DA SUA MALHA MUNICIPAL IBGE.
# Pode ser .shp, .gpkg ou outro formato lido pelo GeoPandas.
CAMINHO_MALHA_MUNICIPAL = Path(
    r"D:\AZ\PSR\data\referencias\BR_Municipios_2025.gpkg"
)

# Se a malha for GeoPackage com mais de uma camada, informe aqui.
# Para SHP ou GPKG com uma camada apenas, mantenha None.
CAMADA_MALHA_MUNICIPAL = None

ANOS_ANALISE = [2020, 2021, 2022, 2023, 2024]
CHUNKSIZE = 100_000
LIMPAR_SAIDAS_ANTERIORES = True

ARQUIVO_GPKG_PONTOS = (
    PASTA_VETORES / "psr_pontos_2020_2024.gpkg"
)

ARQUIVO_AUDITORIA = (
    PASTA_QUALIDADE / "psr_auditoria_pontos_2020_2024.csv"
)

ARQUIVO_REJEITADOS = (
    PASTA_QUALIDADE / "psr_amostra_pontos_rejeitados.csv"
)

for pasta in [PASTA_PARTES_PONTOS, PASTA_QUALIDADE, PASTA_VETORES]:
    pasta.mkdir(parents=True, exist_ok=True)


# =============================================================================
# FUNÇÕES
# =============================================================================

def normalizar_codigo_municipio(serie: pd.Series) -> pd.Series:
    """Mantém somente dígitos e padroniza códigos IBGE com 7 posições."""
    serie = serie.astype("string")
    serie = (
        serie.str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.strip()
    )
    serie = serie.mask(serie.isin(["", "0", "0000000"]), pd.NA)
    return serie.str.zfill(7)


def limpar_texto(serie: pd.Series) -> pd.Series:
    """Padroniza campos textuais sem alterar a estrutura original do dado."""
    serie = serie.astype("string")
    serie = (
        serie.str.replace("\ufffd", "", regex=False)
        .str.replace("\xa0", " ", regex=False)
        .str.replace(r"[\x00-\x1F\x7F-\x9F]", "", regex=True)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.upper()
    )
    nulos = ["", "-", "NAN", "NONE", "NULL", "<NA>", "N/A", "NA"]
    return serie.mask(serie.isin(nulos), pd.NA)


def converter_numero_ptbr(serie: pd.Series) -> pd.Series:
    """
    Converte textos numéricos brasileiros ou internacionais em float.
    Exemplos:
        1.234,56 -> 1234.56
        1234,56  -> 1234.56
        1,234.56 -> 1234.56
    """
    serie = serie.astype("string").str.strip()
    serie = serie.mask(
        serie.isin(["", "-", "NAN", "NULL", "NONE", "<NA>", "N/A", "NA"]),
        pd.NA,
    )

    serie = serie.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    serie = serie.str.replace(r"R\$", "", regex=True)
    serie = serie.str.replace(r"\s+", "", regex=True)
    serie = serie.str.replace(r"[^0-9,.\-]", "", regex=True)

    tem_virgula = serie.str.contains(",", regex=False, na=False)
    tem_ponto = serie.str.contains(".", regex=False, na=False)
    ambos = tem_virgula & tem_ponto

    pos_virgula = serie.str.rfind(",")
    pos_ponto = serie.str.rfind(".")

    formato_br = ambos & (pos_virgula > pos_ponto)
    formato_int = ambos & (pos_ponto > pos_virgula)

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
        serie.loc[apenas_virgula].str.replace(",", ".", regex=False)
    )

    apenas_ponto = tem_ponto & ~tem_virgula
    padrao_milhar = r"^-?\d{1,3}(\.\d{3})+$"
    somente_milhar = apenas_ponto & serie.str.match(padrao_milhar, na=False)

    serie.loc[somente_milhar] = (
        serie.loc[somente_milhar].str.replace(".", "", regex=False)
    )

    return pd.to_numeric(serie, errors="coerce")


def dms_para_decimal(
    graus: pd.Series,
    minutos: pd.Series,
    segundos: pd.Series,
    eixo: str,
) -> pd.Series:
    """
    Converte coordenadas em graus/minutos/segundos para decimal.

    Para longitude, adota sinal negativo porque o Brasil está a oeste.
    Para latitude, preserva o sinal informado; se valor positivo for > 6,
    assume hemisfério sul, pois esse valor não é compatível com o Brasil.
    """

    graus_num = converter_numero_ptbr(graus)
    minutos_num = converter_numero_ptbr(minutos)
    segundos_num = converter_numero_ptbr(segundos)

    componentes_validos = (
        graus_num.notna()
        & minutos_num.notna()
        & segundos_num.notna()
        & minutos_num.between(0, 59.999999)
        & segundos_num.between(0, 59.999999)
    )

    magnitude = (
        graus_num.abs()
        + minutos_num / 60
        + segundos_num / 3600
    )

    # Inicia vazio e preenche somente coordenadas DMS válidas.
    coordenada = pd.Series(
        np.nan,
        index=graus.index,
        dtype="float64"
    )

    # O fillna(False) evita erro quando houver pd.NA.
    mascara_negativa = (
        componentes_validos
        & graus_num.lt(0).fillna(False)
    )

    mascara_positiva = (
        componentes_validos
        & graus_num.ge(0).fillna(False)
    )

    coordenada.loc[mascara_negativa] = (
        -magnitude.loc[mascara_negativa]
    )

    coordenada.loc[mascara_positiva] = (
        magnitude.loc[mascara_positiva]
    )

    if eixo == "lon":
        # Brasil está integralmente a oeste de Greenwich.
        coordenada = -coordenada.abs()

    elif eixo == "lat":
        # Coordenada positiva acima de 6° não pertence ao território brasileiro.
        mascara_latitude_sul = coordenada.gt(6).fillna(False)

        coordenada.loc[mascara_latitude_sul] = (
            -coordenada.loc[mascara_latitude_sul].abs()
        )

    else:
        raise ValueError(
            "O parâmetro eixo deve ser 'lat' ou 'lon'."
        )

    return coordenada


def localizar_coluna(df: gpd.GeoDataFrame, candidatos: list[str]) -> str:
    """Localiza campo ignorando maiúsculas/minúsculas."""
    mapa = {str(c).strip().upper(): c for c in df.columns}

    for candidato in candidatos:
        if candidato.upper() in mapa:
            return mapa[candidato.upper()]

    raise KeyError(
        "Não foi possível localizar código municipal na malha. "
        f"Campos testados: {candidatos}"
    )


def salvar_camada_gpkg(
    gdf: gpd.GeoDataFrame,
    caminho_gpkg: Path,
    camada: str,
) -> None:
    """Salva camada no GeoPackage."""
    if gdf.empty:
        print(f"Camada vazia ignorada: {camada}")
        return

    kwargs = {
        "filename": caminho_gpkg,
        "layer": camada,
        "driver": "GPKG",
        "engine": "pyogrio",
        "index": False,
        "SPATIAL_INDEX": "YES",
    }

    if caminho_gpkg.exists():
        kwargs["mode"] = "a"

    gdf.to_file(**kwargs)
    print(f"Camada salva: {camada} | {len(gdf):,} feições")


def carregar_pontos(periodo: int | None = None) -> gpd.GeoDataFrame:
    """Carrega GeoParquets intermediários, opcionalmente filtrados por ano."""
    partes = []

    for arquivo in sorted(PASTA_PARTES_PONTOS.glob("*.parquet")):
        gdf = gpd.read_parquet(arquivo)

        if periodo is not None:
            gdf = gdf[gdf["ano_apolice"].eq(periodo)].copy()

        if not gdf.empty:
            partes.append(gdf)

    if not partes:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame(
        pd.concat(partes, ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326",
    )


def lider_por_premio(
    gdf: gpd.GeoDataFrame,
    chave: str,
    categoria: str,
    nome_saida: str,
) -> pd.DataFrame:
    """Define categoria líder com base no prêmio líquido agregado."""
    ranking = (
        gdf.groupby([chave, categoria], dropna=False, as_index=False)["premio_liq_rs"]
        .sum()
        .sort_values([chave, "premio_liq_rs", categoria], ascending=[True, False, True])
    )

    return (
        ranking.drop_duplicates(subset=[chave], keep="first")[[chave, categoria]]
        .rename(columns={categoria: nome_saida})
    )


def agregar_localizacoes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Agrega registros coincidentes na mesma coordenada."""
    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    agregado = (
        gdf.groupby("coord_chave", as_index=False)
        .agg(
            longitude=("longitude", "mean"),
            latitude=("latitude", "mean"),
            ano_inicio=("ano_apolice", "min"),
            ano_fim=("ano_apolice", "max"),
            n_registros=("coord_chave", "size"),
            n_anos=("ano_apolice", "nunique"),
            n_seguradoras=("seguradora", "nunique"),
            n_culturas=("cultura", "nunique"),
            area_total_ha=("area_total_ha", "sum"),
            limite_garantia_rs=("limite_garantia_rs", "sum"),
            premio_liq_rs=("premio_liq_rs", "sum"),
            subvencao_rs=("subvencao_rs", "sum"),
            indenizacao_rs=("indenizacao_rs", "sum"),
            n_registros_indenizados=("tem_indenizacao", "sum"),
        )
    )

    cultura_lider = lider_por_premio(
        gdf, "coord_chave", "cultura", "cultura_lider"
    )
    seguradora_lider = lider_por_premio(
        gdf, "coord_chave", "seguradora", "seguradora_lider"
    )

    eventos = gdf[
        gdf["tem_indenizacao"].eq(1)
        & gdf["evento_preponderante"].notna()
    ].copy()

    if eventos.empty:
        evento_lider = pd.DataFrame(columns=["coord_chave", "evento_lider"])
    else:
        ranking_evento = (
            eventos.groupby(
                ["coord_chave", "evento_preponderante"],
                dropna=False,
                as_index=False,
            )["indenizacao_rs"]
            .sum()
            .sort_values(
                ["coord_chave", "indenizacao_rs", "evento_preponderante"],
                ascending=[True, False, True],
            )
        )

        evento_lider = (
            ranking_evento
            .drop_duplicates(subset=["coord_chave"], keep="first")
            [["coord_chave", "evento_preponderante"]]
            .rename(columns={"evento_preponderante": "evento_lider"})
        )

    agregado = (
        agregado.merge(cultura_lider, on="coord_chave", how="left")
        .merge(seguradora_lider, on="coord_chave", how="left")
        .merge(evento_lider, on="coord_chave", how="left")
    )

    agregado["freq_indenizacao_pct"] = np.where(
        agregado["n_registros"] > 0,
        agregado["n_registros_indenizados"] / agregado["n_registros"] * 100,
        np.nan,
    )

    agregado["relacao_indenizacao_premio_pct"] = np.where(
        agregado["premio_liq_rs"] > 0,
        agregado["indenizacao_rs"] / agregado["premio_liq_rs"] * 100,
        np.nan,
    )

    agregado["relacao_indenizacao_limite_pct"] = np.where(
        agregado["limite_garantia_rs"] > 0,
        agregado["indenizacao_rs"] / agregado["limite_garantia_rs"] * 100,
        np.nan,
    )

    colunas_float = [
        "area_total_ha",
        "limite_garantia_rs",
        "premio_liq_rs",
        "subvencao_rs",
        "indenizacao_rs",
        "freq_indenizacao_pct",
        "relacao_indenizacao_premio_pct",
        "relacao_indenizacao_limite_pct",
    ]

    for coluna in colunas_float:
        agregado[coluna] = pd.to_numeric(agregado[coluna], errors="coerce").round(2)

    return gpd.GeoDataFrame(
        agregado,
        geometry=gpd.points_from_xy(agregado["longitude"], agregado["latitude"]),
        crs="EPSG:4326",
    )


# =============================================================================
# PREPARAÇÃO DAS SAÍDAS
# =============================================================================

if LIMPAR_SAIDAS_ANTERIORES:
    if PASTA_PARTES_PONTOS.exists():
        shutil.rmtree(PASTA_PARTES_PONTOS)

    PASTA_PARTES_PONTOS.mkdir(parents=True, exist_ok=True)

    for arquivo in [
        ARQUIVO_GPKG_PONTOS,
        Path(str(ARQUIVO_GPKG_PONTOS) + "-wal"),
        Path(str(ARQUIVO_GPKG_PONTOS) + "-shm"),
    ]:
        if arquivo.exists():
            arquivo.unlink()

if not CAMINHO_MALHA_MUNICIPAL.exists():
    raise FileNotFoundError(
        "Malha municipal não encontrada:\n"
        f"{CAMINHO_MALHA_MUNICIPAL}"
    )


# =============================================================================
# MALHA MUNICIPAL
# =============================================================================

print("Lendo malha municipal...")
gdf_municipios = gpd.read_file(
    CAMINHO_MALHA_MUNICIPAL,
    layer=CAMADA_MALHA_MUNICIPAL,
    engine="pyogrio",
)

if gdf_municipios.crs is None:
    raise ValueError("A malha municipal não possui CRS definido.")

campo_codigo_malha = localizar_coluna(
    gdf_municipios,
    ["CD_MUN", "CD_MUN7", "CD_GEOCMU", "CODMUN", "COD_MUN"],
)

gdf_municipios = gdf_municipios[[campo_codigo_malha, "geometry"]].copy()
gdf_municipios = gdf_municipios.rename(
    columns={campo_codigo_malha: "codigo_municipio_malha"}
)
gdf_municipios["codigo_municipio_malha"] = normalizar_codigo_municipio(
    gdf_municipios["codigo_municipio_malha"]
)
gdf_municipios = gdf_municipios.to_crs("EPSG:4326")

print(f"Municípios carregados: {len(gdf_municipios):,}")


# =============================================================================
# LEITURA DOS CSVs PSR
# =============================================================================

COLUNAS_LEITURA = [
    "ANO_APOLICE",
    "SG_UF_PROPRIEDADE",
    "CD_GEOCMU",
    "NM_MUNICIPIO_PROPRIEDADE",
    "NM_RAZAO_SOCIAL",
    "NM_CLASSIF_PRODUTO",
    "NM_CULTURA_GLOBAL",
    "NR_AREA_TOTAL",
    "VL_LIMITE_GARANTIA",
    "VL_PREMIO_LIQUIDO",
    "VL_SUBVENCAO_FEDERAL",
    "VALOR_INDENIZAÇÃO",
    "EVENTO_PREPONDERANTE",
    "NR_DECIMAL_LATITUDE",
    "NR_DECIMAL_LONGITUDE",
    "NR_GRAU_LAT",
    "NR_MIN_LAT",
    "NR_SEG_LAT",
    "NR_GRAU_LONG",
    "NR_MIN_LONG",
    "NR_SEG_LONG",
]

arquivos_csv = sorted(PASTA_RAW.glob("*.csv"))

if not arquivos_csv:
    raise FileNotFoundError(f"Nenhum CSV encontrado em: {PASTA_RAW}")

auditoria = []
amostras_rejeitados = []
contador_partes = 0

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
        usecols=COLUNAS_LEITURA,
        chunksize=CHUNKSIZE,
        low_memory=False,
        on_bad_lines="warn",
    )

    for numero_chunk, df in enumerate(leitor, start=1):
        print(f"Bloco {numero_chunk:,} | {len(df):,} registros")

        df["ano_apolice"] = (
            converter_numero_ptbr(df["ANO_APOLICE"])
            .round()
            .astype("Int64")
        )

        df = df[df["ano_apolice"].isin(ANOS_ANALISE)].copy()

        if df.empty:
            continue

        # Campos administrativos e categóricos
        df["uf"] = limpar_texto(df["SG_UF_PROPRIEDADE"])
        df["codigo_municipio"] = normalizar_codigo_municipio(df["CD_GEOCMU"])
        df["municipio"] = limpar_texto(df["NM_MUNICIPIO_PROPRIEDADE"])
        df["seguradora"] = limpar_texto(df["NM_RAZAO_SOCIAL"])
        df["classificacao_produto"] = limpar_texto(df["NM_CLASSIF_PRODUTO"])
        df["cultura"] = limpar_texto(df["NM_CULTURA_GLOBAL"])
        df["evento_preponderante"] = limpar_texto(df["EVENTO_PREPONDERANTE"])

        # Métricas
        df["area_total_ha"] = converter_numero_ptbr(df["NR_AREA_TOTAL"])
        df["limite_garantia_rs"] = converter_numero_ptbr(df["VL_LIMITE_GARANTIA"])
        df["premio_liq_rs"] = converter_numero_ptbr(df["VL_PREMIO_LIQUIDO"])
        df["subvencao_rs"] = converter_numero_ptbr(df["VL_SUBVENCAO_FEDERAL"])
        df["indenizacao_rs"] = converter_numero_ptbr(df["VALOR_INDENIZAÇÃO"])
        df["tem_indenizacao"] = (
            df["indenizacao_rs"].fillna(0).gt(0).astype("int8")
        )

        # Coordenadas decimais
        lat_decimal = converter_numero_ptbr(df["NR_DECIMAL_LATITUDE"])
        lon_decimal = converter_numero_ptbr(df["NR_DECIMAL_LONGITUDE"])

        decimal_valida = (
            lat_decimal.between(-35, 6)
            & lon_decimal.between(-75, -30)
        )

        # Coordenadas DMS
        lat_dms = dms_para_decimal(
            df["NR_GRAU_LAT"],
            df["NR_MIN_LAT"],
            df["NR_SEG_LAT"],
            eixo="lat",
        )

        lon_dms = dms_para_decimal(
            df["NR_GRAU_LONG"],
            df["NR_MIN_LONG"],
            df["NR_SEG_LONG"],
            eixo="lon",
        )

        dms_valida = (
            lat_dms.between(-35, 6)
            & lon_dms.between(-75, -30)
        )

        # Decimal válida tem prioridade. DMS é alternativa.
        # Garante máscaras booleanas sem pd.NA.
        decimal_valida = decimal_valida.fillna(False)
        dms_valida = dms_valida.fillna(False)

        # Decimal válida tem prioridade.
        df["latitude"] = lat_dms.copy()
        df["longitude"] = lon_dms.copy()

        df.loc[decimal_valida, "latitude"] = (
            lat_decimal.loc[decimal_valida]
        )

        df.loc[decimal_valida, "longitude"] = (
            lon_decimal.loc[decimal_valida]
        )

        # Fonte da coordenada usada.
        df["fonte_coordenada"] = "SEM_COORDENADA_VALIDA"

        df.loc[dms_valida, "fonte_coordenada"] = "DMS"

        df.loc[decimal_valida, "fonte_coordenada"] = "DECIMAL"

        # Validação espacial inicial: envelope do Brasil.
        df["coordenada_valida_brasil"] = (
            df["latitude"].between(-35, 6).fillna(False)
            & df["longitude"].between(-75, -30).fillna(False)
        )

        # Auditoria antes do join com municípios
        for ano, grupo in df.groupby("ano_apolice", dropna=False):
            auditoria.append(
                {
                    "ano_apolice": int(ano),
                    "registros_total": len(grupo),
                    "coord_decimal_valida": int(decimal_valida.loc[grupo.index].sum()),
                    "coord_dms_valida": int(dms_valida.loc[grupo.index].sum()),
                    "coord_valida_brasil": int(grupo["coordenada_valida_brasil"].sum()),
                }
            )

        df = df[df["coordenada_valida_brasil"]].copy()

        if df.empty:
            continue

        # Pontos e validação contra o município declarado.
        gdf_pontos = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
            crs="EPSG:4326",
        )

        gdf_join = gpd.sjoin(
            gdf_pontos,
            gdf_municipios,
            how="left",
            predicate="within",
        )

        gdf_join["ponto_dentro_municipio"] = (
            gdf_join["codigo_municipio"].fillna("")
            == gdf_join["codigo_municipio_malha"].fillna("")
        )

        rejeitados = gdf_join[~gdf_join["ponto_dentro_municipio"]].copy()

        if not rejeitados.empty:
            amostras_rejeitados.append(
                rejeitados[
                    [
                        "ano_apolice",
                        "uf",
                        "codigo_municipio",
                        "municipio",
                        "cultura",
                        "seguradora",
                        "latitude",
                        "longitude",
                        "fonte_coordenada",
                    ]
                ].head(50)
            )

        gdf_join = gdf_join[gdf_join["ponto_dentro_municipio"]].copy()

        if gdf_join.empty:
            continue

        # Coordenada arredondada para identificar pontos exatamente coincidentes.
        gdf_join["coord_chave"] = (
            gdf_join["latitude"].round(6).astype("string")
            + "|"
            + gdf_join["longitude"].round(6).astype("string")
        )

        campos_saida = [
            "ano_apolice",
            "uf",
            "codigo_municipio",
            "municipio",
            "seguradora",
            "classificacao_produto",
            "cultura",
            "area_total_ha",
            "limite_garantia_rs",
            "premio_liq_rs",
            "subvencao_rs",
            "indenizacao_rs",
            "tem_indenizacao",
            "evento_preponderante",
            "latitude",
            "longitude",
            "fonte_coordenada",
            "coord_chave",
            "geometry",
        ]

        gdf_saida = gdf_join[campos_saida].copy()

        contador_partes += 1
        destino_parquet = (
            PASTA_PARTES_PONTOS / f"pontos_psr_{contador_partes:04d}.parquet"
        )
        gdf_saida.to_parquet(destino_parquet, index=False)

        print(f"Pontos aceitos dentro do município: {len(gdf_saida):,}")


# =============================================================================
# AUDITORIA E CAMADAS GPKG
# =============================================================================

if contador_partes == 0:
    raise RuntimeError(
        "Nenhum ponto válido foi criado. Verifique a malha municipal e as coordenadas."
    )

df_auditoria = (
    pd.DataFrame(auditoria)
    .groupby("ano_apolice", as_index=False)
    .sum(numeric_only=True)
    .sort_values("ano_apolice")
)

contagens_finais = []

for ano in ANOS_ANALISE:
    gdf_ano = carregar_pontos(ano)

    contagens_finais.append(
        {
            "ano_apolice": ano,
            "pontos_aceitos_municipio": len(gdf_ano),
            "locais_unicos": int(gdf_ano["coord_chave"].nunique()) if not gdf_ano.empty else 0,
        }
    )

df_auditoria = df_auditoria.merge(
    pd.DataFrame(contagens_finais),
    on="ano_apolice",
    how="left",
)

df_auditoria["pct_pontos_aceitos_municipio"] = np.where(
    df_auditoria["registros_total"] > 0,
    df_auditoria["pontos_aceitos_municipio"] / df_auditoria["registros_total"] * 100,
    np.nan,
).round(2)

df_auditoria.to_csv(ARQUIVO_AUDITORIA, index=False, encoding="utf-8-sig")

if amostras_rejeitados:
    pd.concat(amostras_rejeitados, ignore_index=True).to_csv(
        ARQUIVO_REJEITADOS,
        index=False,
        encoding="utf-8-sig",
    )

for ano in ANOS_ANALISE:
    gdf_ano = carregar_pontos(ano)

    salvar_camada_gpkg(
        gdf_ano,
        ARQUIVO_GPKG_PONTOS,
        f"pt_{ano}",
    )

    gdf_local = agregar_localizacoes(gdf_ano)

    salvar_camada_gpkg(
        gdf_local,
        ARQUIVO_GPKG_PONTOS,
        f"loc_{ano}",
    )

gdf_total = carregar_pontos()
gdf_local_total = agregar_localizacoes(gdf_total)

salvar_camada_gpkg(
    gdf_local_total,
    ARQUIVO_GPKG_PONTOS,
    "loc_acum_2020_2024",
)

print("\n" + "=" * 90)
print("PONTOS PSR GERADOS COM SUCESSO")
print("=" * 90)
print(df_auditoria.to_string(index=False))
print(f"\nGeoPackage: {ARQUIVO_GPKG_PONTOS}")
print(f"Auditoria: {ARQUIVO_AUDITORIA}")
