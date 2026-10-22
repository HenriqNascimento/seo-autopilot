"""Llamadas a Gemini (API de Google AI Studio). Cada tarea devuelve un JSON que cumple el esquema dado.

Con web=True el modelo puede buscar en Google (grounding) y leer URLs (url_context).
"""
import json
import os
import re

from .base import MODELO, guardar, http, leer, registrar, requerido, sitio

URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
# Precios por 1M tokens (hasta 31/12/2026; Flash duplica en 2027) y por búsqueda tras las 5.000 gratis/mes
PRECIOS = {"gemini-3.8-flash": (0.75, 3.75), "gemini-3.6-flash": (0.75, 3.75), "gemini-3.5-flash-lite": (0.30, 2.50),
           "gemini-3.1-pro-preview": (2.00, 12.00)}

_coste = {"entrada": 0, "salida": 0, "busquedas": 0}


def _extraer_json(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


PRESUPUESTO = float(os.environ.get("PRESUPUESTO_USD_MES", "9"))  # total, por debajo de los 10 USD de Google AI Pro


class PresupuestoAgotado(Exception):
    pass


def _mes():
    import datetime as dt
    return dt.date.today().strftime("%Y-%m")


def gasto_mes(sid=None):
    """Gasto del mes: total (sid=None) o de un sitio."""
    g = leer("gasto.json", {}, global_=True).get(_mes(), {})
    return g.get(sid, 0.0) if sid else sum(g.values())


def guardar_gasto():
    """Suma lo gastado en esta sesión al sitio activo y reinicia el contador."""
    if not coste_usd():
        return
    g = leer("gasto.json", {}, global_=True)
    m = g.setdefault(_mes(), {})
    sid = sitio()["id"]
    m[sid] = round(m.get(sid, 0.0) + coste_usd(), 4)
    guardar("gasto.json", g, global_=True)
    registrar("coste", usd=coste_usd(), modelo=MODELO, **_coste)
    for k in _coste:
        _coste[k] = 0


def _llamar(cuerpo, modelo):
    s = sitio()
    if gasto_mes() + coste_usd() >= PRESUPUESTO:
        raise PresupuestoAgotado(f"Presupuesto total de {PRESUPUESTO} USD/mes alcanzado.")
    if gasto_mes(s["id"]) + coste_usd() >= s.get("presupuesto_usd_mes", PRESUPUESTO):
        raise PresupuestoAgotado(f"Presupuesto de {s['nombre']} ({s['presupuesto_usd_mes']} USD/mes) alcanzado.")
    r = http("POST", URL.format(modelo), cuerpo, {"x-goog-api-key": requerido("GEMINI_API_KEY")}, timeout=900)
    u = r.get("usageMetadata", {})
    _coste["entrada"] += u.get("promptTokenCount", 0) + u.get("toolUsePromptTokenCount", 0)
    _coste["salida"] += u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
    cand = (r.get("candidates") or [{}])[0]
    _coste["busquedas"] += len((cand.get("groundingMetadata") or {}).get("webSearchQueries", []))
    partes = (cand.get("content") or {}).get("parts", [])
    texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
    if not texto:
        raise RuntimeError(f"Respuesta vacía de Gemini (finishReason={cand.get('finishReason')})")
    return texto


def tarea(system, prompt, esquema, web=False, pensar="low", max_tokens=32000, modelo=None, **_):
    """Ejecuta una tarea y devuelve el dict. pensar: low | high (más calidad, más coste)."""
    modelo = modelo or MODELO
    cuerpo = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingLevel": pensar},
                             "responseMimeType": "application/json", "responseJsonSchema": esquema},
    }
    if web:
        cuerpo["tools"] = [{"google_search": {}}, {"url_context": {}}]
    try:
        texto = _llamar(cuerpo, modelo)
    except RuntimeError as e:
        if " 400:" not in str(e):
            raise
        # Plan B si el modelo no admite esquema + herramientas a la vez: esquema en el prompt
        del cuerpo["generationConfig"]["responseMimeType"], cuerpo["generationConfig"]["responseJsonSchema"]
        cuerpo["contents"][0]["parts"][0]["text"] += (
            "\n\nResponde SOLO con un objeto JSON válido que cumpla este JSON Schema, sin texto adicional:\n"
            + json.dumps(esquema, ensure_ascii=False))
        texto = _llamar(cuerpo, modelo)
    datos = _extraer_json(texto)
    faltan = [k for k in esquema.get("required", []) if k not in datos]
    if faltan:
        raise RuntimeError(f"Gemini no devolvió los campos {faltan}")
    return datos


def coste_usd():
    """Coste aproximado. Las búsquedas son gratis hasta 5.000/mes (no se cuentan aquí)."""
    pe, ps = PRECIOS.get(MODELO, (0.75, 3.75))
    return round(_coste["entrada"] * pe / 1e6 + _coste["salida"] * ps / 1e6, 4)

