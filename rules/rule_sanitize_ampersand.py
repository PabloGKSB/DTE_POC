import re
from pathlib import Path
from typing import List, Tuple, Optional

from .models import ValidationIssue

# Match "&" que NO sea una entidad válida (&amp; &lt; &#123; etc.)
BAD_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9A-Fa-f]+);)")


def sanitize_xml_text(text: str, mode: str = "escape") -> Tuple[str, int]:
    """
    Sanitiza '&' no escapados en texto XML.

    mode:
      - "escape"  : reemplaza & malo por &amp;  (recomendado para XML estricto)
      - "and_es"  : reemplaza & malo por " Y "  (modo lenguaje natural)
    """
    if mode == "and_es":
        new_text, n = BAD_AMP.subn(" Y ", text)
    else:
        new_text, n = BAD_AMP.subn("&amp;", text)
    return new_text, n


def run_preparse(xml_path: Path, ctx: dict) -> Optional[str]:
    """
    Pre-parseo: se ejecuta ANTES de validar el XML con lxml.

    Si detecta '&' no escapados, crea una copia saneada del XML
    y la almacena en ctx["sanitized_path"] para que el motor la use.

    Retorna un mensaje descriptivo si se realizaron cambios, o None si no.
    """
    params = ctx.get("params", {})
    sanitize_cfg = params.get("sanitize_ampersand", {})
    enabled = bool(sanitize_cfg.get("enabled", True))
    mode = sanitize_cfg.get("mode", "escape")
    inplace = bool(sanitize_cfg.get("inplace", False))

    if not enabled:
        return None

    raw = xml_path.read_text(encoding="utf-8", errors="replace")
    fixed, n = sanitize_xml_text(raw, mode=mode)
    if n == 0:
        return None

    if inplace:
        xml_path.write_text(fixed, encoding="utf-8")
        return (
            f"Se corrigieron {n} ocurrencia(s) de '&' no escapado "
            f"(modo={mode}) directamente en el archivo."
        )
    else:
        # Crea copia junto al original (más seguro: no modifica el original)
        out = xml_path.with_suffix(xml_path.suffix + ".sanitized")
        out.write_text(fixed, encoding="utf-8")
        ctx["sanitized_path"] = out
        return (
            f"Se corrigieron {n} ocurrencia(s) de '&' no escapado "
            f"(modo={mode}). Copia saneada: {out.name}"
        )


def run(tree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Interfaz estándar del motor de reglas.

    Esta regla actúa como validador post-parseo: si el XML ya fue parseado
    (tree is not None), el '&' ya fue tolerable o saneado en pre-parseo.
    Aquí solo se reporta si se generó un archivo .sanitized (informativo).

    Nota: la corrección real de '&' se realiza en run_preparse(), que debe
    invocarse ANTES de parsear el XML (ver dte_precheck_watcher.py).
    """
    issues: List[ValidationIssue] = []

    # Si durante el pre-parseo se generó una copia saneada, lo reportamos
    # como WARNING informativo (no como ERROR bloqueante).
    sanitized = ctx.get("sanitized_path")
    if sanitized:
        issues.append(ValidationIssue(
            code="SANITIZE_AMPERSAND",
            field="XML",
            message=(
                f"El XML contenía '&' no escapados. "
                f"Se procesó la versión saneada: {Path(sanitized).name}"
            ),
            severity="WARN",
        ))

    return issues