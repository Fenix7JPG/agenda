"""Genera el PDF del horario en una lámina grande, estilo infografía.

No usa A4: el tamaño de la hoja se calcula para que cada día tenga una
columna cómoda (150 pt) y cada hora una altura generosa (72 pt), con letra
de 12 pt para los títulos. El ancho crece con el número de días del rango
visible, y todo queda siempre en una única página vectorial.

El título de cada actividad se dibuja siempre completo y dentro de su
bloque: la altura de 72 pt por hora deja sitio de sobra para títulos largos
en mayúsculas incluso en bloques de 45 minutos. Como red de seguridad para
casos extremos (bloques de minutos con títulos muy largos), si el texto no
cabe las líneas se dibujan igual saliéndose del bloque hacia abajo, y para
que un texto derramado no quede tapado primero se dibujan todos los cuadros
y después todos los textos.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO

from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas

from . import horario_service

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# Colores de prioridad, los mismos del calendario web (static/styles.css)
COLORES_PRIORIDAD = {
    1: colors.HexColor("#D93025"),  # rojo
    2: colors.HexColor("#E37400"),  # naranja
    3: colors.HexColor("#1A73E8"),  # azul
    4: colors.HexColor("#188038"),  # verde
    5: colors.HexColor("#8E24AA"),  # morado
}
COLOR_PRIORIDAD_OTRA = colors.HexColor("#5F6368")

COLOR_BANDA = colors.HexColor("#1F4E79")
COLOR_TEXTO_BANDA = colors.white
COLOR_TEXTO = colors.HexColor("#202124")
COLOR_GRIS = colors.HexColor("#5F6368")
COLOR_LINEA = colors.HexColor("#E8EAED")
COLOR_BORDE = colors.HexColor("#DADCE0")
COLOR_CAB_DIA = colors.HexColor("#F1F3F4")
COLOR_HOY = colors.HexColor("#1A73E8")
COLOR_BLOQUE_HECHO = colors.HexColor("#9AA0A6")
COLOR_TRAZO_FIJADO = colors.HexColor("#1F4E79")

MAX_DIAS = 28

# Lámina grande (infografía): medidas fijas cómodas de leer
MARGEN = {"izq": 30.0, "der": 30.0, "sup": 34.0, "inf": 34.0}
ANCHO_HORA = 52.0
ANCHO_COL_DIA = 150.0
ALTO_HORA = 72.0
ALTO_BANDA = 60.0
ALTO_CAB_DIA = 34.0
HUECO_CAB = 10.0
TAM_TITULO = 12.0
TAM_HORA = 9.0


def _fecha(texto: str | None, nombre: str) -> date:
    """Acepta 'AAAA-MM-DD' y también 'AAAA-MM-DD HH:MM:SS' (frontend)."""
    if not texto:
        raise ValueError(f"Falta la fecha {nombre}")
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(texto).date()
        except (TypeError, ValueError):
            raise ValueError(f"La fecha {nombre} no es válida (se espera AAAA-MM-DD)")


def _validar_rango(inicio: str | None, fin: str | None) -> tuple[date, date]:
    """Valida el rango: `fin` es exclusivo, como lo envía el frontend."""
    a = _fecha(inicio, "de inicio")
    b = _fecha(fin, "final")
    if b <= a:
        raise ValueError("La fecha final debe ser posterior a la de inicio")
    if (b - a).days > MAX_DIAS:
        raise ValueError(f"El rango máximo es de {MAX_DIAS} días")
    return a, b


def _eventos_por_dia(
    bloques: list[dict], inicio: date, fin: date
) -> dict[date, list[dict]]:
    """Parte los bloques que cruzan medianoche y agrupa por día.

    Cada evento queda como {titulo, inicio_min, fin_min, prioridad,
    completado, fijado} con minutos locales de 0 a 1440.
    """
    dias = [inicio + timedelta(days=i) for i in range((fin - inicio).days)]
    mapa: dict[date, list[dict]] = {d: [] for d in dias}

    def agregar(dia: date, bloque: dict, ini: datetime, fin: datetime) -> None:
        if fin <= ini:
            return
        ini_min = ini.hour * 60 + ini.minute
        fin_min = fin.hour * 60 + fin.minute
        if fin_min == 0:
            fin_min = 1440
        mapa[dia].append(
            {
                "titulo": bloque["titulo"],
                "inicio_min": ini_min,
                "fin_min": fin_min,
                "prioridad": bloque.get("prioridad"),
                "completado": bool(bloque.get("completado")),
                "fijado": bool(bloque.get("fijado")),
            }
        )

    for bloque in bloques:
        ini = datetime.strptime(bloque["inicio"], "%Y-%m-%d %H:%M:%S")
        fin = datetime.strptime(bloque["fin"], "%Y-%m-%d %H:%M:%S")
        cursor = ini
        while cursor.date() < fin.date():
            siguiente = datetime.combine(
                cursor.date() + timedelta(days=1), datetime.min.time()
            )
            if cursor.date() in mapa:
                agregar(cursor.date(), bloque, cursor, siguiente)
            cursor = siguiente
        if cursor.date() in mapa:
            agregar(cursor.date(), bloque, cursor, fin)

    return mapa


def _carriles(eventos: list[dict]) -> list[list[dict]]:
    """Carriles para eventos que se solapan el mismo día."""
    ordenados = sorted(eventos, key=lambda e: e["inicio_min"])
    carriles: list[list[dict]] = []
    fin_carril: list[int] = []
    for evento in ordenados:
        colocado = False
        for i, fin in enumerate(fin_carril):
            if evento["inicio_min"] >= fin:
                carriles[i].append(evento)
                fin_carril[i] = evento["fin_min"]
                colocado = True
                break
        if not colocado:
            carriles.append([evento])
            fin_carril.append(evento["fin_min"])
    return carriles


def _envolver(texto: str, fuente: str, tamano: float, ancho: float) -> list[str]:
    """Parte un texto en líneas que caben en `ancho` puntos."""
    lineas: list[str] = []
    for palabra in texto.split():
        while stringWidth(palabra, fuente, tamano) > ancho:
            corte = len(palabra)
            while corte > 1 and stringWidth(palabra[:corte], fuente, tamano) > ancho:
                corte -= 1
            lineas.append(palabra[:corte])
            palabra = palabra[corte:]
        if not lineas or (
            stringWidth(lineas[-1] + " " + palabra, fuente, tamano) > ancho
        ):
            lineas.append(palabra)
        else:
            lineas[-1] += " " + palabra
    return lineas


def _rango_legible(inicio: date, fin: date) -> str:
    """'del lunes 17/08/2026 al domingo 23/08/2026'."""
    def uno(dia: date) -> str:
        return f"{DIAS_SEMANA[dia.weekday()]} {dia.strftime('%d/%m/%Y')}"

    if (fin - inicio).days == 1:
        return uno(inicio)
    return f"del {uno(inicio)} al {uno(fin - timedelta(days=1))}"


def generar_pdf(inicio: str | None, fin: str | None) -> bytes:
    """Devuelve los bytes del PDF (una sola lámina grande, tamaño infografía)."""
    a, b = _validar_rango(inicio, fin)
    bloques = horario_service.listar_bloques(inicio, fin)
    dias = [a + timedelta(days=i) for i in range((b - a).days)]
    mapa = _eventos_por_dia(bloques, a, b)
    num_dias = len(dias)
    hoy = date.today()

    # Tamaño de la hoja: crece con los días, como una infografía
    ancho = MARGEN["izq"] + MARGEN["der"] + ANCHO_HORA + num_dias * ANCHO_COL_DIA
    alto = (
        MARGEN["sup"] + ALTO_BANDA + HUECO_CAB + ALTO_CAB_DIA
        + 24 * ALTO_HORA + MARGEN["inf"]
    )

    x0 = MARGEN["izq"]
    y_banda = alto - MARGEN["sup"]
    y_cab = y_banda - ALTO_BANDA - HUECO_CAB
    y_grid = y_cab - ALTO_CAB_DIA
    y_piso = MARGEN["inf"] + 8.0
    alto_hora = (y_grid - y_piso) / 24.0
    ancho_dia = ANCHO_COL_DIA

    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(ancho, alto))
    c.setTitle(f"Horario {a.strftime('%d/%m/%Y')} al {(b - timedelta(days=1)).strftime('%d/%m/%Y')}")
    c.setAuthor("Gestor de Tareas")

    # -------- Banda de título --------
    c.setFillColor(COLOR_BANDA)
    c.rect(0, y_banda - ALTO_BANDA, ancho, ALTO_BANDA, stroke=0, fill=1)
    c.setFillColor(COLOR_TEXTO_BANDA)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(ancho / 2, y_banda - 28, "HORARIO GENERADO")
    c.setFont("Helvetica", 11)
    c.drawCentredString(
        ancho / 2,
        y_banda - 47,
        f"{_rango_legible(a, b)}  ·  generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}",
    )

    # -------- Cabeceras de días --------
    for i, dia in enumerate(dias):
        col_x = x0 + ANCHO_HORA + i * ancho_dia
        es_hoy = dia == hoy
        c.setFillColor(COLOR_HOY if es_hoy else COLOR_CAB_DIA)
        c.rect(col_x, y_cab - ALTO_CAB_DIA, ancho_dia, ALTO_CAB_DIA, stroke=0, fill=1)
        c.setFillColor(colors.white if es_hoy else COLOR_TEXTO)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(
            col_x + ancho_dia / 2, y_cab - 12, DIAS_SEMANA[dia.weekday()].capitalize()
        )
        c.setFont("Helvetica", 9.5)
        c.setFillColor(colors.white if es_hoy else COLOR_GRIS)
        c.drawCentredString(col_x + ancho_dia / 2, y_cab - 25, dia.strftime("%d/%m"))

    # -------- Rejilla y columna de horas --------
    c.setStrokeColor(COLOR_BORDE)
    c.setLineWidth(0.8)
    c.rect(x0, y_piso, ANCHO_HORA + num_dias * ancho_dia, y_grid - y_piso, stroke=1, fill=0)
    c.setFillColor(COLOR_GRIS)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x0 + ANCHO_HORA / 2, y_cab - 20, "HORA")
    c.setFont("Helvetica", 9)
    for hora in range(24):
        y_linea = y_grid - hora * alto_hora
        c.setStrokeColor(COLOR_LINEA)
        c.setLineWidth(0.5)
        c.line(x0 + ANCHO_HORA, y_linea, x0 + ANCHO_HORA + num_dias * ancho_dia, y_linea)
        c.setFillColor(COLOR_GRIS)
        c.drawRightString(
            x0 + ANCHO_HORA - 6, y_linea - alto_hora / 2 + 3, f"{hora:02d}:00"
        )
    for i in range(1, num_dias):
        col_x = x0 + ANCHO_HORA + i * ancho_dia
        c.setStrokeColor(COLOR_BORDE)
        c.setLineWidth(0.5)
        c.line(col_x, y_piso, col_x, y_grid)

    # -------- Bloques: primero todos los cuadros, luego todos los textos --------
    piezas: list[tuple[dict, float, float]] = []
    for i, dia in enumerate(dias):
        carriles = _carriles(mapa[dia])
        n_carriles = max(len(carriles), 1)
        for idx, carril in enumerate(carriles):
            for evento in carril:
                piezas.append(
                    (
                        evento,
                        x0 + ANCHO_HORA + i * ancho_dia + idx * (ancho_dia / n_carriles),
                        ancho_dia / n_carriles,
                    )
                )

    for evento, col_x, ancho_bloque in piezas:
        _rect_bloque(c, evento, col_x, ancho_bloque, y_grid, alto_hora)
    for evento, col_x, ancho_bloque in piezas:
        _texto_bloque(c, evento, col_x, ancho_bloque, y_grid, alto_hora)

    if not piezas:
        c.setFillColor(COLOR_GRIS)
        c.setFont("Helvetica", 16)
        c.drawCentredString(ancho / 2, (y_grid + y_piso) / 2, "Sin actividades en este rango")

    c.showPage()
    c.save()
    return buf.getvalue()


def _geometria(evento, y_grid, alto_hora):
    alto_bloque = max((evento["fin_min"] - evento["inicio_min"]) / 60.0 * alto_hora, 2.5)
    y_tope = y_grid - evento["inicio_min"] / 60.0 * alto_hora
    y_base = y_tope - alto_bloque
    return alto_bloque, y_tope, y_base


def _relleno(evento):
    if evento["completado"]:
        return COLOR_BLOQUE_HECHO
    return COLORES_PRIORIDAD.get(evento["prioridad"], COLOR_PRIORIDAD_OTRA)


def _rect_bloque(c, evento, col_x, ancho_bloque, y_grid, alto_hora) -> None:
    alto_bloque, _y_tope, y_base = _geometria(evento, y_grid, alto_hora)
    c.setFillColor(_relleno(evento))
    c.roundRect(col_x + 1.5, y_base, ancho_bloque - 3, alto_bloque, 2.5, stroke=0, fill=1)
    if evento["fijado"]:
        c.setStrokeColor(COLOR_TRAZO_FIJADO)
        c.setLineWidth(1.2)
        c.roundRect(col_x + 1.5, y_base, ancho_bloque - 3, alto_bloque, 2.5, stroke=1, fill=0)


def _texto_bloque(c, evento, col_x, ancho_bloque, y_grid, alto_hora) -> None:
    alto_bloque, y_tope, _y_base = _geometria(evento, y_grid, alto_hora)

    ancho_texto = ancho_bloque - 9
    lineas = _envolver(evento["titulo"], "Helvetica-Bold", TAM_TITULO, ancho_texto)
    hora_texto = (
        f"{evento['inicio_min'] // 60:02d}:{evento['inicio_min'] % 60:02d}"
        f" a {evento['fin_min'] // 60:02d}:{evento['fin_min'] % 60:02d}"
    )

    interlinea = 1.2 * TAM_TITULO
    alto_util = alto_bloque - 3
    filas = [(linea, "Helvetica-Bold", TAM_TITULO) for linea in lineas]
    if alto_util >= (len(lineas) + 1) * interlinea:
        filas.append((hora_texto, "Helvetica", TAM_HORA))
    else:
        # Sin sitio para una línea aparte: se añade al final del título si cabe.
        ultima = lineas[-1] if lineas else ""
        con_hora = f"{ultima}  {hora_texto}"
        if lineas and stringWidth(con_hora, "Helvetica-Bold", TAM_TITULO) <= ancho_texto:
            filas[-1] = (con_hora, "Helvetica-Bold", TAM_TITULO)
    if not filas:
        filas = [(hora_texto, "Helvetica", TAM_HORA)]

    c.setFillColor(colors.white)
    for idx, (linea, fuente, tam) in enumerate(filas):
        c.setFont(fuente, tam)
        c.drawString(col_x + 4.5, y_tope - 3 - interlinea * (idx + 1) + 1.5, linea)

    if evento["completado"] and filas:
        c.setStrokeColor(colors.white)
        c.setLineWidth(0.8)
        y_medio = y_tope - 3 - interlinea * len(filas) / 2 + 1.5
        c.line(col_x + 4.5, y_medio, col_x + 4.5 + ancho_texto, y_medio)
