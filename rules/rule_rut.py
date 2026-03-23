from typing import List
from pathlib import Path
from lxml import etree

from .models import ValidationIssue


# =========================================
# Helper: extraer textos por tag (sin NS)
# =========================================
def _find_texts(tree: etree._ElementTree, tag_local: str):
    """
    Busca todos los nodos cuyo nombre local sea `tag_local`,
    ignorando namespaces del XML.

    Retorna una lista de tuplas:
        (texto_del_nodo, nodo_xml)

    Se usa para recorrer distintos posibles nombres de tag
    que contienen un RUT.
    """
    return [
        ((n.text or "").strip(), n)
        for n in tree.xpath(f"//*[local-name()='{tag_local}']")
    ]


# =========================================
# Normalización de RUT
# =========================================
def _normalize_rut(raw: str) -> str:
    """
    Normaliza un RUT eliminando puntos, espacios y dejando
    todo en mayúsculas.

    Ejemplos:
      "12.345.678-k" -> "12345678-K"
      " 12345678-9 " -> "12345678-9"
    """
    return raw.strip().upper().replace(".", "").replace(" ", "")


# =========================================
# Validación de RUT chileno
# =========================================
def _rut_is_valid(raw: str) -> bool:
    """
    Valida un RUT chileno usando el algoritmo de módulo 11.

    Pasos:
      1) Normaliza el RUT
      2) Separa número base y dígito verificador
      3) Aplica ponderadores 2..7 desde derecha a izquierda
      4) Calcula DV esperado
      5) Compara con DV informado

    Retorna:
      True si el RUT es válido, False en caso contrario
    """
    r = _normalize_rut(raw)

    # Debe existir el separador "-"
    if "-" not in r:
        return False

    num, dv = r.split("-", 1)

    # El cuerpo debe ser numérico y el DV de largo 1
    if not num.isdigit() or len(dv) != 1:
        return False

    dv = dv.upper()

    # Cálculo del dígito verificador (módulo 11)
    total = 0
    mult = 2
    for ch in reversed(num):
        total += int(ch) * mult
        mult = 2 if mult == 7 else mult + 1

    mod = 11 - (total % 11)

    # Conversión de resultado a DV esperado
    expected = "0" if mod == 11 else "K" if mod == 10 else str(mod)

    return dv == expected


# =========================================
# Regla: Validación de RUT en XML
# =========================================
def run(tree: etree._ElementTree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Valida todos los RUT encontrados en el XML.

    Se revisan distintos nombres de tag posibles, ya que
    dependiendo del tipo de DTE o del origen del XML,
    el RUT puede venir en diferentes campos.

    Esta regla:
      - NO corrige el RUT
      - NO detiene el proceso
      - SOLO reporta inconsistencias

    Retorna:
      Lista de ValidationIssue (vacía si no hay errores)
    """
    issues: List[ValidationIssue] = []

    # Posibles tags donde puede venir un RUT
    rut_tags = (
        "RUTEmisor",
        "RUTRecep",
        "RUTChofer",
        "Rut",
        "RUT",
    )

    # Recorre cada tag candidato y valida su contenido
    for tag in rut_tags:
        for val, _node in _find_texts(tree, tag):

            # Si el campo existe pero está vacío, se ignora
            if not val:
                continue

            # Validación formal del RUT
            if not _rut_is_valid(val):
                issues.append(ValidationIssue(
                    code="LECTURA_INPUT_XML",
                    field="Rut",
                    message=f"RUT inválido en <{tag}>: '{val}'."
                ))

    return issues
