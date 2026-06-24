# -*- coding: utf-8 -*-
"""Agrega pontos PSR em grades por cultura e seguradora, excluindo seguradoras dominantes.

Execute 07a_gerar_pontos_psr.py antes.
Os indicadores são recalculados após a exclusão das seguradoras configuradas.
Os dados originais não são alterados.
"""
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================
PASTA_PROJETO = Path(r"D:\AZ\PSR")
PASTA_PARTES_PONTOS = PASTA_PROJETO / "data" / "interim" / "pontos_psr_partes"
PASTA_VETORES = PASTA_PROJETO / "data" / "vetores"
PASTA_QUALIDADE = PASTA_PROJETO / "data" / "qualidade" / "grades_psr"
PASTA_VETORES.mkdir(parents=True, exist_ok=True)
PASTA_QUALIDADE.mkdir(parents=True, exist_ok=True)

ARQUIVO_GPKG = PASTA_VETORES / "psr_grades_culturas_sem_dominantes_2020_2024.gpkg"
ARQUIVO_AUDITORIA = PASTA_QUALIDADE / "psr_auditoria_grades_sem_dominantes_2020_2024.csv"
ANOS = [2020, 2021, 2022, 2023, 2024]

# Altere esta lista sempre que quiser incluir mais culturas.
CULTURAS_ANALISE = [
    "SOJA",
    "MILHO 1ª SAFRA",
    "MILHO 2ª SAFRA",
    "MAÇÃ",
    "UVA",
    "CAFÉ",
]

# Use os nomes exatamente como aparecem no campo "seguradora".
# A análise recalcula mercado, líder e HHI sem estas seguradoras.
SEGURADORAS_EXCLUIDAS = [
    "BRASILSEG COMPANHIA DE SEGUROS",
    "ALIANÇA DO BRASIL SEGUROS S/A.",
]

SEGURADORAS_EXCLUIDAS_NORMALIZADAS = {
    nome.strip().upper()
    for nome in SEGURADORAS_EXCLUIDAS
}

# True = também cria camadas detalhadas por hexágono + cultura + seguradora.
GERAR_CAMADAS_CULTSEG = True
SOBRESCREVER_GPKG = True

# Ajuste caminhos, camada (quando GPKG com mais de uma camada) e campo ID.
GRADES = {
    "h05": {
        "caminho": Path(r"D:\AZ\GRADES\hexagono_5km.gpkg"),
        "camada": None,
        "campo_id": "id_hex",
    },
    "h10": {
        "caminho": Path(r"D:\AZ\GRADES\hexagono_10km.gpkg"),
        "camada": None,
        "campo_id": "id_hex",
    },
    "h15": {
        "caminho": Path(r"D:\AZ\GRADES\hexagono_15km.gpkg"),
        "camada": None,
        "campo_id": "id_hex",
    },
    "h25": {
        "caminho": Path(r"D:\AZ\GRADES\hexagono_25km.gpkg"),
        "camada": None,
        "campo_id": "id_hex",
    },
    "h50": {
        "caminho": Path(r"D:\AZ\GRADES\hexagono_50km.gpkg"),
        "camada": None,
        "campo_id": "id_hex",
    },
}


def normalizar_chave_cultura(serie):
    """Normaliza texto de cultura para comparação sem acentos."""
    import unicodedata

    def _normalizar(valor):
        if valor is None:
            return ""
        texto = unicodedata.normalize("NFKD", str(valor))
        texto = "".join(c for c in texto if not unicodedata.combining(c))
        return " ".join(texto.upper().strip().split())

    return serie.astype("string").map(_normalizar)


def padronizar_cultura(serie):
    """
    Padroniza culturas prioritárias.

    Regra de negócio: qualquer categoria contendo MILHO + CONSORCI
    é incorporada a MILHO 2ª SAFRA.
    """
    resultado = serie.astype("string").str.strip().str.upper()
    chave = normalizar_chave_cultura(resultado)

    milho_consorciado = (
        chave.str.contains("MILHO", na=False)
        & chave.str.contains("CONSORCI", na=False)
    )
    milho_1 = (
        chave.str.contains("MILHO", na=False)
        & (
            chave.str.contains(r"\b1\b", regex=True, na=False)
            | chave.str.contains("PRIMEIRA", na=False)
        )
        & chave.str.contains("SAFRA", na=False)
    )
    milho_2 = (
        chave.str.contains("MILHO", na=False)
        & (
            chave.str.contains(r"\b2\b", regex=True, na=False)
            | chave.str.contains("SEGUNDA", na=False)
        )
        & chave.str.contains("SAFRA", na=False)
    )

    resultado.loc[chave.str.startswith("SOJA", na=False)] = "SOJA"
    resultado.loc[milho_1] = "MILHO 1ª SAFRA"
    resultado.loc[milho_2 | milho_consorciado] = "MILHO 2ª SAFRA"
    resultado.loc[chave.str.startswith("MACA", na=False)] = "MAÇÃ"
    resultado.loc[chave.str.startswith("UVA", na=False)] = "UVA"
    resultado.loc[chave.str.startswith("CAFE", na=False)] = "CAFÉ"

    return resultado

# =============================================================================
# FUNÇÕES
# =============================================================================
def salvar_camada(gdf, caminho_gpkg, camada):
    if gdf.empty:
        print(f"Camada vazia ignorada: {camada}")
        return
    kwargs = dict(
        filename=caminho_gpkg,
        layer=camada,
        driver="GPKG",
        engine="pyogrio",
        index=False,
        SPATIAL_INDEX="YES",
    )
    if caminho_gpkg.exists():
        kwargs["mode"] = "a"
    gdf.to_file(**kwargs)
    print(f"Camada salva: {camada} | {len(gdf):,} feições")


def validar_grade(gdf, campo_id, nome):
    if gdf.crs is None:
        raise ValueError(f"A grade {nome} não possui CRS definido.")
    if campo_id not in gdf.columns:
        raise KeyError(f"A grade {nome} não possui o campo '{campo_id}'.")
    if gdf[campo_id].isna().any() or gdf[campo_id].duplicated().any():
        raise ValueError(f"A grade {nome} possui IDs nulos ou duplicados.")
    if not gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError(f"A grade {nome} precisa possuir polígonos.")


def carregar_pontos(ano=None):
    partes = []
    for arquivo in sorted(PASTA_PARTES_PONTOS.glob("*.parquet")):
        gdf = gpd.read_parquet(arquivo)
        if ano is not None:
            gdf = gdf[gdf["ano_apolice"].eq(ano)].copy()
        if not gdf.empty:
            partes.append(gdf)
    if not partes:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs="EPSG:4326")


def lider_por_premio(df, chaves, categoria, nome_saida):
    ranking = (
        df.groupby(chaves + [categoria], as_index=False, dropna=False)["premio_liq_rs"]
        .sum()
        .sort_values(chaves + ["premio_liq_rs", categoria], ascending=[True] * len(chaves) + [False, True])
    )
    return (
        ranking.drop_duplicates(subset=chaves, keep="first")[chaves + [categoria, "premio_liq_rs"]]
        .rename(columns={categoria: nome_saida, "premio_liq_rs": "premio_lider_rs"})
    )


def evento_lider_por_indenizacao(df, chaves):
    eventos = df[df["tem_indenizacao"].eq(1) & df["evento_preponderante"].notna()].copy()
    if eventos.empty:
        return pd.DataFrame(columns=chaves + ["evento_lider"])
    ranking = (
        eventos.groupby(chaves + ["evento_preponderante"], as_index=False, dropna=False)["indenizacao_rs"]
        .sum()
        .sort_values(chaves + ["indenizacao_rs", "evento_preponderante"], ascending=[True] * len(chaves) + [False, True])
    )
    return (
        ranking.drop_duplicates(subset=chaves, keep="first")[chaves + ["evento_preponderante"]]
        .rename(columns={"evento_preponderante": "evento_lider"})
    )


def arredondar(gdf):
    campos = [
        "area_total_ha", "limite_garantia_rs", "premio_liq_rs", "subvencao_rs",
        "indenizacao_rs", "premio_por_ha", "limite_por_ha", "freq_indenizacao_pct",
        "relacao_indenizacao_premio_pct", "relacao_indenizacao_limite_pct",
        "market_share_seg_pct", "share_seguradora_lider_pct", "hhi_premio",
    ]
    for campo in campos:
        if campo in gdf.columns:
            gdf[campo] = pd.to_numeric(gdf[campo], errors="coerce").round(2)
    return gdf


def agregar_grade_cultura(gdf_pontos, gdf_grade, campo_id, acumulado=False):
    """Retorna (camada hex+cultura, camada hex+cultura+seguradora, n pontos associados)."""
    vazio = gpd.GeoDataFrame(geometry=[], crs=gdf_grade.crs)
    if gdf_pontos.empty:
        return vazio, vazio, 0

    grade_join = gdf_grade[[campo_id, "geometry"]].copy().rename(columns={campo_id: "grid_id"})
    grade_join["grid_id"] = grade_join["grid_id"].astype("string")
    pontos = gdf_pontos.to_crs(gdf_grade.crs)
    join = gpd.sjoin(pontos, grade_join, how="inner", predicate="within")
    if join.empty:
        return vazio, vazio, 0

    join["grid_id"] = join["grid_id"].astype("string")

    # Padroniza antes do filtro. MILHO CONSORCIADO é incorporado a MILHO 2ª SAFRA.
    join["cultura"] = padronizar_cultura(join["cultura"])
    join = join[join["cultura"].isin(CULTURAS_ANALISE)].copy()

    # Remove seguradoras dominantes antes de calcular todos os indicadores.
    join["seguradora_normalizada"] = (
        join["seguradora"]
        .astype("string")
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.upper()
    )
    join = join[
        ~join["seguradora_normalizada"].isin(SEGURADORAS_EXCLUIDAS_NORMALIZADAS)
    ].copy()

    if join.empty:
        return vazio, vazio, 0

    chaves = ["grid_id", "cultura"] if acumulado else ["grid_id", "ano_apolice", "cultura"]
    chaves_seg = chaves + ["seguradora"]

    # Detalhe por hexágono + cultura + seguradora
    df_cultseg = (
        join.groupby(chaves_seg, as_index=False, dropna=False)
        .agg(
            n_registros=("coord_chave", "size"),
            n_localizacoes=("coord_chave", "nunique"),
            area_total_ha=("area_total_ha", "sum"),
            limite_garantia_rs=("limite_garantia_rs", "sum"),
            premio_liq_rs=("premio_liq_rs", "sum"),
            subvencao_rs=("subvencao_rs", "sum"),
            indenizacao_rs=("indenizacao_rs", "sum"),
            n_registros_indenizados=("tem_indenizacao", "sum"),
        )
    )
    df_cultseg["premio_total_cultura_hex"] = df_cultseg.groupby(chaves)["premio_liq_rs"].transform("sum")
    df_cultseg["market_share_seg_pct"] = np.where(
        df_cultseg["premio_total_cultura_hex"] > 0,
        df_cultseg["premio_liq_rs"] / df_cultseg["premio_total_cultura_hex"] * 100,
        np.nan,
    )
    df_cultseg["freq_indenizacao_pct"] = np.where(
        df_cultseg["n_registros"] > 0,
        df_cultseg["n_registros_indenizados"] / df_cultseg["n_registros"] * 100,
        np.nan,
    )
    df_cultseg["relacao_indenizacao_premio_pct"] = np.where(
        df_cultseg["premio_liq_rs"] > 0,
        df_cultseg["indenizacao_rs"] / df_cultseg["premio_liq_rs"] * 100,
        np.nan,
    )
    df_cultseg["premio_por_ha"] = np.where(
        df_cultseg["area_total_ha"] > 0,
        df_cultseg["premio_liq_rs"] / df_cultseg["area_total_ha"],
        np.nan,
    )
    df_cultseg["limite_por_ha"] = np.where(
        df_cultseg["area_total_ha"] > 0,
        df_cultseg["limite_garantia_rs"] / df_cultseg["area_total_ha"],
        np.nan,
    )
    df_cultseg["ranking_premio_seg"] = (
        df_cultseg.groupby(chaves)["premio_liq_rs"].rank(method="dense", ascending=False).astype("Int64")
    )
    df_cultseg["eh_seguradora_lider"] = df_cultseg["ranking_premio_seg"].eq(1).astype("int8")

    # Camada resumida por hexágono + cultura
    df_cultura = (
        join.groupby(chaves, as_index=False, dropna=False)
        .agg(
            n_registros=("coord_chave", "size"),
            n_localizacoes=("coord_chave", "nunique"),
            n_anos=("ano_apolice", "nunique"),
            n_seguradoras=("seguradora", "nunique"),
            area_total_ha=("area_total_ha", "sum"),
            limite_garantia_rs=("limite_garantia_rs", "sum"),
            premio_liq_rs=("premio_liq_rs", "sum"),
            subvencao_rs=("subvencao_rs", "sum"),
            indenizacao_rs=("indenizacao_rs", "sum"),
            n_registros_indenizados=("tem_indenizacao", "sum"),
        )
    )
    df_cultura["freq_indenizacao_pct"] = np.where(
        df_cultura["n_registros"] > 0,
        df_cultura["n_registros_indenizados"] / df_cultura["n_registros"] * 100,
        np.nan,
    )
    df_cultura["relacao_indenizacao_premio_pct"] = np.where(
        df_cultura["premio_liq_rs"] > 0,
        df_cultura["indenizacao_rs"] / df_cultura["premio_liq_rs"] * 100,
        np.nan,
    )
    df_cultura["relacao_indenizacao_limite_pct"] = np.where(
        df_cultura["limite_garantia_rs"] > 0,
        df_cultura["indenizacao_rs"] / df_cultura["limite_garantia_rs"] * 100,
        np.nan,
    )
    df_cultura["premio_por_ha"] = np.where(
        df_cultura["area_total_ha"] > 0,
        df_cultura["premio_liq_rs"] / df_cultura["area_total_ha"],
        np.nan,
    )
    df_cultura["limite_por_ha"] = np.where(
        df_cultura["area_total_ha"] > 0,
        df_cultura["limite_garantia_rs"] / df_cultura["area_total_ha"],
        np.nan,
    )

    # Seguradora líder, share da líder e HHI dentro da cultura no hexágono.
    lider = lider_por_premio(df_cultseg, chaves, "seguradora", "seguradora_lider")
    lider = lider.merge(
        df_cultseg[chaves + ["seguradora", "market_share_seg_pct"]],
        left_on=chaves + ["seguradora_lider"],
        right_on=chaves + ["seguradora"],
        how="left",
    ).drop(columns=["seguradora"])
    lider = lider.rename(columns={"market_share_seg_pct": "share_seguradora_lider_pct"})

    df_hhi_base = df_cultseg.copy()
    df_hhi_base["share_decimal"] = np.where(
        df_hhi_base["premio_total_cultura_hex"] > 0,
        df_hhi_base["premio_liq_rs"] / df_hhi_base["premio_total_cultura_hex"],
        0,
    )
    hhi = (
        df_hhi_base.assign(hhi_parcela=df_hhi_base["share_decimal"] ** 2)
        .groupby(chaves, as_index=False)["hhi_parcela"].sum()
    )
    hhi["hhi_premio"] = hhi["hhi_parcela"] * 10000
    hhi = hhi[chaves + ["hhi_premio"]]
    hhi["classificacao_concentracao"] = np.select(
        [hhi["hhi_premio"] < 1500, hhi["hhi_premio"] < 2500],
        ["BAIXA_CONCENTRACAO", "CONCENTRACAO_MODERADA"],
        default="ALTA_CONCENTRACAO",
    )
    evento = evento_lider_por_indenizacao(join, chaves)

    df_cultura = (
        df_cultura.merge(lider, on=chaves, how="left")
        .merge(hhi, on=chaves, how="left")
        .merge(evento, on=chaves, how="left")
    )

    # Merge robusto: grid_id é sempre texto em ambos os lados.
    grade_saida = gdf_grade.copy()
    grade_saida["grid_id"] = grade_saida[campo_id].astype("string")
    gdf_cultura = gpd.GeoDataFrame(
        grade_saida.merge(df_cultura, on="grid_id", how="inner"),
        geometry="geometry",
        crs=gdf_grade.crs,
    )
    gdf_cultseg = gpd.GeoDataFrame(
        grade_saida.merge(df_cultseg, on="grid_id", how="inner"),
        geometry="geometry",
        crs=gdf_grade.crs,
    )

    return arredondar(gdf_cultura), arredondar(gdf_cultseg), len(join)


# =============================================================================
# EXECUÇÃO
# =============================================================================
if not PASTA_PARTES_PONTOS.exists() or not list(PASTA_PARTES_PONTOS.glob("*.parquet")):
    raise FileNotFoundError(
        "Não foram encontrados pontos intermediários. Execute primeiro 07a_gerar_pontos_psr.py."
    )

if SOBRESCREVER_GPKG:
    for arquivo in [ARQUIVO_GPKG, Path(str(ARQUIVO_GPKG) + "-wal"), Path(str(ARQUIVO_GPKG) + "-shm")]:
        if arquivo.exists():
            arquivo.unlink()

print("Carregando pontos acumulados...")
pontos_acumulados = carregar_pontos()
print(f"Pontos carregados: {len(pontos_acumulados):,}")
print("Culturas selecionadas:", ", ".join(CULTURAS_ANALISE))
print("Seguradoras excluídas:", ", ".join(SEGURADORAS_EXCLUIDAS))

auditoria = []

for nome_grade, config in GRADES.items():
    caminho = config["caminho"]
    camada = config["camada"]
    campo_id = config["campo_id"]

    if not caminho.exists():
        raise FileNotFoundError(f"Grade não encontrada: {caminho}")

    print("\n" + "=" * 100)
    print(f"PROCESSANDO GRADE: {nome_grade}")
    print("=" * 100)

    grade = gpd.read_file(caminho, layer=camada, engine="pyogrio")
    validar_grade(grade, campo_id, nome_grade)
    print(f"Células na grade: {len(grade):,}")

    for ano in ANOS:
        print(f"Agregando {ano}...")
        pontos_ano = carregar_pontos(ano)
        gdf_cult, gdf_cultseg, n_associados = agregar_grade_cultura(
            pontos_ano, grade, campo_id, acumulado=False
        )
        salvar_camada(gdf_cult, ARQUIVO_GPKG, f"{nome_grade}_{ano}_cult_sem_dom")
        if GERAR_CAMADAS_CULTSEG:
            salvar_camada(gdf_cultseg, ARQUIVO_GPKG, f"{nome_grade}_{ano}_cultseg_sem_dom")

        auditoria.append({
            "grade": nome_grade,
            "periodo": str(ano),
            "pontos_georreferenciados": len(pontos_ano),
            "pontos_culturas_selecionadas_associados": n_associados,
            "pct_pontos_associados": round(n_associados / len(pontos_ano) * 100, 2) if len(pontos_ano) else np.nan,
            "hex_cultura_com_registro": len(gdf_cult),
            "hex_cultura_seguradora_com_registro": len(gdf_cultseg),
        })

    print("Agregando acumulado 2020-2024...")
    gdf_cult, gdf_cultseg, n_associados = agregar_grade_cultura(
        pontos_acumulados, grade, campo_id, acumulado=True
    )
    salvar_camada(gdf_cult, ARQUIVO_GPKG, f"{nome_grade}_acum_cult_sem_dom")
    if GERAR_CAMADAS_CULTSEG:
        salvar_camada(gdf_cultseg, ARQUIVO_GPKG, f"{nome_grade}_acum_cultseg_sem_dom")

    auditoria.append({
        "grade": nome_grade,
        "periodo": "ACUM_2020_2024",
        "pontos_georreferenciados": len(pontos_acumulados),
        "pontos_culturas_selecionadas_associados": n_associados,
        "pct_pontos_associados": round(n_associados / len(pontos_acumulados) * 100, 2) if len(pontos_acumulados) else np.nan,
        "hex_cultura_com_registro": len(gdf_cult),
        "hex_cultura_seguradora_com_registro": len(gdf_cultseg),
    })

pd.DataFrame(auditoria).to_csv(ARQUIVO_AUDITORIA, index=False, encoding="utf-8-sig")
print("\n" + "=" * 100)
print("GRADES POR CULTURA E SEGURADORA (SEM DOMINANTES) GERADAS COM SUCESSO")
print("=" * 100)
print(f"GeoPackage: {ARQUIVO_GPKG}")
print(f"Auditoria: {ARQUIVO_AUDITORIA}")
