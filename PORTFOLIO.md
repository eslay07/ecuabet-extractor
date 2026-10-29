# Extractor de datos prematch · lectura de portafolio

Herramienta local de extracción estructurada, checkpoints, validación y generación de reportes PDF.

**Autor:** Jimmy Toapanta · [Perfil profesional](https://www.linkedin.com/in/jimmy-toapanta-950a441b8/) · [Portafolio](https://github.com/eslay07)

**Tecnologías:** Python · Playwright · JSON · ReportLab · pruebas automatizadas

## Problema y solución

Una extracción reproducible necesita controlar qué se visitó, conservar el dato original y detectar resultados incompletos.

Separa descubrimiento, extracción, persistencia del avance, validación y construcción del informe; utiliza Chrome local mediante CDP.

## Evidencia para revisar el trabajo

| Archivo o componente | Qué permite revisar |
| --- | --- |
| [src/main.py](src/main.py) | Comandos de la herramienta. |
| [src/checkpoint.py](src/checkpoint.py) | Conservación del avance. |
| [src/extractor.py](src/extractor.py) | Extracción de la información. |
| [src/validator.py](src/validator.py) | Comprobaciones del resultado. |
| [tests/test_checkpoint.py](tests/test_checkpoint.py) | Pruebas del estado. |

## Estado y límites

Proyecto específico de un sitio externo: su funcionamiento depende de la estructura y condiciones de acceso de ese sitio. Es una herramienta de datos, no una garantía de rentabilidad.

## Cómo evaluar el proyecto

Revisar las pruebas locales y la validación sin iniciar una sesión ni realizar apuestas. No se ejecutó extracción contra el sitio durante esta revisión.

Esta actualización documental se basa en la revisión del código y de la documentación disponibles. No añade métricas de ahorro, clientes, usuarios ni resultados de producción que no estén respaldados.

## Capacidad que demuestra

Diseñar un pipeline de adquisición y validar la calidad del resultado antes de generar un informe.

[Volver al README](README.md).
