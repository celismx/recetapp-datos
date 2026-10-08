"""
RecetApp · scraper de precios de medicamentos en farmacias de Colombia.

Consulta el catálogo público (VTEX) de cada farmacia, respeta robots.txt,
va despacio (una consulta cada 1,5 s) y guarda un CSV con un producto por fila.

Uso:
    python scraper/scrape.py                 # escribe data/precios.csv y data/meta.json
    python scraper/scrape.py --limite 3      # prueba rápida con 3 términos

Solo usa la biblioteca estándar de Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LISTA = RAIZ / "scraper" / "medicamentos.csv"
SALIDA = RAIZ / "data" / "precios.csv"
META = RAIZ / "data" / "meta.json"

USER_AGENT = "RecetAppBot/1.0 (proyecto educativo de Gradiente Escuela de Ingenieria)"
PAUSA_SEG = 1.5
RESULTADOS_POR_TERMINO = 50  # VTEX permite hasta 50 por página (_from=0&_to=49)

# Farmacias con catálogo VTEX público y robots.txt que permite la ruta de búsqueda
# (verificado el 7 oct 2026). El script vuelve a revisar robots.txt en cada corrida.
FARMACIAS = [
    {"nombre": "La Rebaja", "base": "https://www.larebajavirtual.com"},
    {"nombre": "Locatel", "base": "https://www.locatelcolombia.com"},
    {"nombre": "Olímpica", "base": "https://www.olimpica.com"},
]

COLUMNAS = [
    "fecha", "farmacia", "principio_activo", "concentracion", "producto", "marca",
    "presentacion", "unidades", "precio", "precio_lista", "precio_unidad", "url",
]

RE_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(MG|MCG|G|UI)(?![A-Z])", re.IGNORECASE
)
RE_UNIDADES = re.compile(
    r"\bX\s*(\d{1,3})\s*(?:UND|UNDS|UNIDADES|TAB|TABS|TABLETAS|CAP|CAPS|CAPSULAS|"
    r"GRAG|GRAGEAS|COMP|COMPRIMIDOS|SOBRES|SOB)?\b",
    re.IGNORECASE,
)
RE_COMBINACION = re.compile(r"\+|/\s*\d|[A-Z]\s*/\s*[A-Z]{3}")  # "ACETAMINOFEN + CODEINA", "500/65MG"
# Variantes de marca que mezclan sustancias aunque el nombre no lo diga (Dolex Gripa, Losartán HCT...)
RE_EXCLUIR = re.compile(r"\b(GRIPA|PLUS|FORTE|DUO|COMPUESTO|HCT|CODEINA|D)\b")
# La etiqueta "Principio activo" de la tienda trae a veces la sal ("LOSARTAN POTASICO": vale) y a veces
# una combinación ("LOSARTAN, HIDROCLOROTIAZIDA", "Losartan-Hidroclorotiazida", "LOSARTAN + AMLODIPINO": no).
RE_SPEC_COMBINACION = re.compile(r"[,+/\-]|\bY\b|\bCON\b")
# El MVP compara solo formas sólidas (tabletas, cápsulas): un jarabe por ml no se compara con una tableta.
RE_NO_SOLIDO = re.compile(
    r"\d\s*ML\b|\bML\b|JARABE|GOTAS|SUSPENSION|SOLUCION|CREMA|\bGEL\b|UNGUENTO|INYECTABLE|"
    r"AMPOLLA|SPRAY|INHALADOR|POLVO|SOBRES?\b|EFERVESCENTE|PARCHE"
)


# ---------------------------------------------------------------- utilidades

def normalizar(texto: str) -> str:
    """Mayúsculas, sin tildes y con espacios simples."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes).strip().upper()


def extraer_concentracion(texto: str) -> str:
    m = RE_CONCENTRACION.search(texto or "")
    if not m:
        return ""
    numero = m.group(1).replace(",", ".")
    if numero.endswith(".0"):
        numero = numero[:-2]
    return f"{numero} {m.group(2).upper()}"


def extraer_unidades(*textos: str) -> int | None:
    for texto in textos:
        m = RE_UNIDADES.search(texto or "")
        if m:
            n = int(m.group(1))
            if 0 < n <= 500:
                return n
    return None


def especificacion(producto: dict, nombre: str) -> str:
    """Las especificaciones VTEX llegan como lista: {"Principio activo": ["LOSARTAN"]}."""
    for clave, valor in producto.items():
        if normalizar(clave) == normalizar(nombre):
            if isinstance(valor, list):
                return " ".join(str(v) for v in valor)
            return str(valor)
    return ""


# ---------------------------------------------------------------- red

_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def permitido(url: str) -> bool:
    partes = urllib.parse.urlsplit(url)
    base = f"{partes.scheme}://{partes.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:  # sin robots.txt legible: no seguimos
            rp.disallow_all = True
        _robots[base] = rp
    return _robots[base].can_fetch(USER_AGENT, url)


def obtener_json(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def buscar(base: str, termino: str) -> list:
    ft = urllib.parse.quote(termino)  # VTEX espera %20 para los espacios, no "+"
    url = f"{base}/api/catalog_system/pub/products/search?ft={ft}&_from=0&_to={RESULTADOS_POR_TERMINO - 1}"
    if not permitido(url):
        print(f"  robots.txt no permite {base}; se omite", file=sys.stderr)
        return []
    datos = None
    for intento in range(2):  # un reintento si la tienda responde con error
        try:
            datos = obtener_json(url)
            break
        except Exception as error:
            print(f"  error en {url} (intento {intento + 1}): {error}", file=sys.stderr)
        finally:
            time.sleep(PAUSA_SEG * (intento + 1))
    return datos if isinstance(datos, list) else []


# ---------------------------------------------------------------- parseo

def filas_de_producto(producto: dict, farmacia: str, termino: str, principio: str, hoy: str,
                      nombres: set[str] | None = None) -> list[dict]:
    """Convierte un producto VTEX en una fila por SKU (caja, blíster, etc.)."""
    nombre = producto.get("productName", "")
    nombre_n = normalizar(nombre)
    principio_spec = normalizar(especificacion(producto, "Principio activo"))

    # 1) Que el producto sea de verdad el medicamento buscado: su nombre debe incluir el principio
    #    activo o una marca conocida de ese principio. La etiqueta de la tienda sola no basta
    #    (hay productos mal etiquetados, p. ej. ASA marcado como acetaminofén).
    validos = {normalizar(termino), principio} | (nombres or set())
    if not any(re.search(rf"\b{re.escape(v)}\b", nombre_n) for v in validos):
        return []
    # 2) Fuera combinaciones (p. ej. acetaminofén + codeína): el MVP compara una sola sustancia.
    if principio_spec and (RE_SPEC_COMBINACION.search(principio_spec)
                           or not re.search(rf"\b{re.escape(principio)}\b", principio_spec)):
        return []
    if RE_COMBINACION.search(nombre_n) or RE_EXCLUIR.search(nombre_n):
        return []

    presentacion_spec = especificacion(producto, "Presentacionunidadmedida")
    if RE_NO_SOLIDO.search(nombre_n) or RE_NO_SOLIDO.search(normalizar(presentacion_spec)):
        return []
    filas = []
    for item in producto.get("items", []):
        if item.get("isKit"):
            continue
        sellers = item.get("sellers") or []
        if not sellers:
            continue
        oferta = sellers[0].get("commertialOffer") or {}
        precio = oferta.get("Price") or 0
        if not oferta.get("IsAvailable", True) or precio <= 0:
            continue
        nombre_item = item.get("nameComplete") or item.get("name") or ""
        # Olímpica pega al nombre del SKU una segunda descripción que puede revelar una combinación
        # ("... LOSARTAN HCT 50/12.5 MG ...") o una forma no sólida que el nombre del producto no dice.
        item_n = normalizar(nombre_item)
        if RE_COMBINACION.search(item_n) or RE_EXCLUIR.search(item_n) or RE_NO_SOLIDO.search(item_n):
            continue
        concentracion = extraer_concentracion(nombre) or extraer_concentracion(nombre_item)
        if not concentracion:
            continue
        unidades = extraer_unidades(nombre_item, presentacion_spec, nombre)
        presentacion = presentacion_spec or nombre_item
        filas.append({
            "fecha": hoy,
            "farmacia": farmacia,
            "principio_activo": principio,
            "concentracion": concentracion,
            "producto": nombre.strip(),
            "marca": (producto.get("brand") or "").strip(),
            "presentacion": normalizar(presentacion),
            "unidades": unidades or "",
            "precio": round(precio),
            "precio_lista": round(oferta.get("ListPrice") or precio),
            "precio_unidad": round(precio / unidades, 2) if unidades else "",
            "url": producto.get("link", ""),
        })
    return filas


# ---------------------------------------------------------------- principal

def leer_lista(limite: int | None) -> list[dict]:
    with LISTA.open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    return filas[:limite] if limite else filas


def main() -> int:
    parser = argparse.ArgumentParser(description="Scraper de precios de RecetApp")
    parser.add_argument("--limite", type=int, help="usar solo los primeros N términos")
    args = parser.parse_args()

    hoy = date.today().isoformat()
    lista = leer_lista(args.limite)
    nombres_por_principio: dict[str, set[str]] = {}
    for med in leer_lista(None):
        nombres_por_principio.setdefault(normalizar(med["principio_activo"]), set()).add(normalizar(med["termino"]))
    vistos: set[tuple] = set()
    filas: list[dict] = []

    for farmacia in FARMACIAS:
        print(f"== {farmacia['nombre']}")
        for med in lista:
            termino, principio = med["termino"], normalizar(med["principio_activo"])
            productos = buscar(farmacia["base"], termino)
            nuevas = 0
            for producto in productos:
                for fila in filas_de_producto(producto, farmacia["nombre"], termino, principio, hoy,
                                              nombres_por_principio.get(principio)):
                    clave = (fila["farmacia"], fila["producto"], fila["presentacion"], fila["precio"])
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    filas.append(fila)
                    nuevas += 1
            print(f"  {termino}: {len(productos)} resultados, {nuevas} filas")

    filas.sort(key=lambda f: (f["principio_activo"], f["concentracion"], f["farmacia"], f["precio"]))
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with SALIDA.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)

    meta = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filas": len(filas),
        "farmacias": sorted({f["farmacia"] for f in filas}),
        "principios_activos": len({f["principio_activo"] for f in filas}),
        "filas_con_precio_unidad": sum(1 for f in filas if f["precio_unidad"] != ""),
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0 if filas else 1


if __name__ == "__main__":
    sys.exit(main())
