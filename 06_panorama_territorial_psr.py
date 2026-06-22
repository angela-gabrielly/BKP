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
    / "panorama_territorial"
)

PASTA_TEMP = PASTA_PROJETO / "temp_duckdb"

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)

ANO_FINAL_COMPLETO = 2024

CULTURAS_AGRICOLAS = [
    "SOJA",
    "MILHO 1ª SAFRA",
    "MILHO 2ª SAFRA",
    "TRIGO",
    "ARROZ",
    "CAFÉ",
    "MAÇÃ",
    "UVA",
    "TOMATE",
    "CEBOLA",
    "CANA-DE-AÇÚCAR",
    "FEIJÃO 1ª SAFRA",
    "FEIJÃO 2ª SAFRA",
    "FEIJÃO 3ª SAFRA",
    "SORGO",
    "ALGODÃO",
    "AMENDOIM",
    "BATATA",
    "CEVADA",
    "PÊSSEGO",
    "CAQUI",
    "AMEIXA",
]


# ============================================================
# FUNÇÕES
# ============================================================

def caminho_sql(caminho):
    return caminho.resolve().as_posix().replace("'", "''")


def exportar_parquet(conexao, consulta_sql, caminho_saida):
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    conexao.execute(
        f"""
        COPY (
            {consulta_sql}
        )
        TO '{caminho_sql(caminho_saida)}'
        (
            FORMAT PARQUET,
            COMPRESSION ZSTD
        )
        """
    )


def exportar_csv(conexao, consulta_sql, caminho_saida):
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    conexao.execute(
        f"""
        COPY (
            {consulta_sql}
        )
        TO '{caminho_sql(caminho_saida)}'
        (
            FORMAT CSV,
            HEADER TRUE,
            DELIMITER ','
        )
        """
    )


# ============================================================
# CONEXÃO E BASE
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

print("Base PSR carregada no DuckDB.")


# ============================================================
# 1. BASE ANUAL POR MUNICÍPIO
# ============================================================

sql_municipio_ano = """
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,

    COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

    COUNT(DISTINCT seguradora) AS seguradoras_atuantes,

    COUNT(DISTINCT cultura) AS culturas_atuantes,

    SUM(COALESCE(area_total, 0)) AS area_total,

    SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,

    SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,

    SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,

    SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total,

    COUNT(
        DISTINCT CASE
            WHEN tem_indenizacao
            THEN id_apolice_anon
            ELSE NULL
        END
    ) AS quantidade_apolices_indenizadas,

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

    CASE
        WHEN COUNT(DISTINCT id_apolice_anon) > 0
        THEN
            COUNT(
                DISTINCT CASE
                    WHEN tem_indenizacao
                    THEN id_apolice_anon
                    ELSE NULL
                END
            ) * 100.0
            / COUNT(DISTINCT id_apolice_anon)
        ELSE NULL
    END AS percentual_apolices_indenizadas

FROM psr

WHERE
    ano_apolice <= 2024
    AND COALESCE(flag_ano_invalido, FALSE) = FALSE

GROUP BY
    ano_apolice,
    uf,
    codigo_municipio,
    municipio
"""

caminho_municipio_ano = (
    PASTA_SAIDA
    / "psr_municipio_ano_2006_2024.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_municipio_ano,
    caminho_saida=caminho_municipio_ano
)


# ============================================================
# 2. LÍDER DO MUNICÍPIO POR PRÊMIO
# ============================================================

sql_lider_seguradora_municipio = """
WITH seguradoras_municipio AS (
    SELECT
        ano_apolice,
        uf,
        codigo_municipio,
        municipio,
        seguradora,

        COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

        SUM(COALESCE(area_total, 0)) AS area_total,

        SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total

    FROM psr

    WHERE
        ano_apolice <= 2024
        AND COALESCE(flag_ano_invalido, FALSE) = FALSE

    GROUP BY
        ano_apolice,
        uf,
        codigo_municipio,
        municipio,
        seguradora
),

shares AS (
    SELECT
        *,

        SUM(premio_liquido_total) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio
        ) AS premio_total_municipio,

        COUNT(*) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio
        ) AS seguradoras_atuantes,

        RANK() OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio
            ORDER BY
                premio_liquido_total DESC
        ) AS ranking_por_premio

    FROM seguradoras_municipio
),

concentracao AS (
    SELECT
        *,

        CASE
            WHEN premio_total_municipio > 0
            THEN premio_liquido_total / premio_total_municipio
            ELSE NULL
        END AS market_share_premio

    FROM shares
),

resultado AS (
    SELECT
        *,

        SUM(
            POWER(
                COALESCE(market_share_premio, 0),
                2
            )
        ) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio
        ) * 10000 AS hhi_premio

    FROM concentracao
)

SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,

    seguradora AS seguradora_lider_por_premio,

    premio_liquido_total AS premio_lider,

    market_share_premio AS market_share_premio_lider,

    seguradoras_atuantes,

    hhi_premio,

    CASE
        WHEN hhi_premio < 1500
        THEN 'BAIXA_CONCENTRACAO'

        WHEN hhi_premio < 2500
        THEN 'CONCENTRACAO_MODERADA'

        ELSE 'ALTA_CONCENTRACAO'
    END AS classificacao_concentracao

FROM resultado
WHERE ranking_por_premio = 1
"""

caminho_lider_seguradora = (
    PASTA_SAIDA
    / "psr_lider_seguradora_municipio_ano_2006_2024.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_lider_seguradora_municipio,
    caminho_saida=caminho_lider_seguradora
)


# ============================================================
# 3. CULTURA LÍDER DO MUNICÍPIO POR PRÊMIO
# ============================================================

sql_lider_cultura_municipio = """
WITH culturas_municipio AS (
    SELECT
        ano_apolice,
        uf,
        codigo_municipio,
        municipio,
        cultura,

        COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

        SUM(COALESCE(area_total, 0)) AS area_total,

        SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total

    FROM psr

    WHERE
        ano_apolice <= 2024
        AND COALESCE(flag_ano_invalido, FALSE) = FALSE

    GROUP BY
        ano_apolice,
        uf,
        codigo_municipio,
        municipio,
        cultura
),

ranking AS (
    SELECT
        *,

        SUM(premio_liquido_total) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio
        ) AS premio_total_municipio,

        RANK() OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio
            ORDER BY
                premio_liquido_total DESC
        ) AS ranking_por_premio

    FROM culturas_municipio
)

SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,

    cultura AS cultura_lider_por_premio,

    premio_liquido_total AS premio_cultura_lider,

    CASE
        WHEN premio_total_municipio > 0
        THEN premio_liquido_total / premio_total_municipio
        ELSE NULL
    END AS market_share_cultura_lider

FROM ranking
WHERE ranking_por_premio = 1
"""

caminho_lider_cultura = (
    PASTA_SAIDA
    / "psr_lider_cultura_municipio_ano_2006_2024.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_lider_cultura_municipio,
    caminho_saida=caminho_lider_cultura
)


# ============================================================
# 4. TABELA TERRITORIAL FINAL
# ============================================================

sql_mapa_territorial = f"""
SELECT
    municipio_base.*,

    seguradora_lider.seguradora_lider_por_premio,
    seguradora_lider.premio_lider,
    seguradora_lider.market_share_premio_lider,
    seguradora_lider.hhi_premio,
    seguradora_lider.classificacao_concentracao,

    cultura_lider.cultura_lider_por_premio,
    cultura_lider.premio_cultura_lider,
    cultura_lider.market_share_cultura_lider,

    CASE
        WHEN municipio_base.premio_liquido_total >= 100000000
        THEN 'MUITO_ALTO'

        WHEN municipio_base.premio_liquido_total >= 30000000
        THEN 'ALTO'

        WHEN municipio_base.premio_liquido_total >= 5000000
        THEN 'MEDIO'

        ELSE 'BAIXO'
    END AS faixa_tamanho_mercado

FROM read_parquet('{caminho_sql(caminho_municipio_ano)}') AS municipio_base

LEFT JOIN read_parquet('{caminho_sql(caminho_lider_seguradora)}') AS seguradora_lider
    ON municipio_base.ano_apolice = seguradora_lider.ano_apolice
    AND municipio_base.uf = seguradora_lider.uf
    AND municipio_base.codigo_municipio = seguradora_lider.codigo_municipio
    AND municipio_base.municipio = seguradora_lider.municipio

LEFT JOIN read_parquet('{caminho_sql(caminho_lider_cultura)}') AS cultura_lider
    ON municipio_base.ano_apolice = cultura_lider.ano_apolice
    AND municipio_base.uf = cultura_lider.uf
    AND municipio_base.codigo_municipio = cultura_lider.codigo_municipio
    AND municipio_base.municipio = cultura_lider.municipio
"""

caminho_mapa_territorial = (
    PASTA_SAIDA
    / "psr_panorama_territorial_municipio_ano_2006_2024.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_mapa_territorial,
    caminho_saida=caminho_mapa_territorial
)


# ============================================================
# 5. RANKING MUNICIPAL 2024
# ============================================================

sql_ranking_municipios_2024 = f"""
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,

    quantidade_apolices,
    seguradoras_atuantes,
    culturas_atuantes,

    area_total,
    limite_garantia_total,
    premio_liquido_total,
    subvencao_federal_total,
    valor_indenizacao_total,

    premio_por_area,
    limite_garantia_por_area,
    taxa_implicita_premio_limite,

    seguradora_lider_por_premio,
    market_share_premio_lider,
    hhi_premio,
    classificacao_concentracao,

    cultura_lider_por_premio,
    market_share_cultura_lider,

    faixa_tamanho_mercado

FROM read_parquet('{caminho_sql(caminho_mapa_territorial)}')

WHERE ano_apolice = 2024

ORDER BY premio_liquido_total DESC
"""

caminho_ranking_2024 = (
    PASTA_SAIDA
    / "psr_ranking_municipios_2024.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_ranking_municipios_2024,
    caminho_saida=caminho_ranking_2024
)


# ============================================================
# 6. RANKING MUNICIPAL 2024 PARA CULTURAS AGRÍCOLAS
# ============================================================

culturas_sql = ", ".join(
    f"'{cultura}'"
    for cultura in CULTURAS_AGRICOLAS
)

sql_ranking_cultura_2024 = f"""
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura,

    COUNT(DISTINCT id_apolice_anon) AS quantidade_apolices,

    COUNT(DISTINCT seguradora) AS seguradoras_atuantes,

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
    END AS taxa_implicita_premio_limite

FROM psr

WHERE
    ano_apolice = 2024
    AND cultura IN ({culturas_sql})
    AND COALESCE(flag_ano_invalido, FALSE) = FALSE

GROUP BY
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura

ORDER BY
    premio_liquido_total DESC
"""

caminho_ranking_cultura_2024 = (
    PASTA_SAIDA
    / "psr_ranking_municipios_cultura_2024.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_ranking_cultura_2024,
    caminho_saida=caminho_ranking_cultura_2024
)


# ============================================================
# FINALIZAÇÃO
# ============================================================

print("\n" + "=" * 90)
print("PANORAMA TERRITORIAL PSR GERADO COM SUCESSO")
print("=" * 90)

arquivos_gerados = [
    caminho_municipio_ano,
    caminho_lider_seguradora,
    caminho_lider_cultura,
    caminho_mapa_territorial,
    caminho_ranking_2024,
    caminho_ranking_cultura_2024,
]

for arquivo in arquivos_gerados:
    tamanho_mb = arquivo.stat().st_size / (1024 ** 2)
    print(f"- {arquivo.name} | {tamanho_mb:,.2f} MB")

con.close()