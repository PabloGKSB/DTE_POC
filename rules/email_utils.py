import logging
import requests

logger = logging.getLogger(__name__)

def enviar_alerta_caf(asunto: str, cuerpo_mensaje: str, cfg: dict):
    """
    Envía un correo de alerta usando la API de Microsoft Graph (OAuth2 Client Credentials).
    cfg debe contener:
      - 'origen': correo origen (buzón desde el que se envía)
      - 'destinatario': correo destino
      - 'client_id': Application (Client) ID de Azure AD
      - 'tenant_id': Directory (Tenant) ID de Azure AD
      - 'client_secret': Secret value de Azure AD
    """
    origen = cfg.get("origen", "")
    destinatario_raw = cfg.get("destinatario", "")
    destinatarios = [d.strip() for d in destinatario_raw.replace(';', ',').split(',') if d.strip()]
    
    client_id = cfg.get("client_id", "")
    tenant_id = cfg.get("tenant_id", "")
    client_secret = cfg.get("client_secret", "")
    
    # Si faltan credenciales de Azure, se cancela para no lanzar errores
    if not all([origen, destinatarios, client_id, tenant_id, client_secret]):
        logger.warning("Configuración de correo incompleta en config.yaml (alertas_email). Falta configuración de Azure / Graph. Omitiendo envío.")
        return

    # 1. Obtener Token OAuth2 de Azure AD
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }

    try:
        logger.info(f"Obteniendo token de Azure AD para la App {client_id}...")
        token_r = requests.post(token_url, data=token_data)
        token_r.raise_for_status()
        
        access_token = token_r.json().get("access_token")
        if not access_token:
            logger.error("No se pudo obtener el access_token de Microsoft Graph. La respuesta fue exitosa pero sin token.")
            return

        # 2. Enviar Correo usando Microsoft Graph
        send_url = f"https://graph.microsoft.com/v1.0/users/{origen}/sendMail"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        email_data = {
            "message": {
                "subject": asunto,
                "body": {
                    "contentType": "Text",
                    "content": cuerpo_mensaje
                },
                "toRecipients": [{"emailAddress": {"address": d}} for d in destinatarios]
            },
            "saveToSentItems": "false" # Puedes cambiar a "true" si quieres guardarlos en "Enviados" de la cuenta
        }
        
        logger.info(f"Token obtenido. Enviando correo vía MS Graph a {', '.join(destinatarios)} desde el buzón de {origen}...")
        send_r = requests.post(send_url, headers=headers, json=email_data)
        send_r.raise_for_status()
        
        logger.info(f"Alerta enviada correctamente a los correos: {', '.join(destinatarios)} usando MS Graph API.")
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"Error HTTP en la API de Microsoft: {e.response.text if hasattr(e, 'response') else e}")
    except Exception as e:
        logger.error(f"Error inesperado al enviar el correo vía Azure/MS Graph: {e}")
