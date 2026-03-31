from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from lxml import etree
import re


@dataclass
class FixChange:
    field: str
    tag: str
    old: str
    new: str


def _iter_nodes_by_local(tree: etree._ElementTree, local_name: str):
    return tree.xpath(f"//*[local-name()='{local_name}']")


def _safe_set_text(node, new_text: str) -> bool:
    old = node.text or ""
    if old == new_text:
        return False
    node.text = new_text
    return True


# -------------------------
# Normalización de moneda
# -------------------------
def _fix_moneda(tree: etree._ElementTree, ctx: dict) -> List[FixChange]:
    changes: List[FixChange] = []

    allowed = ctx.get("params", {}).get("moneda", {}).get("allowed", [])
    allowed = [x.upper() for x in allowed] if isinstance(allowed, list) else []

    # Tabla de equivalencias (segura y extensible)
    synonyms = {
        # USD
        "DOLAR USA": "USD",
        "DÓLAR USA": "USD",
        "DOLARES": "USD",
        "DÓLARES": "USD",
        "DOLAR": "USD",
        "DÓLAR": "USD",
        "US$": "USD",
        "USD$": "USD",
        "U$D": "USD",
        "US DOLLAR": "USD",

        # CLP
        "PESO CHILENO": "CLP",
        "PESOS CHILENOS": "CLP",
        "PESO": "CLP",
        "PESOS": "CLP",
        "CLP$": "CLP",
        "$CLP": "CLP",

        # EUR
        "EURO": "EUR",
        "EUROS": "EUR",
        "€": "EUR",
    }

    for tag in ("Moneda", "TpoMoneda"):
        for node in _iter_nodes_by_local(tree, tag):
            old = (node.text or "").strip()
            if not old:
                continue

            norm = old.strip().upper()
            mapped = synonyms.get(norm, norm)

            # Si hay lista allowed, solo aplicar si el resultado es permitido
            if allowed and mapped not in allowed:
                continue

            if mapped != old:
                _safe_set_text(node, mapped)
                changes.append(FixChange(field="Moneda", tag=tag, old=old, new=mapped))

    return changes


# -------------------------
# Normalización numérica
# -------------------------
def _normalize_number_text(s: str) -> Optional[str]:
    """
    Normaliza números típicos:
      - "1,5" -> "1.5"
      - "1.000,50" -> "1000.50"
      - "1,000.50" -> "1000.50"
    Retorna string normalizada o None si no se puede inferir de forma segura.
    """
    raw = (s or "").strip()
    if not raw:
        return None

    # Quitar espacios internos
    raw = raw.replace(" ", "")

    # Si contiene ambos separadores, inferimos que el ÚLTIMO separador es el decimal
    if "," in raw and "." in raw:
        last_comma = raw.rfind(",")
        last_dot = raw.rfind(".")
        if last_comma > last_dot:
            # decimal = "," ; miles = "."
            raw = raw.replace(".", "")
            raw = raw.replace(",", ".")
        else:
            # decimal = "." ; miles = ","
            raw = raw.replace(",", "")
        return raw

    # Solo coma: asumir coma decimal (caso común CL)
    if "," in raw and "." not in raw:
        return raw.replace(",", ".")

    # Solo punto: puede ser decimal o miles; no tocamos miles con solo "."
    # porque "1.000" podría ser mil o uno con decimales.
    # (si quieres, se puede parametrizar; por defecto conservador)
    if "." in raw and "," not in raw:
        return raw

    # Solo dígitos (o con signo)
    return raw


def _fix_cantidad(tree: etree._ElementTree, ctx: dict) -> List[FixChange]:
    changes: List[FixChange] = []
    for tag in ("Cantidad", "QtyItem", "Qty", "QTYItem", "QTYitems"):
        for node in _iter_nodes_by_local(tree, tag):
            old = (node.text or "").strip()
            if not old:
                continue

            new = _normalize_number_text(old)
            if new is None:
                continue

            if new != old:
                _safe_set_text(node, new)
                changes.append(FixChange(field="Cantidad", tag=tag, old=old, new=new))
    return changes


# -------------------------
# Normalización de RUT
# -------------------------
def _normalize_rut_format(raw: str) -> str:
    return raw.strip().upper().replace(".", "").replace(" ", "")


def _add_rut_hyphen_if_missing(r: str) -> Optional[str]:
    """
    Si viene como 12345678K o 123456789 (sin guion),
    intenta convertir a 12345678-K / 12345678-9
    SIN validar DV (solo formato).
    """
    r = _normalize_rut_format(r)
    if "-" in r:
        return r

    if len(r) < 2:
        return None

    num, dv = r[:-1], r[-1]
    if num.isdigit() and (dv.isdigit() or dv == "K"):
        return f"{num}-{dv}"
    return None


def _fix_rut_format(tree: etree._ElementTree, ctx: dict) -> List[FixChange]:
    changes: List[FixChange] = []
    rut_tags = ("RUTEmisor", "RUTRecep", "RUTChofer", "Rut", "RUT")

    for tag in rut_tags:
        for node in _iter_nodes_by_local(tree, tag):
            old = (node.text or "").strip()
            if not old:
                continue

            # 1) normaliza puntos/espacios/mayúsculas
            norm = _normalize_rut_format(old)

            # 2) si falta guion, intenta insertarlo de forma segura
            with_hyphen = _add_rut_hyphen_if_missing(norm) or norm

            if with_hyphen != old:
                _safe_set_text(node, with_hyphen)
                changes.append(FixChange(field="Rut", tag=tag, old=old, new=with_hyphen))

    return changes


# -------------------------
# Pipeline principal
# -------------------------
def apply_autofix(tree: etree._ElementTree, ctx: dict) -> List[FixChange]:
    """
    Aplica autocorrecciones seguras (normalizaciones determinísticas).
    No inventa datos de negocio (nombre/dirección/folio/ref/etc).
    """
    changes: List[FixChange] = []
    changes += _fix_moneda(tree, ctx)
    changes += _fix_cantidad(tree, ctx)
    changes += _fix_rut_format(tree, ctx)
    return changes
