from pathlib import Path
import duckdb
import pandas as pd


# ============================================================
# CONFIGURAÇÃO
# ============================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")

PASTA_PARTES = (
    PASTA_PROJETO
    / "data"
    / "processed"
    / "psr_base_analitica_partes"
)

PASTA_SAIDA = (
    PASTA_PROJETO
    / "data"
    / "processed"
    / "panorama_nacional"
)

PASTA_TEMP = PASTA_PROJETO / "temp_duckdb"

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)

ANO_FINAL_COMPLETO = 2024
ANO_PARCIAL = 2025


# ============================================================
# FUNÇÕES
# ============================================================

def caminho_sql(caminho):
    return caminho.resolve().as_posix().replace("'", "''")


def exportar_csv(conexao, consulta_sql, caminho_saida):
    caminho_saida = Path(caminho_saida)
    destino = caminho_sql(caminho_saida)

    conexao.execute(
        f"""
        COPY (
            {consulta_sql}
        )
        TO '{destino}'
        (
            FORMAT CSV,
            HEADER TRUE,
            DELIMITER ','
        )
        """
    )


# ============================================================
# CONEXÃO E LEITURA DA BASE
# ============================================================

con = duckdb.connect()

con.execute(
    f"""
    SET temp_directory = '{caminho_sql(PASTA_TEMP)}'
    """
)

glob_parquet = caminho_sql(PASTA_PARTES / "*.parquet")

con.execute(
    f"""
    CREATE OR REPLACE VIEW psr AS
    SELECT *
    FROM read_parquet(
        '{glob_parquet}',
        union_by_name = true
    )
    """
)


# ============================================================
# 1. PADRONIZAÇÃO ANALÍTICA DE ANOS
# ============================================================

sql_base = f"""
SELECT
    *,
    CASE
        WHEN ano_apolice <= {ANO_FINAL_COMPLETO}
        THEN 'ANO_COMPLETO'

        WHEN ano_apolice = {ANO_PARCIAL}
        THEN 'ANO_PARCIAL'

        ELSE 'ANO_A_VALIDAR'
    END AS status_ano
FROM psr
WHERE COALESCE(flag_ano_invalido, FALSE) = FALSE
"""

con.execute(
    f"""
    CREATE OR REPLACE VIEW psr_analitico AS
    {sql_base}
    """
)


# ============================================================
# 2. LISTA DE CULTURAS
# ============================================================

sql_culturas = """
SELECT
    cultura,
    COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,
    COUNT(DISTINCT seguradora) AS seguradoras_atuantes,
    COUNT(DISTINCT uf) AS ufs_atuantes,
    SUM(COALESCE(area_total, 0)) AS area_total,
    SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,
    SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,
    SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,
    SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total
FROM psr_analitico
WHERE ano_apolice <= 2024
GROUP BY cultura
ORDER BY premio_liquido_total DESC
"""

caminho_culturas = (
    PASTA_SAIDA
    / "psr_ranking_culturas_2006_2024.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_culturas,
    caminho_saida=caminho_culturas
)


# ============================================================
# 3. PANORAMA POR ANO E CULTURA
# ============================================================

sql_ano_cultura = """
SELECT
    ano_apolice,
    status_ano,
    cultura,

    COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

    COUNT(DISTINCT seguradora) AS seguradoras_atuantes,

    COUNT(DISTINCT CONCAT(
        COALESCE(uf, ''),
        '|',
        COALESCE(codigo_municipio, ''),
        '|',
        COALESCE(municipio, '')
    )) AS municipios_atuantes,

    SUM(COALESCE(area_total, 0)) AS area_total,

    SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,

    SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,

    SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,

    SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total,

    CASE
        WHEN SUM(COALESCE(area_total, 0)) > 0
        THEN
            SUM(COALESCE(premio_liquido, 0))
            / SUM(COALESCE(area_total, 0))
        ELSE NULL
    END AS premio_por_area,

    CASE
        WHEN SUM(COALESCE(area_total, 0)) > 0
        THEN
            SUM(COALESCE(limite_garantia, 0))
            / SUM(COALESCE(area_total, 0))
        ELSE NULL
    END AS limite_garantia_por_area,

    CASE
        WHEN SUM(COALESCE(limite_garantia, 0)) > 0
        THEN
            SUM(COALESCE(premio_liquido, 0))
            / SUM(COALESCE(limite_garantia, 0))
        ELSE NULL
    END AS taxa_implicita_premio_limite,

    AVG(taxa) AS taxa_media_simples,

    CASE
        WHEN SUM(COALESCE(limite_garantia, 0)) > 0
        THEN
            SUM(
                COALESCE(taxa, 0)
                * COALESCE(limite_garantia, 0)
            )
            / SUM(COALESCE(limite_garantia, 0))
        ELSE NULL
    END AS taxa_media_ponderada_limite

FROM psr_analitico
GROUP BY
    ano_apolice,
    status_ano,
    cultura
ORDER BY
    ano_apolice,
    premio_liquido_total DESC
"""

caminho_ano_cultura = (
    PASTA_SAIDA
    / "psr_panorama_ano_cultura.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_ano_cultura,
    caminho_saida=caminho_ano_cultura
)


# ============================================================
# 4. PANORAMA POR ANO, CULTURA E SEGURADORA
# ============================================================

sql_ano_cultura_seguradora = """
WITH base AS (
    SELECT
        ano_apolice,
        status_ano,
        cultura,
        seguradora,

        COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

        SUM(COALESCE(area_total, 0)) AS area_total,

        SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,

        SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,

        SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,

        SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total

    FROM psr_analitico

    GROUP BY
        ano_apolice,
        status_ano,
        cultura,
        seguradora
),

totais AS (
    SELECT
        *,

        SUM(premio_liquido_total) OVER (
            PARTITION BY
                ano_apolice,
                cultura
        ) AS premio_total_cultura,

        SUM(area_total) OVER (
            PARTITION BY
                ano_apolice,
                cultura
        ) AS area_total_cultura,

        SUM(quantidade_apolices) OVER (
            PARTITION BY
                ano_apolice,
                cultura
        ) AS apolices_totais_cultura

    FROM base
)

SELECT
    *,

    CASE
        WHEN premio_total_cultura > 0
        THEN premio_liquido_total / premio_total_cultura
        ELSE NULL
    END AS market_share_premio,

    CASE
        WHEN area_total_cultura > 0
        THEN area_total / area_total_cultura
        ELSE NULL
    END AS market_share_area,

    CASE
        WHEN apolices_totais_cultura > 0
        THEN quantidade_apolices * 1.0 / apolices_totais_cultura
        ELSE NULL
    END AS market_share_apolices,

    RANK() OVER (
        PARTITION BY
            ano_apolice,
            cultura
        ORDER BY
            premio_liquido_total DESC
    ) AS ranking_por_premio

FROM totais
ORDER BY
    ano_apolice,
    cultura,
    ranking_por_premio
"""

caminho_ano_cultura_seguradora = (
    PASTA_SAIDA
    / "psr_panorama_ano_cultura_seguradora.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_ano_cultura_seguradora,
    caminho_saida=caminho_ano_cultura_seguradora
)


# ============================================================
# 5. RANKING NACIONAL DE SEGURADORAS
# ============================================================

sql_seguradoras = """
SELECT
    seguradora,

    COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

    COUNT(DISTINCT cultura) AS culturas_atuantes,

    COUNT(DISTINCT uf) AS ufs_atuantes,

    COUNT(DISTINCT CONCAT(
        COALESCE(uf, ''),
        '|',
        COALESCE(codigo_municipio, ''),
        '|',
        COALESCE(municipio, '')
    )) AS municipios_atuantes,

    SUM(COALESCE(area_total, 0)) AS area_total,

    SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,

    SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,

    SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,

    SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total

FROM psr_analitico
WHERE ano_apolice <= 2024
GROUP BY seguradora
ORDER BY premio_liquido_total DESC
"""

caminho_seguradoras = (
    PASTA_SAIDA
    / "psr_ranking_seguradoras_2006_2024.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_seguradoras,
    caminho_saida=caminho_seguradoras
)


# ============================================================
# 6. PANORAMA POR UF E CULTURA
# ============================================================

sql_uf_cultura = """
SELECT
    ano_apolice,
    status_ano,
    uf,
    cultura,

    COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

    COUNT(DISTINCT seguradora) AS seguradoras_atuantes,

    COUNT(DISTINCT CONCAT(
        COALESCE(codigo_municipio, ''),
        '|',
        COALESCE(municipio, '')
    )) AS municipios_atuantes,

    SUM(COALESCE(area_total, 0)) AS area_total,

    SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,

    SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,

    SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,

    SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total,

    CASE
        WHEN SUM(COALESCE(area_total, 0)) > 0
        THEN
            SUM(COALESCE(premio_liquido, 0))
            / SUM(COALESCE(area_total, 0))
        ELSE NULL
    END AS premio_por_area,

    CASE
        WHEN SUM(COALESCE(limite_garantia, 0)) > 0
        THEN
            SUM(COALESCE(premio_liquido, 0))
            / SUM(COALESCE(limite_garantia, 0))
        ELSE NULL
    END AS taxa_implicita_premio_limite

FROM psr_analitico

GROUP BY
    ano_apolice,
    status_ano,
    uf,
    cultura

ORDER BY
    ano_apolice,
    premio_liquido_total DESC
"""

caminho_uf_cultura = (
    PASTA_SAIDA
    / "psr_panorama_uf_cultura.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_uf_cultura,
    caminho_saida=caminho_uf_cultura
)


# ============================================================
# FINALIZAÇÃO
# ============================================================

print("\n" + "=" * 90)
print("PANORAMA NACIONAL GERADO COM SUCESSO")
print("=" * 90)

arquivos_gerados = [
    caminho_culturas,
    caminho_ano_cultura,
    caminho_ano_cultura_seguradora,
    caminho_seguradoras,
    caminho_uf_cultura,
]

for arquivo in arquivos_gerados:
    tamanho_mb = arquivo.stat().st_size / (1024 ** 2)
    print(f"- {arquivo.name} | {tamanho_mb:,.2f} MB")

con.close()