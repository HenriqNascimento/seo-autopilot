"""Contactos (leads): el objetivo supremo. Qué artículos traen personas cualificadas que dejan sus datos.

Fuentes por sitio (sitio.json → "leads"):
- "cloudflare_kv": registro del Worker de la web (claves lead:* y ev:*), sin datos personales.
- "hubspot": contactos del CRM con su página de entrada y fuente (scope crm.objects.contacts.read).

Cada contacto nuevo se califica UNA vez con IA usando solo datos de negocio (nunca nombre, email ni teléfono)
y se guarda en estado/leads.json como {id, fecha, origen (slug del artículo o ""), fuente, cualificado, motivo}.
"""
import datetime as dt
import os
import urllib.parse

from . import ia
from .base import guardar, http, leer, registrar, requerido, sitio

CALIFICA = {"type": "object", "required": ["cualificado", "motivo"],
            "properties": {"cualificado": {"type": "boolean"}, "motivo": {"type": "string", "description": "Una frase"}}}


def disponible():
    cfg = sitio().get("leads") or {}
    if cfg.get("tipo") == "cloudflare_kv":
        return all(os.environ.get(cfg[k]) for k in ("cuenta_env", "ns_env", "token_env"))
    if cfg.get("tipo") == "hubspot":
        return bool(os.environ.get(sitio()["publicador"].get("token_env", "")))
    return False


# ---------- lectura de fuentes ----------

def _kv():
    cfg = sitio()["leads"]
    base = (f"https://api.cloudflare.com/client/v4/accounts/{requerido(cfg['cuenta_env'])}"
            f"/storage/kv/namespaces/{requerido(cfg['ns_env'])}")
    return base, {"authorization": f"Bearer {requerido(cfg['token_env'])}"}


def _kv_claves(prefijo):
    base, h = _kv()
    claves, cursor = [], ""
    while True:
        r = http("GET", f"{base}/keys?prefix={urllib.parse.quote(prefijo)}&limit=1000" + (f"&cursor={cursor}" if cursor else ""), cabeceras=h)
        claves += [k["name"] for k in r.get("result", [])]
        cursor = (r.get("result_info") or {}).get("cursor")
        if not cursor:
            return claves


def _kv_valor(clave):
    base, h = _kv()
    return http("GET", f"{base}/values/{urllib.parse.quote(clave, safe='')}", cabeceras=h, crudo=True).decode("utf-8")


def _nuevos_cloudflare(conocidos):
    import json
    out = []
    for k in _kv_claves("lead:"):
        if k in conocidos:
            continue
        r = json.loads(_kv_valor(k))
        datos_negocio = {c: r.get(c) for c in ("negocio", "sector", "ciudad", "tiene_web", "busqueda", "puntuacion", "pais", "formulario")}
        out.append({"id": k, "fecha": r["t"][:10], "origen": r.get("origen", ""),
                    "fuente": r.get("utm_source") or r.get("referrer") or "directo", "negocio": datos_negocio})
    return out


def _nuevos_hubspot(conocidos):
    from . import hubspot
    desde = int((dt.datetime.now() - dt.timedelta(days=120)).timestamp() * 1000)
    cuerpo = {"filterGroups": [{"filters": [{"propertyName": "createdate", "operator": "GTE", "value": str(desde)}]}],
              "properties": ["createdate", "hs_analytics_source", "hs_analytics_source_data_1", "hs_analytics_first_url",
                             "company", "jobtitle", "email", "city"],
              "limit": 100}
    r = http("POST", hubspot.API + "/crm/v3/objects/contacts/search", cuerpo, hubspot._h())
    prefijo = sitio().get("blog_ruta", "/blog")
    out = []
    for c in r.get("results", []):
        cid = f"hs:{c['id']}"
        if cid in conocidos:
            continue
        p = c.get("properties", {})
        ruta = urllib.parse.urlparse(p.get("hs_analytics_first_url") or "").path
        origen = ruta.rstrip("/").rsplit("/", 1)[-1] if ruta.startswith(prefijo + "/") else ""
        dominio = (p.get("email") or "").split("@")[-1].lower()
        personal = dominio in ("gmail.com", "hotmail.com", "outlook.com", "yahoo.es", "yahoo.com", "icloud.com", "live.com", "hotmail.es")
        out.append({"id": cid, "fecha": (p.get("createdate") or "")[:10], "origen": origen,
                    "fuente": (p.get("hs_analytics_source") or "").lower() or "desconocida",
                    # solo datos de negocio para calificar; el email no se guarda
                    "negocio": {"empresa": p.get("company"), "cargo": p.get("jobtitle"), "ciudad": p.get("city"),
                                "email_corporativo": bool(dominio) and not personal,
                                "dominio": dominio if dominio and not personal else "",
                                "pagina_entrada": ruta}})
    return out


# ---------- calificación y agregados ----------

def actualizar():
    """Trae contactos nuevos, los califica y devuelve la lista completa guardada."""
    if not disponible():
        return leer("leads.json", [])
    guardados = leer("leads.json", [])
    conocidos = {x["id"] for x in guardados}
    tipo = sitio()["leads"]["tipo"]
    nuevos = _nuevos_cloudflare(conocidos) if tipo == "cloudflare_kv" else _nuevos_hubspot(conocidos)
    s = sitio()
    for n in nuevos:
        r = ia.tarea("Calificas contactos comerciales con criterio realista. Español.",
                     f"""¿Este contacto es un cliente potencial cualificado para {s['nombre']}?
Negocio: {s['negocio']}
Cliente ideal: {s['publico']}
Datos del contacto (sin datos personales): {n['negocio']}
Cualificado = encaja con el cliente ideal y podría contratar. No cualificado = spam, pruebas, estudiantes, proveedores, competidores, fuera de mercado.""",
                     CALIFICA)
        n["cualificado"], n["motivo"] = bool(r["cualificado"]), r["motivo"][:200]
        n.pop("negocio", None)  # no se guarda nada más que la calificación
        guardados.append(n)
    if nuevos:
        registrar("leads_nuevos", total=len(nuevos), cualificados=sum(n["cualificado"] for n in nuevos))
    guardar("leads.json", guardados)
    return guardados


def clics_cta(dias=28):
    """Clics en las llamadas a la acción por artículo (solo webs con contador propio)."""
    if (sitio().get("leads") or {}).get("tipo") != "cloudflare_kv" or not disponible():
        return {}
    limite = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
    out = {}
    for k in _kv_claves("ev:"):
        _, fecha, tipo, origen = k.split(":", 3)
        if tipo == "cta" and fecha >= limite:
            out[origen] = out.get(origen, 0) + int(_kv_valor(k) or 0)
    return out


def por_articulo(leads, dias=None):
    """{slug: {"leads": n, "cualificados": n}} (opcionalmente solo los últimos `dias`)."""
    limite = (dt.date.today() - dt.timedelta(days=dias)).isoformat() if dias else ""
    out = {}
    for x in leads:
        if x["fecha"] < limite:
            continue
        o = out.setdefault(x["origen"] or "(sin artículo)", {"leads": 0, "cualificados": 0})
        o["leads"] += 1
        o["cualificados"] += int(x["cualificado"])
    return out
