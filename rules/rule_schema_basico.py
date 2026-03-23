from typing import List
from pathlib import Path
from lxml import etree

from .models import ValidationIssue


# =========================================
# Regla: validaciones básicas tipo "schema"
# =========================================
def run(tree: etree._ElementTree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Regla de consistencia básica (tipo "schema lógico"):

    La idea NO es validar contra un XSD completo, sino detectar
    inconsistencias comunes y repetitivas que suelen provocar
    rechazos del validador externo (ej: "VALIDA_SCHEMA").

    Validaciones incluidas:
      1) Chofer:
         - Si existe el bloque <Chofer>, entonces debe existir
           un subnodo <NombreChofer>.
         - Si falta, el bloque se considera incompleto.

      2) Referencia:
         - Si dentro de <Referencia> aparece <FchRef> (fecha de referencia),
           entonces se exige <FolioRef> (folio de referencia).
         - Esto representa una regla de completitud: si ingresas fecha,
           el folio asociado no puede faltar.

      3) Receptor:
         - Si existe el bloque <Receptor>, entonces deben existir
           subnodos <RUTRecep> y <RznSocRecep>.
         - Ayuda a mitigar errores comunes de schema como fallos en
           CdgIntRecep o Contacto por falta de precedentes.

    Parámetros:
      - tree: XML ya parseado con lxml
      - xml_path: ruta del archivo XML (útil para logs/contexto si se necesita)
      - ctx: contexto global (no se usa en esta regla, pero se mantiene
             por consistencia con el resto del motor de reglas)

    Retorna:
      - Lista de ValidationIssue (vacía si no se detectan problemas)
    """
    issues: List[ValidationIssue] = []

    # ---------------------------------------------------------
    # 1) Chofer: si existe <Chofer>, debe existir <NombreChofer>
    # ---------------------------------------------------------
    # Se recorre cada bloque <Chofer> encontrado en cualquier parte del XML.
    # local-name() permite ignorar namespaces.
    for chofer in tree.xpath("//*[local-name()='Chofer']"):

        # Se valida que dentro del bloque exista al menos un <NombreChofer>.
        # Si no existe, se reporta como "schema inconsistente".
        if not chofer.xpath(".//*[local-name()='NombreChofer']"):
            issues.append(ValidationIssue(
                code="VALIDA_SCHEMA",
                field="Chofer/NombreChofer",
                message="El bloque <Chofer> está incompleto: falta <NombreChofer>."
            ))

    # ---------------------------------------------------------
    # 2) Referencia: si existe <FchRef>, exigir <FolioRef>
    # ---------------------------------------------------------
    # Por cada bloque <Referencia>, si existe la fecha de referencia (<FchRef>)
    # se exige el folio de esa referencia (<FolioRef>).
    for ref in tree.xpath("//*[local-name()='Referencia']"):

        # Condición:
        # - Hay <FchRef>
        # - Pero NO hay <FolioRef>
        if ref.xpath(".//*[local-name()='FchRef']") and not ref.xpath(".//*[local-name()='FolioRef']"):
            issues.append(ValidationIssue(
                code="VALIDA_SCHEMA",
                field="Referencia/FolioRef",
                message="En <Referencia> aparece <FchRef> pero falta <FolioRef>."
            ))

    # ---------------------------------------------------------
    # 3) Receptor: si existe <Receptor>, exigir <RUTRecep> y <RznSocRecep>
    # ---------------------------------------------------------
    # Por cada bloque <Receptor> validamos que tenga campos de identificación
    # críticos y requeridos antes de seguir parseando nodos opcionales.
    for recep in tree.xpath("//*[local-name()='Receptor']"):

        # Condición: falta el RUT del receptor
        if not recep.xpath(".//*[local-name()='RUTRecep']"):
            issues.append(ValidationIssue(
                code="VALIDA_SCHEMA",
                field="Receptor/RUTRecep",
                message="El bloque <Receptor> está incompleto: falta <RUTRecep>."
            ))

        # Condición: falta la Razón Social del receptor
        if not recep.xpath(".//*[local-name()='RznSocRecep']"):
            issues.append(ValidationIssue(
                code="VALIDA_SCHEMA",
                field="Receptor/RznSocRecep",
                message="El bloque <Receptor> está incompleto: falta <RznSocRecep>."
            ))

    return issues
