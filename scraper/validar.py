"""
RecetApp · valida data/precios.csv antes de publicarlo.

Uso: python scraper/validar.py
Sale con código 1 si alguna regla falla. Al final imprime los mejores ejemplos de ahorro para la clase.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CSV = Path(__file__).resolve().parent.parent / "data" / "precios.csv"
COMBINACIONES = re.compile(r"\+|GRIPA|\bHCT\b|CODEINA", re.IGNORECASE)


def main() -> int:
    filas = list(csv.DictReader(CSV.open(encoding="utf-8")))
    farmacias = Counter(f["farmacia"] for f in filas)
    principios = {f["principio_activo"] for f in filas}
    con_pu = [f for f in filas if f["precio_unidad"]]
    precios = [float(f["precio"]) for f in filas]

    grupos: dict[tuple, list] = defaultdict(list)
    for f in con_pu:
        grupos[(f["principio_activo"], f["concentracion"])].append(f)
    ejemplos = []
    for clave, lista in grupos.items():
        if len({f["marca"] for f in lista}) < 2:
            continue
        barato = min(lista, key=lambda f: float(f["precio_unidad"]))
        caro = max(lista, key=lambda f: float(f["precio_unidad"]))
        extra = float(caro["precio_unidad"]) / float(barato["precio_unidad"]) - 1
        ejemplos.append((extra, clave, barato, caro))
    ejemplos.sort(key=lambda e: e[0], reverse=True)

    reglas = [
        ("Al menos 2 farmacias", len(farmacias) >= 2, dict(farmacias)),
        ("Al menos 20 principios activos", len(principios) >= 20, len(principios)),
        ("60 % o más de filas con precio por unidad", len(con_pu) >= 0.6 * len(filas), f"{len(con_pu)}/{len(filas)}"),
        ("Precios entre $500 y $2.000.000", min(precios) >= 500 and max(precios) <= 2_000_000, f"{min(precios):.0f}–{max(precios):.0f}"),
        ("Sin combinaciones de sustancias", not any(COMBINACIONES.search(f["producto"]) for f in filas), ""),
        ("5 o más grupos con 30 % de diferencia", sum(1 for e in ejemplos if e[0] >= 0.3) >= 5, sum(1 for e in ejemplos if e[0] >= 0.3)),
    ]
    ok = True
    for nombre, paso, detalle in reglas:
        ok &= paso
        print(f"{'OK   ' if paso else 'FALLA'} {nombre}: {detalle}")

    print("\nMejores ejemplos de ahorro (por unidad):")
    for extra, (principio, conc), barato, caro in ejemplos[:8]:
        ahorro = 1 - float(barato["precio_unidad"]) / float(caro["precio_unidad"])
        print(f"- {principio} {conc}: {caro['producto']} ({caro['farmacia']}, ${float(caro['precio_unidad']):,.0f} c/u)"
              f" → {barato['producto']} ({barato['farmacia']}, ${float(barato['precio_unidad']):,.0f} c/u): ahorras {ahorro:.0%}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
