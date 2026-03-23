## Precheck de DTE en XML

Herramienta en Python para **validar y autocorregir (en casos seguros)** XML de DTE (Documentos Tributarios Electrónicos) antes de que sean procesados por otros sistemas (por ejemplo QaD).  
Supervisa una carpeta de entrada, aplica un conjunto de reglas configurables y clasifica los archivos en **OK** o **ERROR**, generando reportes de diagnóstico y, cuando es posible, una versión corregida del XML.

### Características principales

- **Watcher de carpeta**: usa `watchdog` para detectar nuevos/actualizados XML en la carpeta de entrada.
- **Motor de reglas plugin** (`rules/`):
  - `rule_schema_basico`: chequeos lógicos básicos (bloque `Chofer`, `Referencia`, etc.).
  - `rule_schema_cdgitem`: valida que `CdgItem` tenga `VlrCodigo`.
  - `rule_cantidad`: valida que campos de cantidad sean numéricos y mayores a un mínimo.
  - `rule_moneda`: valida formato de moneda (3 letras) y lista de monedas permitidas.
  - `rule_rut`: valida RUT chilenos con algoritmo de módulo 11.
  - `rule_sanitize_ampersand`: sanea `&` mal escapados antes de parsear.
- **Autofix** (`autofix.py`):
  - Normaliza monedas (ej. "DÓLAR USA" → "USD" si está permitido).
  - Normaliza cantidades (separadores de miles/decimales comunes).
  - Normaliza formato de RUT (puntos, espacios, guion).
- **Reportes legibles**:
  - `*.readable.txt` con detalle de errores.
  - `*.fixes.txt` con cambios aplicados por autofix.
  - XML corregido `*.fixed.xml` cuando el autofix deja el archivo válido.

## Requisitos

- **Python** 3.9+ (recomendado).
- Paquetes Python:
  - `watchdog`
  - `lxml`
  - `PyYAML`

Puedes instalarlos vía `pip`:

```bash
pip install watchdog lxml pyyaml
```

## Estructura del proyecto

- `dte_precheck_watcher.py`: script principal. Levanta el watcher, aplica reglas y maneja el flujo OK/ERROR.
- `autofix.py`: motor de autocorrecciones seguras.
- `config.yaml`: configuración de rutas, reglas habilitadas y parámetros.
- `rules/`:
  - `rule_schema_basico.py`
  - `rule_schema_cdgitem.py`
  - `rule_cantidad.py`
  - `rule_moneda.py`
  - `rule_rut.py`
  - `rule_sanitize_ampersand.py`

## Configuración (`config.yaml`)

Las rutas y reglas se configuran sin tocar el código Python.

- **Rutas** (`paths`):
  - `in_dir`: carpeta donde llegan los XML a validar.
  - `ok_dir`: carpeta donde se mueven los XML válidos.
  - `err_dir`: carpeta donde se mueven los XML con errores y se generan los reportes.
- **Watcher** (`watch`):
  - `poll_stable_seconds`: intervalo entre chequeos de tamaño de archivo.
  - `stable_checks`: número de chequeos con mismo tamaño para considerar el archivo estable.
  - `processed_cache_seconds`: tiempo que se mantiene en caché un archivo ya procesado para evitar reprocesos.
- **Reglas habilitadas** (`rules.enabled`):
  - Lista de módulos dentro de `rules/` que se ejecutan en orden.
- **Parámetros para reglas** (`params`):
  - `moneda.allowed`: lista de monedas válidas (ej. `["CLP", "USD", "EUR"]`).
  - `cantidad.min`: valor mínimo permitido para cantidades (ej. `0.0`).
  - `sanitize_ampersand.enabled`, `mode`, `inplace`: controlan si se corrigen `&` mal escapados y cómo.

Ajusta `config.yaml` a tus rutas y criterios de negocio antes de ejecutar.

## Cómo ejecutar

1. Verifica que las carpetas configuradas en `config.yaml` (`in_dir`, `ok_dir`, `err_dir`) existan o deja que el script las cree.
2. Activa tu entorno virtual (opcional) e instala dependencias.
3. Desde la carpeta del proyecto (`DTE_POC`), ejecuta:

```bash
python dte_precheck_watcher.py
```

4. Deja el proceso corriendo. Cada vez que un XML nuevo aparezca en `in_dir`:
   - Se espera a que el archivo quede **estable** (tamaño sin cambios).
   - Se intenta parsear el XML.
   - Se aplican todas las reglas habilitadas.
   - Según el resultado:
     - **Sin errores**: el XML se mueve a `ok_dir`.
     - **Con errores**:
       - El XML original se mueve a `err_dir`.
       - Se genera un reporte `nombre.xml.readable.txt` en `err_dir`.
       - Se intenta aplicar **autofix** sobre una copia:
         - Si queda válido, se genera `nombre.fixed.xml` y se mueve a `ok_dir`.
         - Si sigue con errores, se mantiene en `err_dir` y se genera reporte adicional.

## Flujo de validación y autofix

1. **Parseo inicial**:
   - Si el XML está mal formado, se genera un issue `LECTURA_INPUT_XML` con línea y snippet cuando es posible.
2. **Reglas de negocio**:
   - Cada regla en `rules/` devuelve una lista de `ValidationIssue` que se consolidan en un único reporte.
3. **Autofix**:
   - Solo se ejecuta si el XML es parseable.
   - Aplica normalizaciones determinísticas (no inventa datos).
4. **Revalidación**:
   - El XML corregido se vuelve a pasar por las reglas para asegurar que queda en estado OK.

## Extender el sistema (nuevas reglas)

1. Crea un nuevo archivo en `rules/`, por ejemplo `rules/rule_mi_regla.py`.
2. Implementa una función:

```python
def run(tree, xml_path, ctx) -> List[ValidationIssue]:
    ...
```

3. Agrega el nombre del módulo a `rules.enabled` en `config.yaml`.
4. Reinicia el watcher.

## Notas

- El motor usa `lxml` con `huge_tree=True` para tolerar XML grandes.
- Para entornos productivos, se recomienda ejecutar el script como servicio (systemd, NSSM, etc.) y redirigir logs a un sistema de monitoreo.
