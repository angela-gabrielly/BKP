# -*- coding: utf-8 -*-
"""
09_criar_projeto_qgis_psr.py

EXECUTE DENTRO DO QGIS:
Plugins > Python Console > Show Editor > Open Script > Run Script

Cria um projeto .qgz com grupos temáticos e camadas pré-estilizadas.
Não altera os GeoPackages de origem; os estilos ficam salvos no .qgz.
"""

from pathlib import Path
import math

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsProject,
    QgsRendererCategory,
    QgsRendererRange,
    QgsSingleSymbolRenderer,
    QgsStyle,
    QgsSymbol,
    QgsVectorLayer,
)

# =============================================================================
# CONFIGURAÇÃO — AJUSTE AQUI
# =============================================================================

PASTA_PROJETO = Path(r"D:\AZ\PSR")
PASTA_VETORES = PASTA_PROJETO / "data" / "vetores"
PASTA_REFERENCIAS = PASTA_PROJETO / "data" / "referencias"
PASTA_QGIS = PASTA_PROJETO / "qgis"
PASTA_QGIS.mkdir(parents=True, exist_ok=True)

# Grade padrão do projeto: h05, h10, h15, h25 ou h50.
PREFIXO_GRADE = "h10"

# Para não deixar o projeto pesado, começa somente com acumulado 2020–2024.
# Mude para True caso queira acrescentar também as camadas anuais.
INCLUIR_CAMADAS_ANUAIS = False

CULTURAS = [
    "SOJA",
    "MILHO 1ª SAFRA",
    "MILHO 2ª SAFRA",
    "MAÇÃ",
    "UVA",
    "CAFÉ",
]

GPKG_TOTAL = PASTA_VETORES / "psr_grades_2020_2024.gpkg"
GPKG_CULTURA = PASTA_VETORES / "psr_grades_culturas_2020_2024.gpkg"
GPKG_SEM_DOM = PASTA_VETORES / "psr_grades_culturas_sem_dominantes_2020_2024.gpkg"
GPKG_PONTOS = PASTA_VETORES / "psr_pontos_2020_2024.gpkg"

# Opcional. Use None para não carregar a referência municipal.
CAMINHO_MALHA_MUNICIPAL = PASTA_REFERENCIAS / "BR_Municipios_2024.shp"

ARQUIVO_QGZ = PASTA_QGIS / "inteligencia_territorial_psr.qgz"

# =============================================================================
# FUNÇÕES
# =============================================================================

def log(msg):
    print(f"[PSR/QGIS] {msg}")


def gpkg_uri(path, layer_name):
    return f"{path.as_posix()}|layername={layer_name}"


def esc(texto):
    return str(texto).replace("'", "''")


def has_field(layer, field):
    ok = layer.fields().indexOf(field) >= 0
    if not ok:
        campos = ", ".join([f.name() for f in layer.fields()])
        log(f"Campo ausente: {field} | {layer.name()} | Campos disponíveis: {campos}")
    return ok


def localizar_campo(layer, candidatos):
    """Retorna o primeiro campo existente entre possíveis nomes."""
    nomes = {campo.name().lower(): campo.name() for campo in layer.fields()}
    for candidato in candidatos:
        if candidato.lower() in nomes:
            return nomes[candidato.lower()]
    return None


def load_gpkg(path, source_layer, title, subset=""):
    if not path.exists():
        log(f"GeoPackage não encontrado: {path}")
        return None
    lyr = QgsVectorLayer(gpkg_uri(path, source_layer), title, "ogr")
    if not lyr.isValid():
        log(f"Camada inválida/não encontrada: {path.name} > {source_layer}")
        return None
    if subset:
        lyr.setSubsetString(subset)
    return lyr


def style_graduated(layer, field, ramp_name="YlOrRd", n=5):
    """
    Graduação por quantis calculada manualmente.
    Funciona em diferentes versões do QGIS/PyQGIS, sem depender da
    assinatura variável de QgsGraduatedSymbolRenderer.createRenderer().
    """
    if not has_field(layer, field):
        return

    valores = []
    for feat in layer.getFeatures():
        valor = feat[field]
        try:
            if valor is not None:
                valor = float(valor)
                if math.isfinite(valor):
                    valores.append(valor)
        except (TypeError, ValueError):
            pass

    if not valores:
        log(f"Sem valores numéricos válidos para graduação: {layer.name()} > {field}")
        return

    valores.sort()

    def quantil_ordenado(valores_ordenados, q):
        if len(valores_ordenados) == 1:
            return valores_ordenados[0]
        posicao = (len(valores_ordenados) - 1) * q
        baixo = int(math.floor(posicao))
        alto = int(math.ceil(posicao))
        if baixo == alto:
            return valores_ordenados[baixo]
        peso = posicao - baixo
        return (
            valores_ordenados[baixo] * (1 - peso)
            + valores_ordenados[alto] * peso
        )

    limites = [quantil_ordenado(valores, i / n) for i in range(n + 1)]

    # Remove cortes repetidos, comuns quando há muitos zeros.
    limites_unicos = []
    for limite in limites:
        if not limites_unicos or limite > limites_unicos[-1]:
            limites_unicos.append(limite)

    if len(limites_unicos) < 2:
        minimo = valores[0]
        maximo = valores[-1]
        ajuste = abs(maximo) * 0.01 if maximo != 0 else 1
        limites_unicos = [minimo, maximo + ajuste]

    estilo = QgsStyle().defaultStyle()
    rampa = estilo.colorRamp(ramp_name) or estilo.colorRamp("Viridis")
    if rampa is None:
        log(f"Rampa indisponível para {layer.name()}")
        return

    total_classes = len(limites_unicos) - 1
    ranges = []

    for i in range(total_classes):
        inferior = limites_unicos[i]
        superior = limites_unicos[i + 1]
        proporcao = i / max(total_classes - 1, 1)
        cor = rampa.color(proporcao)

        simbolo = QgsSymbol.defaultSymbol(layer.geometryType())
        simbolo.setColor(cor)

        rotulo = f"{inferior:,.0f} – {superior:,.0f}".replace(",", ".")
        ranges.append(QgsRendererRange(inferior, superior, simbolo, rotulo))

    renderer = QgsGraduatedSymbolRenderer(field, ranges)
    renderer.setClassAttribute(field)
    layer.setRenderer(renderer)

def style_categorized(layer, field, max_categories=35):
    if not has_field(layer, field):
        return
    idx = layer.fields().indexOf(field)
    vals = [v for v in layer.uniqueValues(idx) if v is not None and str(v).strip() not in ("", "NULL", "<NULL>")]
    vals = sorted(vals, key=lambda x: str(x))
    if not vals:
        log(f"Sem categorias válidas: {layer.name()} > {field}")
        return
    if len(vals) > max_categories:
        log(f"Categorias demais ({len(vals)}): {layer.name()} > {field}")
        return
    cats = []
    total = len(vals)
    for i, val in enumerate(vals):
        color = QColor.fromHsv(int(i * 360 / total), 165, 225)
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(color)
        cats.append(QgsRendererCategory(val, sym, str(val)))
    layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))


def style_boundary(layer):
    symbol = QgsFillSymbol.createSimple({
        "color": "255,255,255,0",
        "outline_color": "90,90,90,150",
        "outline_width": "0.15",
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setOpacity(0.6)


def add(group, layer, visible=False):
    if layer is None:
        return
    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    node.setItemVisibilityChecked(visible)


def add_culture_layers(group, gpkg, source_layer, period_label, mode):
    """Cria uma camada filtrada por cultura para cada cultura selecionada."""
    configs = {
        "market": ("Prêmio", "premio_liq_rs", "grad", "YlOrRd"),
        "area": ("Área segurada", "area_total_ha", "grad", "YlGn"),
        "leader": ("Seguradora líder", "seguradora_lider", "cat", None),
        "share": ("Share da líder", "share_seguradora_lider_pct", "grad", "PuBuGn"),
        "conc": ("Concentração", "classificacao_concentracao", "cat", None),
        "event": ("Evento líder", "evento_lider", "cat", None),
        "frequency": ("Frequência de indenização", "freq_indenizacao_pct", "grad", "PuRd"),
    }
    suffix, field, renderer, ramp = configs[mode]
    for cultura in CULTURAS:
        subset = f'"cultura" = \'{esc(cultura)}\''
        name = f"{period_label} | {cultura} | {suffix}"
        lyr = load_gpkg(gpkg, source_layer, name, subset)
        if lyr:
            if renderer == "grad":
                style_graduated(lyr, field, ramp)
            else:
                style_categorized(lyr, field)
            add(group, lyr)


def add_cultseg_layers(group, gpkg, source_layer, period_label):
    for cultura in CULTURAS:
        subset = f'"cultura" = \'{esc(cultura)}\''
        name = f"{period_label} | {cultura} | Concorrentes detalhados"
        lyr = load_gpkg(gpkg, source_layer, name, subset)
        if lyr:
            campo_seguradora = localizar_campo(
                lyr,
                [
                    "seguradora",
                    "seguradora_1",
                    "nm_razao_social",
                    "seguradora_lider",
                ],
            )
            if campo_seguradora is None:
                campos = ", ".join([f.name() for f in lyr.fields()])
                log(
                    f"Camada detalhada sem campo de seguradora: {lyr.name()} | "
                    f"Campos disponíveis: {campos}"
                )
            else:
                style_categorized(lyr, campo_seguradora)
            lyr.setOpacity(0.55)
            add(group, lyr)


def create_group(root, name):
    g = root.addGroup(name)
    g.setExpanded(False)
    return g

# =============================================================================
# PROJETO
# =============================================================================

project = QgsProject.instance()
project.clear()
project.setTitle("Inteligência Territorial do Mercado de Seguro Rural | PSR 2020–2024")
project.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))
root = project.layerTreeRoot()

log("Criando projeto QGIS...")

# 00 — Base
g = create_group(root, "00. Base de referência")
if CAMINHO_MALHA_MUNICIPAL and CAMINHO_MALHA_MUNICIPAL.exists():
    municipal = QgsVectorLayer(CAMINHO_MALHA_MUNICIPAL.as_posix(), "Municípios IBGE | referência", "ogr")
    if municipal.isValid():
        style_boundary(municipal)
        add(g, municipal, visible=True)
    else:
        log("Malha municipal inválida.")
else:
    log("Malha municipal não encontrada. Grupo de referência ficará vazio.")

# 01 — Mercado e Exposição
g = create_group(root, "01. Mercado e exposição")
total_layer = f"{PREFIXO_GRADE}_acum_2020_2024"
for title, field, ramp in [
    ("Mercado total | Prêmio líquido", "premio_liq_rs", "YlOrRd"),
    ("Mercado total | Limite de garantia", "limite_garantia_rs", "YlGnBu"),
    ("Mercado total | Nº de registros", "n_registros", "PuBuGn"),
    ("Mercado total | Nº de localizações", "n_localizacoes", "PuBu"),
    ("Mercado total | Recorrência anual", "n_anos", "GnBu"),
]:
    lyr = load_gpkg(GPKG_TOTAL, total_layer, title)
    if lyr:
        style_graduated(lyr, field, ramp)
        add(g, lyr)

# 02 — Culturas
g = create_group(root, "02. Culturas e perfil produtivo")
g1 = g.addGroup("02.1 Mercado por cultura | Prêmio")
add_culture_layers(g1, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "market")
g2 = g.addGroup("02.2 Mercado por cultura | Área segurada")
add_culture_layers(g2, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "area")

# 03 — Competitividade
g = create_group(root, "03. Competitividade e concentração")
g1 = g.addGroup("03.1 Seguradora líder por cultura")
add_culture_layers(g1, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "leader")
g2 = g.addGroup("03.2 Participação da líder por cultura")
add_culture_layers(g2, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "share")
g3 = g.addGroup("03.3 Concentração de mercado por cultura")
add_culture_layers(g3, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "conc")
g4 = g.addGroup("03.4 Concorrentes detalhados por cultura")
add_cultseg_layers(g4, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cultseg", "Acumulado 2020–2024")

# 04 — Sem dominantes
g = create_group(root, "04. Mercado sem seguradoras dominantes")
g1 = g.addGroup("04.1 Nova líder por cultura")
add_culture_layers(g1, GPKG_SEM_DOM, f"{PREFIXO_GRADE}_acum_cult_sem_dom", "Sem dominantes | 2020–2024", "leader")
g2 = g.addGroup("04.2 Concentração recalculada por cultura")
add_culture_layers(g2, GPKG_SEM_DOM, f"{PREFIXO_GRADE}_acum_cult_sem_dom", "Sem dominantes | 2020–2024", "conc")
g3 = g.addGroup("04.3 Concorrentes remanescentes detalhados")
add_cultseg_layers(g3, GPKG_SEM_DOM, f"{PREFIXO_GRADE}_acum_cultseg_sem_dom", "Sem dominantes | 2020–2024")

# 05 — Indenizações
g = create_group(root, "05. Indenizações e eventos")
for title, field, ramp in [
    ("Indenizações registradas | Valor", "indenizacao_rs", "OrRd"),
    ("Indenizações registradas | Frequência", "freq_indenizacao_pct", "PuRd"),
    ("Relação exploratória | Indenização / prêmio", "relacao_indenizacao_premio_pct", "RdPu"),
]:
    lyr = load_gpkg(GPKG_TOTAL, total_layer, title)
    if lyr:
        style_graduated(lyr, field, ramp)
        add(g, lyr)
g1 = g.addGroup("05.1 Evento líder por cultura")
add_culture_layers(g1, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "event")
g2 = g.addGroup("05.2 Frequência de indenização por cultura")
add_culture_layers(g2, GPKG_CULTURA, f"{PREFIXO_GRADE}_acum_cult", "Acumulado 2020–2024", "frequency")

# 06 — Pontos
g = create_group(root, "06. Distribuição espacial dos registros")
for title, source_layer, field in [
    ("Localizações agregadas | Nº de registros", "loc_acum_2020_2024", "n_registros"),
    ("Localizações agregadas | Recorrência anual", "loc_acum_2020_2024", "n_anos"),
    ("Localizações agregadas | Limite de garantia", "loc_acum_2020_2024", "limite_garantia_rs"),
    ("Registros individuais | Ano 2024 | Prêmio", "pt_2024", "premio_liq_rs"),
]:
    lyr = load_gpkg(GPKG_PONTOS, source_layer, title)
    if lyr:
        style_graduated(lyr, field, "Viridis")
        lyr.setOpacity(0.70)
        add(g, lyr)

# 07 — Anual opcional
if INCLUIR_CAMADAS_ANUAIS:
    g = create_group(root, "07. Histórico anual")
    for ano in range(2020, 2025):
        ga = g.addGroup(str(ano))
        lyr = load_gpkg(GPKG_TOTAL, f"{PREFIXO_GRADE}_{ano}", f"{ano} | Mercado total | Prêmio")
        if lyr:
            style_graduated(lyr, "premio_liq_rs", "YlOrRd")
            add(ga, lyr)
        for cultura in CULTURAS:
            subset = f'"cultura" = \'{esc(cultura)}\''
            lyr = load_gpkg(GPKG_CULTURA, f"{PREFIXO_GRADE}_{ano}_cult", f"{ano} | {cultura} | Prêmio", subset)
            if lyr:
                style_graduated(lyr, "premio_liq_rs", "YlOrRd")
                add(ga, lyr)

# Estado final do painel de camadas.
for child in root.children():
    child.setExpanded(False)
root.findGroup("00. Base de referência").setExpanded(True)
root.findGroup("01. Mercado e exposição").setExpanded(True)

ok = project.write(ARQUIVO_QGZ.as_posix())
if not ok:
    raise RuntimeError(f"Não foi possível salvar o projeto: {ARQUIVO_QGZ}")

log("Projeto criado com sucesso.")
log(f"Arquivo: {ARQUIVO_QGZ}")
log("Abra os grupos e ligue uma camada temática por vez para evitar sobreposição.")
