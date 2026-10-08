# recetapp-datos

Precios de medicamentos de farmacias en línea de Colombia para **RecetApp**, el proyecto de la clase *Introducción a Claude Code* de Gradiente.

- `data/precios.csv`: un producto por fila (farmacia, principio activo, concentración, presentación, precio y precio por unidad).
- `data/meta.json`: fecha de actualización y conteos.
- `scraper/scrape.py`: el script que genera los datos. Solo biblioteca estándar de Python.
- `scraper/medicamentos.csv`: la lista de medicamentos que se consultan (nombre genérico y de marca).

## Cómo se obtienen los datos

El script consulta el buscador público del catálogo de cada farmacia, revisa `robots.txt` antes de cada consulta, se identifica con un User-Agent propio y espera 1,5 segundos entre consultas. No usa cuentas, no pasa captchas y no guarda datos personales.

Fuentes: La Rebaja Virtual, Locatel Colombia y Olímpica.

## Correrlo

```bash
python scraper/scrape.py            # todo
python scraper/scrape.py --limite 3 # prueba rápida
```

## Aviso

Los precios son una foto del día en que se corrió el script y pueden cambiar. RecetApp compara precios; no reemplaza la indicación de un médico o farmacéutico.
