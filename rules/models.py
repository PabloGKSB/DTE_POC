from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationIssue:
    """
    Modelo estándar de error/issue que devuelven todas las reglas del motor.

    Centralizado aquí para evitar duplicación entre reglas y garantizar
    un formato uniforme en reportes, notificaciones y métricas.

    Campos:
      code     - Código lógico del error (ej: VALIDA_SCHEMA, LECTURA_INPUT_XML)
      field    - Campo / ruta funcional afectada (ej: Chofer/NombreChofer)
      message  - Descripción legible del problema detectado
      severity - Severidad del issue (default: ERROR; puede ser WARN, INFO)
      line     - Línea del XML donde ocurrió el error (si disponible)
      snippet  - Fragmento del XML alrededor del error (si disponible)
    """
    code: str
    field: str
    message: str
    severity: str = "ERROR"
    line: Optional[int] = None
    snippet: Optional[str] = None
