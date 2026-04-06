from typing import List, Optional
from pathlib import Path
from lxml import etree

from .models import ValidationIssue

def parse_caf_range(caf_path: Path) -> Optional[tuple[int, int]]:
    """
    Lee un archivo XML de CAF y extrae el rango de folios autorizados.
    Retorna una tupla (desde, hasta) o None si no se pudo leer.
    El CAF tiene la estructura <RNG><D>desde</D><H>hasta</H></RNG>
    """
    try:
        # El CAF real a veces trae declaration y cosas raras, usamos recover
        parser = etree.XMLParser(recover=True)
        tree = etree.parse(str(caf_path), parser)
        
        # Buscamos los nodos D (Desde) y H (Hasta) dentro de RNG
        d_nodes = tree.xpath("//*[local-name()='RNG']/*[local-name()='D']")
        h_nodes = tree.xpath("//*[local-name()='RNG']/*[local-name()='H']")
        
        if d_nodes and h_nodes:
            d = int((d_nodes[0].text or "0").strip())
            h = int((h_nodes[0].text or "0").strip())
            return d, h
    except Exception:
        pass
    return None

def find_valid_caf(caf_dir: Path, tipo_dte: str, current_folio: int) -> Optional[tuple[Path, int]]:
    """
    Busca en el directorio de CAFs configurado un archivo que contenga
    autorización para el tipo_dte y cuyo rango incluya current_folio.
    Retorna (ruta_al_caf, folios_restantes) o None.
    """
    # Escaneamos todos los XML de la carpeta
    for caf_path in caf_dir.glob("*.xml"):
        # Podríamos optimizar filtrando el nombre si tienen un estándar, 
        # pero para estar seguros parseamos rápido el XML para ver el TD
        try:
            tree = etree.parse(str(caf_path), etree.XMLParser(recover=True))
            td_nodes = tree.xpath("//*[local-name()='TD']")
            
            if td_nodes and td_nodes[0].text.strip() == tipo_dte:
                # Encontramos un CAF para este tipo de documento.
                # Verificamos si este folio está dentro del rango
                rng = parse_caf_range(caf_path)
                if rng:
                    # Rango: D (Desde) y H (Hasta)
                    desde, hasta = rng
                    if desde <= current_folio <= hasta:
                        restantes = hasta - current_folio
                        total_caf = (hasta - desde) + 1
                        return caf_path, restantes, total_caf
        except Exception:
            continue
            
    return None


# =========================================
# Regla: Validación de Stock de CAF
# =========================================
def run(tree: etree._ElementTree, xml_path: Path, ctx: dict) -> List[ValidationIssue]:
    """
    Valida que el DTE tenga un Folio autorizado por un CAF existente en el directorio configurado
    y genera alertas preventivas si quedan pocos folios disponibles.
    
    Parámetros (en config.yaml):
      params:
        caf:
          dir: "Z:/"
          alerta_stock: 50
    """
    issues: List[ValidationIssue] = []

    # Leemos configuración
    caf_cfg = ctx.get("params", {}).get("caf", {})
    caf_dir_str = caf_cfg.get("dir")
    alerta_porcentaje = float(caf_cfg.get("alerta_porcentaje", 10.0)) / 100.0
    
    if not caf_dir_str:
        return issues # No configurado, no hacemos nada
        
    caf_dir = Path(caf_dir_str)
    if not caf_dir.exists():
        issues.append(ValidationIssue(
            code="CAF_CONFIG_ERROR",
            field="Sistema",
            message=f"La carpeta de CAFs configurada no existe: {caf_dir}",
            severity="WARN"
        ))
        return issues

    # Buscamos el TipoDTE y el Folio en el XML entrante
    tipo_dte_nodes = tree.xpath("//*[local-name()='TipoDTE']")
    folio_nodes = tree.xpath("//*[local-name()='Folio']")
    
    # Si falta alguno, esta no es responsabilidad de esta regla, 
    # el validador de schema lo agarrará
    if not tipo_dte_nodes or not folio_nodes:
        return issues
        
    tipo_dte = (tipo_dte_nodes[0].text or "").strip()
    folio_str = (folio_nodes[0].text or "").strip()
    
    # El Folio 0 que me comentabas es fatal
    if folio_str == "0":
        issues.append(ValidationIssue(
            code="GENERA_XML",
            field="Folio",
            message=f"El XML tiene Folio 0 para el Tipo Documento {tipo_dte}. Asigne un folio válido antes de enviar.",
            severity="ERROR"
        ))
        return issues
        
    try:
        folio = int(folio_str)
    except ValueError:
        return issues # Folio no numerico, lo atraparía otra regla
        
    # Buscar CAF válido para este documento y folio
    resultado = find_valid_caf(caf_dir, tipo_dte, folio)
    
    if not resultado:
        # Error grave: Están usando un folio que NO está en ninguno de los CAFs de Z:\
        issues.append(ValidationIssue(
            code="GENERA_XML",
            field="Folio",
            message=f"No se encuentra archivo CAF cargado para tipo documento {tipo_dte}, Folio {folio}. Descargue y coloque el CAF oficial en la carpeta: {caf_dir}.",
            severity="ERROR"
        ))
    else:
        # ¡CAF encontrado! Validamos stock restante
        caf_path, restantes, total_caf = resultado
        
        if restantes == 0:
            issues.append(ValidationIssue(
                code="ALERTA_CAF_AGOTADO",
                field="Folio",
                message=f"¡Atención! Este es el ÚLTIMO folio ({folio}) del CAF {caf_path.name}. Urgente solicitar nuevos folios al SII.",
                severity="WARN"
            ))
        else:
            porcentaje_restante = (restantes / total_caf)
            if porcentaje_restante <= alerta_porcentaje:
                issues.append(ValidationIssue(
                    code="ALERTA_CAF_STOCK_BAJO",
                    field="Folio",
                    message=f"Stock bajo para tipo documento {tipo_dte}: Quedan solo {restantes} folios ({porcentaje_restante:.1%} del total) en {caf_path.name}.",
                    severity="WARN"
                ))

    return issues
