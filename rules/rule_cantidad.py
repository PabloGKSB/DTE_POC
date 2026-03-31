from typing import List
from pathlib import Path
from lxml import etree

from .models import ValidationIssue


# =========================================
# Función auxiliar: buscar textos por tag
# =========================================
def _find_texts(tree: etree._ElementTree, tag_local: str):
    """
    Busca todos los nodos del XML cuyo nombre local coincida con `tag_local`,
    ignorando namespaces.

    Retorna una lista de tuplas:
        (texto_del_nodo, nodo_xml)

    Esto permite:
    - Validar el contenido textual
    - Tener acceso al nodo original si se quiere obtener línea/snippet
    """
    return [
        ((n.text or "").strip(), n)
        for n in tree.xpath(f"//*[local-name()='{tag_local}']")
    ]


# =========================================
# Regla de validación: Cantidad
# =========================================
def run(tree: etree._ElementTree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Valida que los campos de cantidad en el XML:
    - Existan
    - Sean numéricos
    - Sean mayores a un valor mínimo configurable

    Esta regla NO modifica el XML, solo detecta errores.

    Parámetros:
    - tree: XML ya parseado (lxml)
    - xml_path: ruta del archivo XML (útil para logging o contexto)
    - ctx: contexto global con parámetros (config.yaml)

    Retorna:
    - Lista de ValidationIssue (vacía si no hay errores)
    """

    # Obtiene parámetros configurables desde el contexto
    # Ejemplo en config.yaml:
    # params:
    #   cantidad:
    #     min: 0.0
    params = ctx.get("params", {}).get("cantidad", {})
    min_val = float(params.get("min", 0.0))

    issues: List[ValidationIssue] = []

    # Posibles nombres de tags que representan cantidad
    # (por variaciones de schema o versiones)
    candidate_tags = ("Cantidad", "QtyItem", "Qty", "QTYItem", "QTYitems")

    # Recorre cada variante de tag posible
    for tag in candidate_tags:
        for val, _node in _find_texts(tree, tag):

            # Caso 1: campo vacío. Lo ignoramos (no es error)
            if val is None or val.strip() == "":
                continue

            # Normalización simple:
            # reemplaza coma por punto para decimales mal formateados
            norm = val.replace(",", ".")

            try:
                num = float(norm)

                # Caso 2: valor numérico pero inválido por rango
                if num < min_val:
                    issues.append(ValidationIssue(
                        code="LECTURA_INPUT_XML",
                        field="Cantidad",
                        message=(
                            f"El campo <{tag}> debe ser > {min_val}. "
                            f"Valor: '{val}'."
                        )
                    ))

            except ValueError:
                # Caso 3: valor no numérico
                issues.append(ValidationIssue(
                    code="LECTURA_INPUT_XML",
                    field="Cantidad",
                    message=f"El campo <{tag}> debe ser numérico. Valor: '{val}'."
                ))

    return issues
