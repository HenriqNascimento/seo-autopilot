"""Google Search Console (una cuenta de servicio con acceso de lectura a cada propiedad)."""
import datetime as dt
import json
import os
import urllib.parse

from .base import http, requerido, sitio

_token = None


def _auth():
    global _token
    if _token is None:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        info = json.loads(requerido("GSC_CREDENCIALES"))
        cred = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        cred.refresh(Request())
        _token = cred.token
    return {"authorization": f"Bearer {_token}"}


def disponible():
    return bool(os.environ.get("GSC_CREDENCIALES"))


def consulta(dimensiones, dias=28, fin_hace=3, filtros=None, limite=5000, inicio=None, fin=None):
    """Filas de Search Analytics. GSC tarda ~3 días en consolidar datos, por eso fin_hace=3."""
    fin = fin or dt.date.today() - dt.timedelta(days=fin_hace)
    inicio = inicio or fin - dt.timedelta(days=dias - 1)
    cuerpo = {"startDate": str(inicio), "endDate": str(fin), "dimensions": dimensiones, "rowLimit": limite}
    if filtros:
        cuerpo["dimensionFilterGroups"] = [{"filters": filtros}]
    prop = urllib.parse.quote(sitio()["gsc_sitio"], safe="")
    filas = http("POST", f"https://www.googleapis.com/webmasters/v3/sites/{prop}/searchAnalytics/query", cuerpo, _auth()).get("rows", [])
    return [{**{d: f["keys"][i] for i, d in enumerate(dimensiones)},
             "clics": f["clicks"], "impresiones": f["impressions"], "ctr": f["ctr"], "posicion": f["position"]}
            for f in filas]


def _pagina(url):
    return [{"dimension": "page", "operator": "equals", "expression": url}]


def metricas_pagina(url, inicio, fin):
    f = consulta([], filtros=_pagina(url), inicio=inicio, fin=fin)
    return f[0] if f else {"clics": 0, "impresiones": 0, "ctr": 0, "posicion": None}


def consultas_de_pagina(url, dias=28, limite=25, inicio=None, fin=None):
    filas = consulta(["query"], dias=dias, filtros=_pagina(url), inicio=inicio, fin=fin)
    return sorted(filas, key=lambda x: -x["impresiones"])[:limite]


def ultimo_rastreo(url):
    """Fecha del último rastreo de Google (URL Inspection API) o None."""
    r = http("POST", "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
             {"inspectionUrl": url, "siteUrl": sitio()["gsc_sitio"]}, _auth())
    t = (((r.get("inspectionResult") or {}).get("indexStatusResult") or {}).get("lastCrawlTime"))
    return dt.date.fromisoformat(t[:10]) if t else None


def curva_ctr(dias=90):
    """CTR medio del propio sitio por posición redondeada (1-20), para ajustar CTR por posición."""
    filas = consulta(["query", "page"], dias=dias)
    acc = {}
    for f in filas:
        p = min(20, max(1, round(f["posicion"])))
        c, i = acc.get(p, (0, 0))
        acc[p] = (c + f["clics"], i + f["impresiones"])
    defecto = {1: .28, 2: .16, 3: .11, 4: .08, 5: .06, 6: .05, 7: .04, 8: .035, 9: .03, 10: .025}
    return {p: (acc[p][0] / acc[p][1] if p in acc and acc[p][1] >= 200 else defecto.get(p, 0.015)) for p in range(1, 21)}
