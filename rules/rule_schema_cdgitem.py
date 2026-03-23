from typing import List
from pathlib import Path
from lxml import etree

from .models import ValidationIssue


# =========================================
# Regla: validación de bloque CdgItem
# =========================================
def run(tree: etree._ElementTree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Valida la consistencia del bloque <CdgItem>.

    Regla aplicada:
      - Si existe un bloque <CdgItem>, entonces debe existir
        al menos un subnodo <VlrCodigo> dentro de él.

    Esta validación apunta a detectar XML incompletos que suelen
    provocar errores de tipo "VALIDA_SCHEMA" en el sistema externo.

    Importante:
      - No se valida el contenido de <VlrCodigo>, solo su existencia.
      - La regla NO corrige el XML, solo reporta el problema.

    Parámetros:
      - tree: XML parseado con lxml
      - xml_path: ruta del archivo XML (útil para logs o contexto)
      - ctx: contexto global (no utilizado en esta regla, pero
             se mantiene por consistencia con el motor)

    Retorna:
      - Lista de ValidationIssue (vacía si no se detectan problemas)
    """
    issues: List[ValidationIssue] = []

    # Busca todos los bloques <CdgItem> en el XML, sin importar namespace
    cdg_items = tree.xpath("//*[local-name()='CdgItem']")

    # Por cada bloque encontrado, se valida la existencia de <VlrCodigo>
    for node in cdg_items:

        # XPath relativo para buscar <VlrCodigo> dentro del bloque actual
        has_vlr = node.xpath(".//*[local-name()='VlrCodigo']")

        # Si no existe <VlrCodigo>, el bloque se considera incompleto
        if not has_vlr:
            issues.append(ValidationIssue(
                code="VALIDA_SCHEMA",
                field="CdgItem/VlrCodigo",
                message="El bloque <CdgItem> está incompleto: falta <VlrCodigo>."
            ))

    return issues
