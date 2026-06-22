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
    / "indicadores"
)

PASTA_QUALIDADE = (
    PASTA_PROJETO
    / "data"
    / "qualidade"
)

PASTA_TEMP = PASTA_PROJETO / "temp_duckdb"

PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_QUALIDADE.mkdir(parents=True, exist_ok=True)
PASTA_TEMP.mkdir(parents=True, exist_ok=True)

if not PASTA_PARTES.exists():
    raise FileNotFoundError(
        f"Pasta de partes parquet não encontrada: {PASTA_PARTES}"
    )

if not list(PASTA_PARTES.glob("*.parquet")):
    raise FileNotFoundError(
        f"Nenhum arquivo parquet encontrado em: {PASTA_PARTES}"
    )


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def caminho_sql(caminho):
    """
    Converte um caminho Windows em formato seguro para DuckDB SQL.
    """
    return caminho.resolve().as_posix().replace("'", "''")


def exportar_parquet(conexao, consulta_sql, caminho_saida):
    """
    Exporta resultado de uma consulta DuckDB para Parquet.
    """
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    destino_sql = caminho_sql(caminho_saida)

    conexao.execute(
        f"""
        COPY (
            {consulta_sql}
        )
        TO '{destino_sql}'
        (
            FORMAT PARQUET,
            COMPRESSION ZSTD
        )
        """
    )


def exportar_csv(conexao, consulta_sql, caminho_saida):
    """
    Exporta resultado de uma consulta DuckDB para CSV.
    """
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    destino_sql = caminho_sql(caminho_saida)

    conexao.execute(
        f"""
        COPY (
            {consulta_sql}
        )
        TO '{destino_sql}'
        (
            FORMAT CSV,
            HEADER TRUE,
            DELIMITER ','
        )
        """
    )


# ============================================================
# CONEXÃO DUCKDB E VIEW DA BASE
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

print("View DuckDB criada com sucesso.")
print(f"Fonte: {PASTA_PARTES}")


# ============================================================
# 1. COBERTURA TEMPORAL E VOLUME ANUAL
# ============================================================

sql_cobertura_anual = """
SELECT
    ano_apolice,
    MIN(data_apolice) AS primeira_data_apolice,
    MAX(data_apolice) AS ultima_data_apolice,
    COUNT(*) AS registros_psr,
    COUNT(DISTINCT id_apolice_anon) AS ids_apolice_unicos,
    COUNT(DISTINCT municipio) AS municipios_com_registro,
    COUNT(DISTINCT seguradora) AS seguradoras_atuantes,
    SUM(COALESCE(area_total, 0)) AS area_total,
    SUM(COALESCE(limite_garantia, 0)) AS limite_garantia_total,
    SUM(COALESCE(premio_liquido, 0)) AS premio_liquido_total,
    SUM(COALESCE(subvencao_federal, 0)) AS subvencao_federal_total,
    SUM(COALESCE(valor_indenizacao, 0)) AS valor_indenizacao_total,
    SUM(
        CASE
            WHEN tem_indenizacao THEN 1
            ELSE 0
        END
    ) AS registros_com_indenizacao
FROM psr
GROUP BY ano_apolice
ORDER BY ano_apolice
"""

df_cobertura_anual = con.execute(
    sql_cobertura_anual
).df()

caminho_cobertura_anual = (
    PASTA_SAIDA
    / "psr_cobertura_anual.csv"
)

df_cobertura_anual.to_csv(
    caminho_cobertura_anual,
    index=False,
    encoding="utf-8-sig"
)

print("\n" + "=" * 100)
print("COBERTURA TEMPORAL POR ANO")
print("=" * 100)

print(
    df_cobertura_anual.to_string(
        index=False
    )
)


# ============================================================
# 2. VALIDAÇÃO DA UNIDADE DO REGISTRO
# ============================================================

sql_validacao_ids = """
SELECT
    COUNT(*) AS registros_psr,
    COUNT(DISTINCT id_apolice_anon) AS ids_apolice_unicos,
    COUNT(*) - COUNT(DISTINCT id_apolice_anon) AS registros_repetidos_por_id,
    ROUND(
        COUNT(*) * 1.0
        / NULLIF(COUNT(DISTINCT id_apolice_anon), 0),
        4
    ) AS media_registros_por_id
FROM psr
"""

df_validacao_ids = con.execute(
    sql_validacao_ids
).df()

caminho_validacao_ids = (
    PASTA_QUALIDADE
    / "psr_validacao_ids_apolice.csv"
)

df_validacao_ids.to_csv(
    caminho_validacao_ids,
    index=False,
    encoding="utf-8-sig"
)

print("\n" + "=" * 100)
print("VALIDAÇÃO DA UNIDADE DE REGISTRO")
print("=" * 100)

print(
    df_validacao_ids.to_string(
        index=False
    )
)

sql_distribuicao_registros_por_id = """
WITH contagem_ids AS (
    SELECT
        id_apolice_anon,
        COUNT(*) AS registros_por_id
    FROM psr
    GROUP BY id_apolice_anon
)
SELECT
    registros_por_id,
    COUNT(*) AS quantidade_ids,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (),
        4
    ) AS percentual_ids
FROM contagem_ids
GROUP BY registros_por_id
ORDER BY registros_por_id
"""

df_distribuicao_ids = con.execute(
    sql_distribuicao_registros_por_id
).df()

caminho_distribuicao_ids = (
    PASTA_QUALIDADE
    / "psr_distribuicao_registros_por_id.csv"
)

df_distribuicao_ids.to_csv(
    caminho_distribuicao_ids,
    index=False,
    encoding="utf-8-sig"
)

print("\nDistribuição de linhas por identificador anônimo:")
print(
    df_distribuicao_ids.head(20).to_string(
        index=False
    )
)


# ============================================================
# 3. AUDITORIA DE PRÊMIO NEGATIVO E OUTLIERS
# ============================================================

sql_premio_negativo = """
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    seguradora,
    cultura,
    classificacao_produto,
    area_total,
    limite_garantia,
    premio_liquido,
    subvencao_federal,
    valor_indenizacao,
    data_apolice,
    arquivo_origem,
    linha_origem
FROM psr
WHERE premio_liquido < 0
ORDER BY ano_apolice, uf, municipio
"""

caminho_premio_negativo = (
    PASTA_QUALIDADE
    / "psr_registros_premio_negativo.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_premio_negativo,
    caminho_saida=caminho_premio_negativo
)

sql_top_limites = """
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    seguradora,
    cultura,
    classificacao_produto,
    area_total,
    limite_garantia,
    premio_liquido,
    taxa,
    subvencao_federal,
    valor_indenizacao,
    data_apolice
FROM psr
WHERE limite_garantia IS NOT NULL
ORDER BY limite_garantia DESC
LIMIT 100
"""

caminho_top_limites = (
    PASTA_QUALIDADE
    / "psr_top_100_limites_garantia.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_top_limites,
    caminho_saida=caminho_top_limites
)

sql_perfil_taxa = """
SELECT
    ano_apolice,
    COUNT(taxa) AS registros_com_taxa,
    MIN(taxa) AS taxa_minima,
    QUANTILE_CONT(taxa, 0.25) AS taxa_p25,
    QUANTILE_CONT(taxa, 0.50) AS taxa_mediana,
    QUANTILE_CONT(taxa, 0.75) AS taxa_p75,
    MAX(taxa) AS taxa_maxima,
    AVG(taxa) AS taxa_media_simples
FROM psr
WHERE taxa IS NOT NULL
GROUP BY ano_apolice
ORDER BY ano_apolice
"""

df_perfil_taxa = con.execute(
    sql_perfil_taxa
).df()

caminho_perfil_taxa = (
    PASTA_QUALIDADE
    / "psr_perfil_taxa_anual.csv"
)

df_perfil_taxa.to_csv(
    caminho_perfil_taxa,
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# 4. BASE DE MERCADO:
#    ANO × UF × MUNICÍPIO × CULTURA × SEGURADORA
# ============================================================

sql_municipio_cultura_seguradora = """
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura,
    seguradora,

    COUNT(*) AS registros_psr,

    COUNT(
        DISTINCT id_apolice_anon
    ) AS ids_apolice_unicos,

    SUM(
        COALESCE(area_total, 0)
    ) AS area_total,

    SUM(
        COALESCE(limite_garantia, 0)
    ) AS limite_garantia_total,

    SUM(
        COALESCE(premio_liquido, 0)
    ) AS premio_liquido_total,

    SUM(
        CASE
            WHEN premio_liquido >= 0
            THEN premio_liquido
            ELSE 0
        END
    ) AS premio_liquido_positivo,

    SUM(
        CASE
            WHEN premio_liquido < 0
            THEN 1
            ELSE 0
        END
    ) AS registros_premio_negativo,

    SUM(
        COALESCE(subvencao_federal, 0)
    ) AS subvencao_federal_total,

    SUM(
        COALESCE(valor_indenizacao, 0)
    ) AS valor_indenizacao_total,

    SUM(
        CASE
            WHEN tem_indenizacao THEN 1
            ELSE 0
        END
    ) AS registros_com_indenizacao,

    COUNT(
        DISTINCT CASE
            WHEN tem_indenizacao
            THEN id_apolice_anon
            ELSE NULL
        END
    ) AS ids_com_indenizacao,

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
    END AS taxa_media_ponderada_limite,

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
        WHEN COUNT(*) > 0
        THEN
            SUM(
                CASE
                    WHEN tem_indenizacao THEN 1
                    ELSE 0
                END
            ) * 100.0 / COUNT(*)
        ELSE NULL
    END AS percentual_registros_com_indenizacao

FROM psr

WHERE COALESCE(flag_ano_invalido, FALSE) = FALSE

GROUP BY
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura,
    seguradora
"""

caminho_municipio_cultura_seguradora = (
    PASTA_SAIDA
    / "psr_municipio_cultura_seguradora_ano.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_municipio_cultura_seguradora,
    caminho_saida=caminho_municipio_cultura_seguradora
)


# ============================================================
# 5. BASE DE MERCADO:
#    ANO × UF × MUNICÍPIO × CULTURA
# ============================================================

sql_municipio_cultura = """
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura,

    COUNT(*) AS registros_psr,

    COUNT(
        DISTINCT id_apolice_anon
    ) AS ids_apolice_unicos,

    COUNT(
        DISTINCT seguradora
    ) AS seguradoras_atuantes,

    SUM(
        COALESCE(area_total, 0)
    ) AS area_total,

    SUM(
        COALESCE(limite_garantia, 0)
    ) AS limite_garantia_total,

    SUM(
        COALESCE(premio_liquido, 0)
    ) AS premio_liquido_total,

    SUM(
        CASE
            WHEN premio_liquido >= 0
            THEN premio_liquido
            ELSE 0
        END
    ) AS premio_liquido_positivo,

    SUM(
        CASE
            WHEN premio_liquido < 0
            THEN 1
            ELSE 0
        END
    ) AS registros_premio_negativo,

    SUM(
        COALESCE(subvencao_federal, 0)
    ) AS subvencao_federal_total,

    SUM(
        COALESCE(valor_indenizacao, 0)
    ) AS valor_indenizacao_total,

    SUM(
        CASE
            WHEN tem_indenizacao THEN 1
            ELSE 0
        END
    ) AS registros_com_indenizacao,

    COUNT(
        DISTINCT CASE
            WHEN tem_indenizacao
            THEN id_apolice_anon
            ELSE NULL
        END
    ) AS ids_com_indenizacao,

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
    END AS taxa_media_ponderada_limite,

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
        WHEN COUNT(*) > 0
        THEN
            SUM(
                CASE
                    WHEN tem_indenizacao THEN 1
                    ELSE 0
                END
            ) * 100.0 / COUNT(*)
        ELSE NULL
    END AS percentual_registros_com_indenizacao

FROM psr

WHERE COALESCE(flag_ano_invalido, FALSE) = FALSE

GROUP BY
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura
"""

caminho_municipio_cultura = (
    PASTA_SAIDA
    / "psr_municipio_cultura_ano.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_municipio_cultura,
    caminho_saida=caminho_municipio_cultura
)


# ============================================================
# 6. MARKET SHARE E CONCENTRAÇÃO POR SEGURADORA
# ============================================================

caminho_seg_sql = caminho_sql(
    caminho_municipio_cultura_seguradora
)

sql_market_share = f"""
WITH base AS (
    SELECT *
    FROM read_parquet('{caminho_seg_sql}')
),

totais AS (
    SELECT
        *,

        SUM(premio_liquido_total) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio,
                cultura
        ) AS premio_total_mercado,

        SUM(area_total) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio,
                cultura
        ) AS area_total_mercado,

        SUM(ids_apolice_unicos) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio,
                cultura
        ) AS ids_total_mercado,

        COUNT(*) OVER (
            PARTITION BY
                ano_apolice,
                uf,
                codigo_municipio,
                municipio,
                cultura
        ) AS seguradoras_atuantes_mercado

    FROM base
),

shares AS (
    SELECT
        *,

        CASE
            WHEN premio_total_mercado > 0
            THEN premio_liquido_total / premio_total_mercado
            ELSE NULL
        END AS market_share_premio,

        CASE
            WHEN area_total_mercado > 0
            THEN area_total / area_total_mercado
            ELSE NULL
        END AS market_share_area,

        CASE
            WHEN ids_total_mercado > 0
            THEN ids_apolice_unicos * 1.0 / ids_total_mercado
            ELSE NULL
        END AS market_share_ids

    FROM totais
)

SELECT
    *,

    RANK() OVER (
        PARTITION BY
            ano_apolice,
            uf,
            codigo_municipio,
            municipio,
            cultura
        ORDER BY
            premio_liquido_total DESC NULLS LAST
    ) AS ranking_por_premio,

    RANK() OVER (
        PARTITION BY
            ano_apolice,
            uf,
            codigo_municipio,
            municipio,
            cultura
        ORDER BY
            area_total DESC NULLS LAST
    ) AS ranking_por_area,

    RANK() OVER (
        PARTITION BY
            ano_apolice,
            uf,
            codigo_municipio,
            municipio,
            cultura
        ORDER BY
            ids_apolice_unicos DESC NULLS LAST
    ) AS ranking_por_ids,

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
            municipio,
            cultura
    ) * 10000 AS hhi_premio,

    SUM(
        POWER(
            COALESCE(market_share_area, 0),
            2
        )
    ) OVER (
        PARTITION BY
            ano_apolice,
            uf,
            codigo_municipio,
            municipio,
            cultura
    ) * 10000 AS hhi_area,

    SUM(
        POWER(
            COALESCE(market_share_ids, 0),
            2
        )
    ) OVER (
        PARTITION BY
            ano_apolice,
            uf,
            codigo_municipio,
            municipio,
            cultura
    ) * 10000 AS hhi_ids

FROM shares
"""

caminho_market_share = (
    PASTA_SAIDA
    / "psr_market_share_municipio_cultura_ano.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_market_share,
    caminho_saida=caminho_market_share
)


# ============================================================
# 7. SEGURADORAS LÍDERES POR PRÊMIO
# ============================================================

caminho_market_share_sql = caminho_sql(
    caminho_market_share
)

sql_lideres = f"""
SELECT
    ano_apolice,
    uf,
    codigo_municipio,
    municipio,
    cultura,
    seguradora AS seguradora_lider_por_premio,
    premio_liquido_total AS premio_lider,
    market_share_premio AS market_share_premio_lider,
    seguradoras_atuantes_mercado,
    hhi_premio
FROM read_parquet('{caminho_market_share_sql}')
WHERE ranking_por_premio = 1
"""

caminho_lideres = (
    PASTA_SAIDA
    / "psr_lideres_municipio_cultura_ano.parquet"
)

exportar_parquet(
    conexao=con,
    consulta_sql=sql_lideres,
    caminho_saida=caminho_lideres
)


# ============================================================
# 8. RESUMO EXECUTIVO NACIONAL POR ANO E CULTURA
# ============================================================

sql_resumo_nacional_cultura = """
SELECT
    ano_apolice,
    cultura,

    COUNT(*) AS registros_psr,

    COUNT(
        DISTINCT id_apolice_anon
    ) AS ids_apolice_unicos,

    COUNT(
        DISTINCT seguradora
    ) AS seguradoras_atuantes,

    COUNT(
        DISTINCT CONCAT(
            COALESCE(uf, ''),
            '|',
            COALESCE(codigo_municipio, ''),
            '|',
            COALESCE(municipio, '')
        )
    ) AS municipios_com_registro,

    SUM(
        COALESCE(area_total, 0)
    ) AS area_total,

    SUM(
        COALESCE(limite_garantia, 0)
    ) AS limite_garantia_total,

    SUM(
        COALESCE(premio_liquido, 0)
    ) AS premio_liquido_total,

    SUM(
        COALESCE(subvencao_federal, 0)
    ) AS subvencao_federal_total,

    SUM(
        COALESCE(valor_indenizacao, 0)
    ) AS valor_indenizacao_total,

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

FROM psr

WHERE COALESCE(flag_ano_invalido, FALSE) = FALSE

GROUP BY
    ano_apolice,
    cultura

ORDER BY
    ano_apolice,
    premio_liquido_total DESC
"""

caminho_resumo_nacional_cultura = (
    PASTA_SAIDA
    / "psr_resumo_nacional_cultura_ano.csv"
)

exportar_csv(
    conexao=con,
    consulta_sql=sql_resumo_nacional_cultura,
    caminho_saida=caminho_resumo_nacional_cultura
)


# ============================================================
# FINALIZAÇÃO
# ============================================================

print("\n" + "=" * 100)
print("PANORAMA PSR GERADO COM SUCESSO")
print("=" * 100)

print("\nArquivos principais gerados:")

arquivos_principais = [
    caminho_cobertura_anual,
    caminho_validacao_ids,
    caminho_distribuicao_ids,
    caminho_premio_negativo,
    caminho_top_limites,
    caminho_perfil_taxa,
    caminho_municipio_cultura_seguradora,
    caminho_municipio_cultura,
    caminho_market_share,
    caminho_lideres,
    caminho_resumo_nacional_cultura,
]

for arquivo in arquivos_principais:
    if arquivo.exists():
        tamanho_mb = arquivo.stat().st_size / (1024 ** 2)
        print(f"- {arquivo.name} | {tamanho_mb:,.2f} MB")

con.close()