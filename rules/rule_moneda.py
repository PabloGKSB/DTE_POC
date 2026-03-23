from typing import List
from pathlib import Path
from lxml import etree
import re

from .models import ValidationIssue


# =========================================
# Helper: extraer textos por tag (sin NS)
# =========================================
def _find_texts(tree: etree._ElementTree, tag_local: str):
    """
    Busca todos los nodos cuyo nombre local sea `tag_local`, ignorando namespaces.

    Retorna lista de tuplas:
        (texto_normalizado, nodo_xml)

    Esto permite:
      - validar contenido textual
      - eventualmente usar el nodo para obtener línea/snippet (si se implementa)
    """
    return [
        ((n.text or "").strip(), n)
        for n in tree.xpath(f"//*[local-name()='{tag_local}']")
    ]


# =========================================
# Regla: Validación de Moneda / TpoMoneda
# =========================================
def run(tree: etree._ElementTree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Valida el/los campos de moneda dentro del XML.

    Reglas aplicadas:
      1) Si el valor existe, se evalúa (si está vacío se ignora).
      2) Largo máximo recomendado: 3 caracteres (ISO 4217 como CLP/USD/EUR).
      3) Debe ser exactamente 3 letras (regex).
      4) Si existe lista de permitidas en config, la moneda debe estar en esa lista.

    Importante:
    - Esta regla NO corrige el valor, solo reporta issues.
    - La lista de monedas permitidas se parametriza desde ctx (config.yaml).

    Parámetros esperados en config.yaml:
      params:
        moneda:
          allowed: ["CLP", "USD", "EUR"]
    """

    # Obtiene el listado de monedas permitidas desde el contexto.
    # Si viene bien formado como lista, lo normalizamos a upper-case.
    allowed = ctx.get("params", {}).get("moneda", {}).get("allowed", [])
    allowed = [x.upper() for x in allowed] if isinstance(allowed, list) else []

    issues: List[ValidationIssue] = []

    # Algunos XML usan <Moneda>, otros usan <TpoMoneda>. Validamos ambos.
    for tag in ("Moneda", "TpoMoneda"):
        for val, _node in _find_texts(tree, tag):

            # Si el tag existe pero viene vacío, esta regla lo ignora.
            # (Si quieres exigirlo, se puede agregar una regla distinta).
            if not val:
                continue

            # Normalizamos a mayúsculas para comparar con la lista "allowed"
            v = val.upper()

            # Caso 1: largo mayor a 3 (lo típico es 3 letras)
            if len(v) > 3:
                issues.append(ValidationIssue(
                    code="LECTURA_INPUT_XML",
                    field="Moneda",
                    message=(
                        f"El campo <{tag}> supera largo máximo 3: '{val}'. "
                        f"Use CLP/USD/EUR."
                    )
                ))

            # Caso 2: no cumple patrón de 3 letras (ideal ISO 4217)
            # Nota: aquí la regex se aplica sobre el valor original, no el upper.
            # Igual es válido, porque acepta A-Z y a-z.
            if not re.fullmatch(r"[A-Za-z]{3}", val):
                issues.append(ValidationIssue(
                    code="LECTURA_INPUT_XML",
                    field="Moneda",
                    message=f"El campo <{tag}> debería ser 3 letras. Valor: '{val}'."
                ))

            # Caso 3: si hay lista "allowed", validar pertenencia
            if allowed and v not in allowed:
                issues.append(ValidationIssue(
                    code="LECTURA_INPUT_XML",
                    field="Moneda",
                    message=f"Moneda '{val}' no está en permitidas: {allowed}."
                ))

    return issues
