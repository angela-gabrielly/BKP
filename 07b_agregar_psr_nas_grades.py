# -*- coding: utf-8 -*-
"""
07b_agregar_psr_nas_grades.py

Agrega os pontos PSR em grades fornecidas pelo usuário.

O script NÃO cria grades. Ele usa os arquivos existentes de 5, 10, 15, 25 e 50 km.

Pré-requisito:
Executar antes o script 07a_gerar_pontos_psr.py.

Saídas:
- data/vetores/psr_grades_2020_2024.gpkg
- data/qualidade/grades_psr/psr_auditoria_grades_2020_2024.csv
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_PARTES_PONTOS = (
    PASTA_PROJETO / "data" / "interim" / "pontos_psr_partes"
)

PASTA_VETORES = PASTA_PROJETO / "data" / "vetores"

PASTA_QUALIDADE = (
    PASTA_PROJETO / "data" / "qualidade" / "grades_psr"
)

PASTA_VETORES.mkdir(parents=True, exist_ok=True)
PASTA_QUALIDADE.mkdir(parents=True, exist_ok=True)

ARQUIVO_GPKG_GRADES = (
    PASTA_VETORES / "psr_grades_2020_2024.gpkg"
)

ARQUIVO_AUDITORIA = (
    PASTA_QUALIDADE / "psr_auditoria_grades_2020_2024.csv"
)

ANOS_ANALISE = [2020, 2021, 2022, 2023, 2024]
SOBRESCREVER_GPKG = True


# =============================================================================
# AJUSTE OS CAMINHOS E OS CAMPOS IDENTIFICADORES DAS SUAS GRADES
#
# "camada": None para SHP, GeoJSON ou GPKG com camada única.
# "campo_id": precisa ter valor único para cada célula.
# =============================================================================

GRADES = {
    "h05": {
        "caminho": Path(r"D:\AZ\PSR\data\grade\hexagono_5km.gpkg"),
        "camada": None,
        "campo_id": "id",
    },
    "h10": {
        "caminho": Path(r"D:\AZ\PSR\data\grade\hexagono_10km.gpkg"),
        "camada": None,
        "campo_id": "id",
    },
    "h15": {
        "caminho": Path(r"D:\AZ\PSR\data\grade\hexagono_15km.gpkg"),
        "camada": None,
        "campo_id": "id",
    },
    "h25": {
        "caminho": Path(r"D:\AZ\PSR\data\grade\hexagono_25km.gpkg"),
        "camada": None,
        "campo_id": "id",
    },
    "h50": {
        "caminho": Path(r"D:\AZ\PSR\data\grade\hexagono_50km.gpkg"),
        "camada": None,
        "campo_id": "id",
    },
}


# =============================================================================
# FUNÇÕES
# =============================================================================

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
    print(f"Camada salva: {camada} | {len(gdf):,} células")


def validar_grade(
    gdf_grade: gpd.GeoDataFrame,
    campo_id: str,
    nome_grade: str,
) -> None:
    """Valida estrutura mínima da grade."""
    if gdf_grade.crs is None:
        raise ValueError(f"A grade {nome_grade} não possui CRS definido.")

    if campo_id not in gdf_grade.columns:
        raise KeyError(
            f"A grade {nome_grade} não possui o campo '{campo_id}'."
        )

    if gdf_grade[campo_id].isna().any():
        raise ValueError(f"A grade {nome_grade} possui IDs nulos.")

    if gdf_grade[campo_id].duplicated().any():
        raise ValueError(f"A grade {nome_grade} possui IDs duplicados.")

    if not gdf_grade.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError(
            f"A grade {nome_grade} precisa possuir geometrias poligonais."
        )


def carregar_pontos(periodo: int | None = None) -> gpd.GeoDataFrame:
    """Carrega pontos intermediários, com filtro opcional por ano."""
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


def calcular_lider(
    df: pd.DataFrame,
    chaves: list[str],
    categoria: str,
    valor: str,
    nome_saida: str,
) -> pd.DataFrame:
    """Retorna categoria líder pelo maior valor agregado."""
    ranking = (
        df.groupby(chaves + [categoria], dropna=False, as_index=False)[valor]
        .sum()
        .sort_values(chaves + [valor, categoria], ascending=[True] * len(chaves) + [False, True])
    )

    return (
        ranking.drop_duplicates(subset=chaves, keep="first")[chaves + [categoria]]
        .rename(columns={categoria: nome_saida})
    )


def agregar_por_grade(
    gdf_pontos: gpd.GeoDataFrame,
    gdf_grade: gpd.GeoDataFrame,
    campo_id_grade: str,
    acumulado: bool,
) -> tuple[gpd.GeoDataFrame, int]:
    """
    Associa pontos à grade e calcula métricas por célula.

    Retorna:
    - camada vetorial com células contendo registros;
    - quantidade de pontos associados a uma célula.
    """
    if gdf_pontos.empty:
        return gpd.GeoDataFrame(geometry=[], crs=gdf_grade.crs), 0

    gdf_grade_base = gdf_grade[[campo_id_grade, "geometry"]].copy()
    gdf_grade_base = gdf_grade_base.rename(columns={campo_id_grade: "grid_id"})
    gdf_grade_base["grid_id"] = gdf_grade_base["grid_id"].astype("string")

    gdf_pontos_proj = gdf_pontos.to_crs(gdf_grade.crs)

    gdf_join = gpd.sjoin(
        gdf_pontos_proj,
        gdf_grade_base,
        how="inner",
        predicate="within",
    )

    if gdf_join.empty:
        return gpd.GeoDataFrame(geometry=[], crs=gdf_grade.crs), 0

    gdf_join["grid_id"] = gdf_join["grid_id"].astype("string")

    chaves = ["grid_id"] if acumulado else ["grid_id", "ano_apolice"]

    # Métricas centrais
    df_agregado = (
        gdf_join.groupby(chaves, dropna=False, as_index=False)
        .agg(
            n_registros=("coord_chave", "size"),
            n_localizacoes=("coord_chave", "nunique"),
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

    df_agregado["freq_indenizacao_pct"] = np.where(
        df_agregado["n_registros"] > 0,
        df_agregado["n_registros_indenizados"] / df_agregado["n_registros"] * 100,
        np.nan,
    )

    df_agregado["relacao_indenizacao_premio_pct"] = np.where(
        df_agregado["premio_liq_rs"] > 0,
        df_agregado["indenizacao_rs"] / df_agregado["premio_liq_rs"] * 100,
        np.nan,
    )

    df_agregado["relacao_indenizacao_limite_pct"] = np.where(
        df_agregado["limite_garantia_rs"] > 0,
        df_agregado["indenizacao_rs"] / df_agregado["limite_garantia_rs"] * 100,
        np.nan,
    )

    df_agregado["premio_por_ha"] = np.where(
        df_agregado["area_total_ha"] > 0,
        df_agregado["premio_liq_rs"] / df_agregado["area_total_ha"],
        np.nan,
    )

    df_agregado["limite_por_ha"] = np.where(
        df_agregado["area_total_ha"] / 1 > 0,
        df_agregado["limite_garantia_rs"] / df_agregado["area_total_ha"],
        np.nan,
    )

    # Lideranças
    cultura_lider = calcular_lider(
        gdf_join, chaves, "cultura", "premio_liq_rs", "cultura_lider"
    )
    seguradora_lider = calcular_lider(
        gdf_join, chaves, "seguradora", "premio_liq_rs", "seguradora_lider"
    )

    # HHI do prêmio por seguradora
    df_share = (
        gdf_join.groupby(chaves + ["seguradora"], dropna=False, as_index=False)["premio_liq_rs"]
        .sum()
    )

    df_share["premio_total_grid"] = (
        df_share.groupby(chaves)["premio_liq_rs"].transform("sum")
    )

    df_share["market_share"] = np.where(
        df_share["premio_total_grid"] > 0,
        df_share["premio_liq_rs"] / df_share["premio_total_grid"],
        0,
    )

    df_hhi = (
        df_share.assign(hhi_parcela=df_share["market_share"] ** 2)
        .groupby(chaves, as_index=False)["hhi_parcela"]
        .sum()
    )

    df_hhi["hhi_premio"] = df_hhi["hhi_parcela"] * 10000
    df_hhi = df_hhi[chaves + ["hhi_premio"]]

    # Evento dominante por valor de indenização
    eventos = gdf_join[
        gdf_join["tem_indenizacao"].eq(1)
        & gdf_join["evento_preponderante"].notna()
    ].copy()

    if eventos.empty:
        evento_lider = pd.DataFrame(columns=chaves + ["evento_lider"])
    else:
        evento_lider = calcular_lider(
            eventos,
            chaves,
            "evento_preponderante",
            "indenizacao_rs",
            "evento_lider",
        )

    df_final = (
        df_agregado
        .merge(cultura_lider, on=chaves, how="left")
        .merge(seguradora_lider, on=chaves, how="left")
        .merge(df_hhi, on=chaves, how="left")
        .merge(evento_lider, on=chaves, how="left")
    )

    df_final["classificacao_concentracao"] = np.select(
        [
            df_final["hhi_premio"] < 1500,
            df_final["hhi_premio"] < 2500,
        ],
        [
            "BAIXA_CONCENTRACAO",
            "CONCENTRACAO_MODERADA",
        ],
        default="ALTA_CONCENTRACAO",
    )

    # Padroniza a chave da grade como texto antes do merge final.
    # Isso evita conflito entre, por exemplo, id numérico e grid_id textual.
    gdf_grade_saida = gdf_grade.copy()

    gdf_grade_saida["grid_id"] = (
        gdf_grade_saida[campo_id_grade]
        .astype("string")
    )

    gdf_saida = gdf_grade_saida.merge(
        df_final,
        on="grid_id",
        how="inner",
    )

    gdf_saida = gpd.GeoDataFrame(
        gdf_saida,
        geometry="geometry",
        crs=gdf_grade.crs,
    )

    campos_numericos = [
        "area_total_ha",
        "limite_garantia_rs",
        "premio_liq_rs",
        "subvencao_rs",
        "indenizacao_rs",
        "freq_indenizacao_pct",
        "relacao_indenizacao_premio_pct",
        "relacao_indenizacao_limite_pct",
        "premio_por_ha",
        "limite_por_ha",
        "hhi_premio",
    ]

    for campo in campos_numericos:
        if campo in gdf_saida.columns:
            gdf_saida[campo] = pd.to_numeric(
                gdf_saida[campo], errors="coerce"
            ).round(2)

    return gdf_saida, len(gdf_join)


# =============================================================================
# PREPARAÇÃO
# =============================================================================

if not PASTA_PARTES_PONTOS.exists():
    raise FileNotFoundError(
        "Pasta de pontos intermediários não encontrada. "
        "Execute primeiro o script 07a_gerar_pontos_psr.py."
    )

if not list(PASTA_PARTES_PONTOS.glob("*.parquet")):
    raise FileNotFoundError(
        "Nenhum GeoParquet de pontos encontrado. "
        "Execute primeiro o script 07a_gerar_pontos_psr.py."
    )

if SOBRESCREVER_GPKG:
    for arquivo in [
        ARQUIVO_GPKG_GRADES,
        Path(str(ARQUIVO_GPKG_GRADES) + "-wal"),
        Path(str(ARQUIVO_GPKG_GRADES) + "-shm"),
    ]:
        if arquivo.exists():
            arquivo.unlink()


# =============================================================================
# PROCESSAMENTO
# =============================================================================

print("Carregando pontos acumulados de 2020 a 2024...")
gdf_pontos_acumulados = carregar_pontos()

print(f"Pontos carregados: {len(gdf_pontos_acumulados):,}")

auditoria = []

for nome_grade, config in GRADES.items():
    caminho_grade = config["caminho"]
    camada_grade = config["camada"]
    campo_id_grade = config["campo_id"]

    if not caminho_grade.exists():
        raise FileNotFoundError(f"Grade não encontrada: {caminho_grade}")

    print("\n" + "=" * 90)
    print(f"PROCESSANDO GRADE: {nome_grade}")
    print("=" * 90)

    gdf_grade = gpd.read_file(
        caminho_grade,
        layer=camada_grade,
        engine="pyogrio",
    )

    validar_grade(gdf_grade, campo_id_grade, nome_grade)

    print(f"Células na grade: {len(gdf_grade):,}")

    # Camadas anuais
    for ano in ANOS_ANALISE:
        print(f"Agregando ano {ano}...")

        gdf_pontos_ano = carregar_pontos(ano)

        gdf_resultado, pontos_associados = agregar_por_grade(
            gdf_pontos_ano,
            gdf_grade,
            campo_id_grade,
            acumulado=False,
        )

        salvar_camada_gpkg(
            gdf_resultado,
            ARQUIVO_GPKG_GRADES,
            f"{nome_grade}_{ano}",
        )

        auditoria.append(
            {
                "grade": nome_grade,
                "periodo": str(ano),
                "pontos_validos": len(gdf_pontos_ano),
                "pontos_associados_grade": pontos_associados,
                "pct_pontos_associados": round(
                    pontos_associados / len(gdf_pontos_ano) * 100,
                    2,
                ) if len(gdf_pontos_ano) > 0 else np.nan,
                "celulas_com_registros": len(gdf_resultado),
            }
        )

    # Camada acumulada
    print("Agregando acumulado 2020-2024...")

    gdf_acumulado, pontos_associados = agregar_por_grade(
        gdf_pontos_acumulados,
        gdf_grade,
        campo_id_grade,
        acumulado=True,
    )

    salvar_camada_gpkg(
        gdf_acumulado,
        ARQUIVO_GPKG_GRADES,
        f"{nome_grade}_acum_2020_2024",
    )

    auditoria.append(
        {
            "grade": nome_grade,
            "periodo": "ACUM_2020_2024",
            "pontos_validos": len(gdf_pontos_acumulados),
            "pontos_associados_grade": pontos_associados,
            "pct_pontos_associados": round(
                pontos_associados / len(gdf_pontos_acumulados) * 100,
                2,
            ) if len(gdf_pontos_acumulados) > 0 else np.nan,
            "celulas_com_registros": len(gdf_acumulado),
        }
    )


# =============================================================================
# FINALIZAÇÃO
# =============================================================================

df_auditoria = pd.DataFrame(auditoria)
df_auditoria.to_csv(ARQUIVO_AUDITORIA, index=False, encoding="utf-8-sig")

print("\n" + "=" * 90)
print("GRADES PSR GERADAS COM SUCESSO")
print("=" * 90)
print(df_auditoria.to_string(index=False))

print(f"\nGeoPackage: {ARQUIVO_GPKG_GRADES}")
print(f"Auditoria: {ARQUIVO_AUDITORIA}")
