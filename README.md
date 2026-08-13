# EcuabetExtractor

Extractor local de cuotas prematch observadas en la cartelera pública de [Ecuabet](https://ecuabet.com/deportes). Navega con Playwright por CDP sobre la instalación local de Google Chrome, sin proxy, VPN, navegador cloud ni inicio de sesión. Cada comando crea un perfil temporal nuevo y lo elimina al cerrar, por lo que no reutiliza cookies ni tokens. Las cuotas se conservan como cadenas de texto.

## Requisitos y preparación

- Windows con Google Chrome local.
- Python compatible (el entorno creado para este proyecto usa Python 3.12).
- Computador encendido, conectado a Internet y con sesión de Windows activa durante las ejecuciones.

```powershell
& .\.venv\Scripts\Activate.ps1
python -m src.main status
```

Las dependencias están fijadas en `requirements.txt`. No se usa Selenium.

## Comandos

```powershell
python -m src.main discover
python -m src.main extract-next
python -m src.main status
python -m src.main build-pdf
python -m src.main validate
python -m src.main test --matches 5 --after 13:00
python -m src.main run-scheduled
```

Cada comando devuelve `0` al finalizar correctamente y un valor distinto de `0` ante un error.

`discover` solo abre Ecuabet los jueves, viernes y sábados. El objetivo será, respectivamente, viernes, sábado o domingo. Los domingos, lunes, martes y miércoles termina con `NO CORRESPONDE UNA EJECUCIÓN PROGRAMADA` y no abre el sitio.

## Interfaz de ejecución manual

Abra `Abrir_EcuabetExtractor.cmd` con doble clic. La aplicación permite:

- Elegir cualquier fecha, incluso fuera de los días programados.
- Escribir entre 1 y 50 partidos, uno por línea.
- Validar la lista antes de comenzar.
- Ver el progreso, abrir la carpeta de resultados y abrir el último PDF.
- Ejecutar sin modificar la tarea automática de jueves, viernes y sábado.

Formato mínimo:

```text
Real Madrid vs Barcelona
Inter de Milán vs Venezia
```

Formatos opcionales:

```text
20:00 | Real Madrid vs Barcelona
LaLiga | 20:00 | Real Madrid vs Barcelona
```

La interfaz solo puede verificar partidos publicados en la cartelera pública de Ecuabet para la fecha seleccionada. Primero entra en `Deportes`, abre `Fútbol` y expande la cartelera antes de localizar cada partido por equipos y fecha. Si Ecuabet exige iniciar sesión para abrir los mercados detallados, la ejecución se detiene y no genera un PDF vacío. No inventa datos si el nombre no se encuentra. Las ejecuciones manuales se guardan aparte:

- `output/AAAA-MM-DD/Respaldo_Cuotas_Ecuabet_Manual_AAAA-MM-DD.json`
- `output/AAAA-MM-DD/Cuotas_Ecuabet_Manual_AAAA-MM-DD.pdf`

También puede usar PowerShell directamente:

```powershell
.\.venv\Scripts\python.exe -m src.main manual-run --date 2026-08-09 --matches-file .\mis_partidos.txt
.\.venv\Scripts\python.exe -m src.main manual-status
```

Si la consulta terminó pero falló solamente la validación o el guardado final, puede
recuperarse el último resultado sin volver a consultar Ecuabet:

```powershell
.\.venv\Scripts\python.exe -m src.main manual-validate
```

## Producción

La ejecución de producción acepta exclusivamente:

- Premier League de Inglaterra.
- LaLiga de España.
- Serie A de Italia.
- Bundesliga de Alemania.
- Ligue 1 de Francia.

El descubrimiento se persiste en el manifiesto JSON antes de procesar partidos. `extract-next` procesa únicamente el siguiente pendiente y reemplaza el JSON de forma atómica. Un archivo de bloqueo en `work/ecuabet.lock` impide ejecuciones simultáneas.

La tarea de Windows se instala únicamente tras una prueba técnica validada:

```powershell
python -m src.main schedule
```

Nombre: `Cuotas Ecuabet - viernes, sábado y domingo`. Horarios locales: jueves, viernes y sábado a las 15:00. La configuración valida el tiempo mediante `America/Guayaquil`; Windows debe conservar UTC-05:00 sin horario de verano.

## Archivos

- Respaldo: `output/AAAA-MM-DD/Respaldo_Cuotas_Ecuabet_AAAA-MM-DD.json`
- PDF: `output/AAAA-MM-DD/Cuotas_Ecuabet_AAAA-MM-DD.pdf`
- Log estructurado: `logs/Ecuabet_AAAA-MM-DD.log`
- Copia estable para ChatGPT Desktop: `outputs/EcuabetExtractor/`

La copia estable conserva el mismo nombre y se reemplaza atómicamente. Este entorno de Codex no expone una API independiente de “Biblioteca”, por lo que `outputs/EcuabetExtractor/` es el destino local verificable y descargable.

## Estrategia y seguridad

La extracción usa únicamente datos estructurados observados durante la navegación pública actual. Si aparecen Error 1009, acceso denegado, bloqueo regional, CAPTCHA, inicio de sesión obligatorio o una cartelera vacía, la ejecución se detiene. No se pulsan cuotas ni controles de apuestas, y no se registran cookies, tokens ni encabezados privados.

Para cada mercado se abre un único panel, se espera estabilidad, se lee, se valida y se cierra. Los deslizadores se recorren desde el mínimo hasta el máximo, una posición por vez. Solo se deduplican coincidencias idénticas de mercado, línea, selección y cuota.

El PDF se construye exclusivamente desde el JSON, contiene texto y tablas nativas, repite encabezados y añade número de página. La validación comprueba los 12 mercados, recorrido de deslizadores, texto extraíble, ausencia de imágenes, partidos y cuotas.

## Árbitros

Solo se acepta una designación publicada por una liga, federación, comisión arbitral o club que reproduzca una fuente oficial. Cuando no existe una designación comprobable se conserva exactamente el estado no verificable exigido; nunca se infiere un árbitro.
