import time
import shutil
import yaml
import logging
import importlib
from pathlib import Path
from typing import List, Optional
from dataclasses import asdict

from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler
from autofix import apply_autofix, FixChange
from rules.rule_sanitize_ampersand import run_preparse as sanitize_preparse


from lxml import etree


# =============================
# Logging
# =============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# =============================
# Cargar configuración (YAML)
# =============================
def load_config() -> dict:
    """
    Carga el archivo config.yaml ubicado en el mismo directorio del script.

    El YAML define:
      - paths: carpetas in/ok/error
      - watch: parámetros del watcher (estabilidad, cache)
      - rules: reglas habilitadas (plugins)
      - params: parámetros para reglas (min cantidad, monedas permitidas, etc.)
    """
    cfg_path = Path(__file__).parent / "config.yaml"
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


# Carga de configuración al iniciar el proceso
CFG = load_config()

# Rutas principales de entrada/salida definidas en config.yaml
IN_DIR  = Path(CFG["paths"]["in_dir"])
OK_DIR  = Path(CFG["paths"]["ok_dir"])
ERR_DIR = Path(CFG["paths"]["err_dir"])

# Parámetros del watcher:
# - poll_stable_seconds: cada cuánto revisa el tamaño del archivo para confirmar que terminó de escribirse
# - stable_checks: cuántas veces seguidas debe mantener el mismo tamaño para considerarlo "estable"
# - processed_cache_seconds: evita re-procesar el mismo archivo por eventos repetidos del filesystem
POLL_STABLE_SECONDS = float(CFG["watch"].get("poll_stable_seconds", 0.6))
STABLE_CHECKS = int(CFG["watch"].get("stable_checks", 2))
CACHE_SECONDS = int(CFG["watch"].get("processed_cache_seconds", 30))

# Lista de reglas habilitadas (por nombre de módulo dentro de rules/)
ENABLED_RULES = CFG["rules"]["enabled"]

# Parámetros globales para reglas (ej: moneda allowed, cantidad min, folio min, etc.)
PARAMS = CFG.get("params", {})


# =============================
# Motor de reglas (plugins)
# =============================
def load_rules(rule_names: List[str]):
    """
    Importa dinámicamente cada regla desde el package rules.

    En config.yaml se define:
      rules:
        enabled:
          - rule_schema_basico
          - rule_rut
          - rule_moneda
          ...

    Cada módulo en rules/<name>.py debe exponer una función:
      run(tree, xml_path, ctx) -> List[ValidationIssue | dict]
    """
    rules = []
    for name in rule_names:
        mod = importlib.import_module(f"rules.{name}")
        rules.append(mod.run)
    return rules


# Carga las funciones run() de todas las reglas habilitadas
RULE_FUNCS = load_rules(ENABLED_RULES)


# =============================
# Utilidades (I/O y parsing)
# =============================
def wait_until_stable(path: Path) -> bool:
    """
    Espera a que el archivo tenga tamaño "estable" antes de procesarlo.

    ¿Por qué?
      - Sistemas como QaD (o integraciones) a veces escriben el XML por partes.
      - Si lo lees antes de que termine de escribirse, puedes parsear un XML incompleto.

    Lógica:
      - Revisa el size del archivo cada POLL_STABLE_SECONDS
      - Si el size se repite STABLE_CHECKS veces seguidas y size > 0 -> estable
    """
    try:
        last = -1
        stable = 0
        while stable < STABLE_CHECKS:
            size = path.stat().st_size
            if size == last and size > 0:
                stable += 1
            else:
                stable = 0
                last = size
            time.sleep(POLL_STABLE_SECONDS)
        return True
    except FileNotFoundError:
        # Si el archivo desapareció (movido por otro proceso, etc.)
        return False


def safe_move(src: Path, dst_dir: Path) -> Path:
    """
    Mueve un archivo a un directorio destino de forma segura.

    - Crea la carpeta si no existe
    - Si ya existe un archivo con el mismo nombre en destino, agrega sufijo con timestamp
    - Usa shutil.move (mueve/renombra en mismo FS; si es diferente FS, copiará y borrará)
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        dst = dst_dir / f"{src.stem}_{int(time.time())}{src.suffix}"
    shutil.move(str(src), str(dst))
    return dst


def parse_xml(xml_path: Path):
    """
    Parsea el XML usando lxml.

    - recover=False: si está mal formado, lanza error (lo capturamos)
    - huge_tree=True: tolera árboles grandes

    Retorna:
      (tree, None, None) si OK
      (None, error_str, line) si XML mal formado
    """
    try:
        parser = etree.XMLParser(recover=False, huge_tree=True)
        return etree.parse(str(xml_path), parser), None, None
    except etree.XMLSyntaxError as e:
        # position: (line, column)
        line = getattr(e, "position", (None, None))[0]
        return None, str(e), line


def xml_snippet(xml_path: Path, line: int, context: int = 3) -> Optional[str]:
    """
    Extrae un snippet textual del XML alrededor de la línea donde ocurrió el error.

    - Esto hace que el reporte sea mucho más útil para debugging
    - No siempre se podrá (ej: encoding raro), por eso se maneja con try/except
    """
    if not line:
        return None
    try:
        lines = xml_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, line - context)
        end = min(len(lines), line + context)
        out = []
        for i in range(start, end + 1):
            out.append(f"{i:>4}: {lines[i-1].rstrip()}")
        return "\n".join(out)
    except Exception:
        return None
    
def write_fixed_xml(tree: etree._ElementTree, out_path: Path):
    """
    Guarda el XML (lxml tree) a disco.
    - pretty_print=False para no alterar formato más de lo necesario
    - xml_declaration=True para mantener estructura estándar
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(out_path),
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=False
    )



# =============================
# Validación: aplica reglas
# =============================
def validate_xml(xml_path: Path):
    """
    Valida un XML aplicando:
      1) Pre-parseo: sanitize_ampersand (corrige & mal escapados si están presentes)
      2) parse XML (si falla, issue de XML mal formado)
      3) ejecución de cada regla habilitada
      4) captura de excepciones por regla para que una regla mala no caiga el servicio

    Retorna una lista de issues (dicts) lista para reportar.
    """
    issues = []

    # Contexto pasado a reglas (solo params por ahora)
    ctx = {"params": PARAMS}

    # 0) Pre-parseo: sanitize_ampersand antes de parsear
    #    Si detecta & mal escapados, crea copia .sanitized y la almacena en ctx
    preparse_msg = sanitize_preparse(xml_path, ctx)
    if preparse_msg:
        log.warning("%s: %s", xml_path.name, preparse_msg)

    # Si el pre-parseo generó una copia saneada, validamos esa copia
    effective_path = ctx.get("sanitized_path", xml_path)

    # 1) Parseo XML: si está mal formado se reporta y no se siguen reglas
    tree, err, line = parse_xml(effective_path)
    if not tree:
        issues.append({
            "code": "LECTURA_INPUT_XML",
            "field": "XML",
            "message": f"XML mal formado: {err}",
            "line": line,
            "snippet": xml_snippet(effective_path, line)
        })
        return issues

    # 2) Ejecutar reglas una a una
    for rule in RULE_FUNCS:
        try:
            res = rule(tree, xml_path, ctx)

            # La regla puede retornar:
            # - ValidationIssue (dataclass)
            # - dict ya armado
            # Aquí normalizamos a dict para uniformidad.
            for it in res:
                if hasattr(it, "__dict__") and "code" in it.__dict__:
                    issues.append(it.__dict__)
                else:
                    issues.append(it)

        except Exception as e:
            # 3) Si una regla explota, no se cae todo el watcher:
            issues.append({
                "code": "PRECHECK_INTERNAL",
                "field": "RuleEngine",
                "message": f"Regla lanzó excepción: {e}"
            })

    return issues


def write_report(xml_path: Path, issues: list, dest_dir: Path):
    """
    Genera un reporte legible (.readable.txt) con todos los issues.

    - Se guarda en ERR_DIR por conveniencia operacional
    - Incluye: code, field, message
    - Si hay línea/snippet, también se incluye (muy útil para XML mal formado)
    """
    rep = dest_dir / (xml_path.name + ".readable.txt")

    lines = [
        f"FILE: {xml_path.name}",
        f"RESULT: ERROR ({len(issues)} issues)",
        ""
    ]

    for i, it in enumerate(issues, 1):
        code = it.get("code", "NA")
        field = it.get("field", "NA")
        msg = it.get("message", "")
        lines.append(f"{i}. [{code}] FIELD={field} | {msg}")

        # Info adicional si la regla/parseo entregó línea/snippet
        if it.get("line"):
            lines.append(f"   line={it['line']}")
        if it.get("snippet"):
            lines.append("   XML_SNIPPET:")
            for sn in it["snippet"].splitlines():
                lines.append("   " + sn)

    lines.append("")
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_fix_report(base_path: Path, changes: List[FixChange], dest_dir: Path):
    """
    Reporte de cambios aplicados por autofix.
    """
    rep = dest_dir / (base_path.name + ".fixes.txt")
    lines = [
        f"FILE: {base_path.name}",
        f"FIXES_APPLIED: {len(changes)}",
        ""
    ]
    for i, ch in enumerate(changes, 1):
        lines.append(f"{i}. FIELD={ch.field} TAG=<{ch.tag}> | '{ch.old}' -> '{ch.new}'")
    lines.append("")
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")

def send_fatal_email(xml_name: str, issues: list, is_fixed=False):
    email_cfg = PARAMS.get("alertas_email", {})
    if not (email_cfg and email_cfg.get("origen")):
        return
        
    from rules.email_utils import enviar_alerta_caf
    
    estado = "después de intentar correcciones automáticas" if is_fixed else "sin poder aplicar correcciones automáticas"
    asunto = f"ALERTA DTE: Rechazo en {xml_name}"
    
    lines = [
        f"El archivo {xml_name} generó alertas o fue rechazado ({estado}).",
        f"Se encontraron {len(issues)} advertencia(s)/error(es):",
        ""
    ]
    for i, it in enumerate(issues, 1):
        code = it.get("code", "NA")
        field = it.get("field", "NA")
        msg = it.get("message", "")
        lines.append(f"{i}. [{code}] CAMPO: {field} | {msg}")

    cuerpo = "\n".join(lines)
    enviar_alerta_caf(asunto, cuerpo, email_cfg)



# =============================
# Watcher: procesamiento eventos
# =============================
class Processor:
    """
    Encapsula el procesamiento de archivos XML y un cache anti-repetición.

    watchfiles dispara muchos eventos (created/modified/moved),
    por lo que se evita procesar lo mismo múltiples veces en segundos.
    """
    def __init__(self):
        self.cache = {}

    def recently_processed(self, path: Path) -> bool:
        """
        Retorna True si el archivo fue procesado "recientemente".

        Además limpia entradas viejas del cache, para que el dict
        no crezca indefinidamente.
        """
        now = time.time()

        # Limpieza del cache por TTL
        for k in list(self.cache.keys()):
            if now - self.cache[k] > CACHE_SECONDS:
                del self.cache[k]

        # Normaliza key (lower) para que cambios de casing no dupliquen
        key = str(path).lower()
        return key in self.cache

    def mark(self, path: Path):
        """Marca el archivo como procesado en el cache."""
        self.cache[str(path).lower()] = time.time()

    def process(self, path: Path):
        """
        Pipeline completo por archivo:

        1) filtra solo .xml
        2) verifica que exista
        3) cache anti-reproceso
        4) espera estabilidad del archivo (terminó de escribirse)
        5) valida
        6) mueve a OK o ERR y genera reporte
        """
        if path.suffix.lower() != ".xml":
            return
        if not path.exists():
            return
        if self.recently_processed(path):
            return
        if not wait_until_stable(path):
            return

        # Marcamos antes de validar para evitar doble ejecución por eventos seguidos
        self.mark(path)

        issues = validate_xml(path)

        if not issues:
            safe_move(path, OK_DIR)
            log.info("[OK] %s -> %s", path.name, OK_DIR)
        else:
           # 1) Mover original a ERR (sin tocarlo)
            moved_original = safe_move(path, ERR_DIR)

            # 2) Guardar reporte del error original
            write_report(moved_original, issues, ERR_DIR)

            # 3) Intentar autofix sobre una COPIA (tree desde el original movido)
            tree, err, line = parse_xml(moved_original)
            if not tree:
                # Si ni siquiera parsea, no hay nada que arreglar
                log.error("[ERROR] %s -> %s (XML mal formado, sin autofix)", moved_original.name, ERR_DIR)
                send_fatal_email(moved_original.name, issues)
                return

            ctx = {"params": PARAMS}
            changes = apply_autofix(tree, ctx)

            if not changes:
                # No había correcciones seguras aplicables
                log.warning("[ERROR] %s -> %s (sin correcciones aplicables)", moved_original.name, ERR_DIR)
                send_fatal_email(moved_original.name, issues)
                return

            # 4) Guardar XML corregido con sufijo .fixed.xml en ERR_DIR (auditable)
            fixed_path = ERR_DIR / (moved_original.stem + ".fixed.xml")
            write_fixed_xml(tree, fixed_path)

            # 5) Reporte de cambios realizados
            write_fix_report(fixed_path, changes, ERR_DIR)

            # 6) Revalidar el XML corregido
            fixed_issues = validate_xml(fixed_path)

            if not fixed_issues:
                # 7) Si pasa, mover el fixed a OK_DIR
                moved_fixed = safe_move(fixed_path, OK_DIR)
                log.info("[FIXED->OK] %s fixed as %s -> %s", moved_original.name, moved_fixed.name, OK_DIR)
            else:
                # Si sigue fallando, dejarlo en ERR y reportar sus issues
                write_report(fixed_path, fixed_issues, ERR_DIR)
                log.warning("[ERROR] %s -> %s (autofix aplicado pero sigue fallando)", moved_original.name, ERR_DIR)
                send_fatal_email(moved_original.name, fixed_issues, is_fixed=True)

class Handler(FileSystemEventHandler):
    """
    Handler de watchdog: reacciona a eventos del filesystem.

    Se registran:
      - on_created: archivo nuevo
      - on_modified: archivo modificado (común cuando se escribe por partes)
      - on_moved: cuando un archivo es movido/renombrado hacia el directorio observado
    """
    def __init__(self, processor: Processor):
        self.processor = processor

    def on_created(self, event):
        if not event.is_directory:
            self.processor.process(Path(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self.processor.process(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self.processor.process(Path(event.dest_path))


def scan_existing(proc: Processor):
    """
    Escanea XML ya existentes al arrancar el servicio.

    Útil si el servicio se reinicia y quedaron archivos pendientes
    en la carpeta IN_DIR.
    """
    for p in sorted(IN_DIR.glob("*.xml")):
        proc.process(p)


def main():
    """
    Punto de entrada:
      - crea carpetas si no existen
      - procesa pendientes existentes
      - inicia watchdog observer
      - loop infinito hasta Ctrl+C
    """
    # Asegura que las carpetas existan
    for d in (IN_DIR, OK_DIR, ERR_DIR):
        d.mkdir(parents=True, exist_ok=True)

    proc = Processor()

    # Procesa archivos que ya estaban antes de iniciar el watcher
    scan_existing(proc)

    # Configura observer (watchdog)
    obs = Observer()
    obs.schedule(Handler(proc), str(IN_DIR), recursive=False)
    obs.start()

    # Logs básicos en consola (en servicio systemd se irían a journalctl)
    log.info("Watching: %s", IN_DIR)
    log.info("OK_DIR:   %s", OK_DIR)
    log.info("ERR_DIR:  %s", ERR_DIR)
    log.info("Rules:    %s", ENABLED_RULES)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()


if __name__ == "__main__":
    main()
