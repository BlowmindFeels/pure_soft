# Sistema "pure_soft"


Aplicación para registrar aire contaminado, simular su purificación, validar el resultado
y ver indicadores. Hecha con la tecnología más simple posible:

| Parte | Tecnología | Por qué |
|---|---|---|
| Servidor y cálculos | Python (solo librería estándar) | No hay que instalar nada |
| Base de datos | SQLite (viene con Python, archivo `aire.db`) | No requiere servidor MySQL/PostgreSQL |
| Interfaz y gráficos | HTML + JavaScript puro (gráficos SVG propios) | Sin React, sin Node, sin internet |

## Cómo ejecutarlo
1. Instale Python 3.8 o superior (https://www.python.org).
2. Descomprima el ZIP.
3. Ejecute:
   - Windows: doble clic en `iniciar.bat`
   - Linux/Mac: `sh iniciar.sh`
   - o en cualquier sistema: `python app.py`
4. Se abre el navegador en http://localhost:8000 (si no, ábralo a mano).

La primera vez, en **Monitoreo** pulse **Cargar datos de ejemplo** para ver el dashboard lleno.

## Flujo de uso
1. **Monitoreo**: registre PM2.5, PM10, CO₂ y CO (o use «Simular sensores»). Se guarda fecha y hora y se clasifica el nivel.
2. **Purificación**: elija un ingreso pendiente, el filtro (se sugiere uno según los contaminantes) y los minutos. Se guardan los valores minuto a minuto.
3. **Validación**: compara inicial vs. final, % de reducción por contaminante y clasifica el resultado.
4. **Dashboard**: 6 indicadores, 4 gráficos y alertas.
5. **Reportes**: análisis de resultados automático, eficiencia por filtro, tabla detallada, CSV para Excel e impresión a PDF.

## Reglas usadas

**Nivel de contaminación** (el del contaminante más alto define el nivel general):

| | Bajo | Moderado | Alto | Crítico |
|---|---|---|---|---|
| PM2.5 (µg/m³) | ≤ 12 | ≤ 35 | ≤ 55 | > 55 |
| PM10 (µg/m³) | ≤ 54 | ≤ 154 | ≤ 254 | > 254 |
| CO₂ (ppm) | ≤ 800 | ≤ 1000 | ≤ 2000 | > 2000 |
| CO (ppm) | ≤ 4 | ≤ 9 | ≤ 35 | > 35 |

**Filtros simulados** (eficiencia máxima por contaminante):

| Filtro | PM2.5 | PM10 | CO₂ | CO |
|---|---|---|---|---|
| HEPA | 97 % | 98 % | 0 % | 0 % |
| Carbón activado | 25 % | 30 % | 10 % | 15 % |
| HEPA + Carbón activado | 98 % | 99 % | 10 % | 15 % |
| Sistema completo (HEPA + carbón + catalizador/absorbente) | 98 % | 99 % | 45 % | 80 % |

Estos porcentajes son valores de simulación (no mediciones reales). Reflejan la idea de la nota técnica:
HEPA captura partículas, el carbón activado adsorbe algunos gases y ninguna tecnología elimina todo.
Durante el proceso el valor baja con una curva exponencial hasta ~95 % de la eficiencia máxima al terminar el tiempo.

**Clasificación del resultado** (eficiencia = promedio de reducción de los contaminantes que estaban por encima de «Bajo»):
Excelente ≥ 90 % · Bueno ≥ 70 % · Regular ≥ 40 % · Deficiente < 40 %.

## Archivos
- `app.py` – servidor, base de datos, simulación y cálculos
- `index.html` – interfaz completa (módulos 1 a 4 y reportes)
- `aire.db` – se crea sola al primer arranque (tablas `procesos` y `lecturas`)

Para empezar de cero, cierre el programa y borre `aire.db`.

## Conectar sensores reales (opcional)
El servidor ya expone `POST /api/procesos` con JSON `{"pm25":..,"pm10":..,"co2":..,"co":..}`;
un Arduino/Raspberry Pi puede enviar las mediciones a esa dirección.
