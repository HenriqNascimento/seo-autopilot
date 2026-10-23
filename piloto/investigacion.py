"""Descubre qué busca el público de cada sitio.

Fuentes, todas autorizadas: Search Console (API oficial) y Gemini con grounding de Google Search
(API oficial de pago). No se consulta ni se raspa la Búsqueda de Google directamente.
"""
import json
import random

from . import gsc, ia
from .base import conocimiento, guardar, leer, registrar, sitio


def oportunidades_gsc():
    """Consultas con impresiones donde el sitio aún no está bien posicionado: demanda real medida."""
    if not gsc.disponible():
        return []
    filas = gsc.consulta(["query", "page"], dias=90)
    return sorted([f for f in filas if f["impresiones"] >= 10 and f["posicion"] > 7],
                  key=lambda f: -f["impresiones"])[:80]


ESQUEMA = {
    "type": "object", "required": ["temas"],
    "properties": {"temas": {"type": "array", "items": {
        "type": "object",
        "required": ["slug", "keyword", "secundarias", "intencion", "etapa", "cluster", "prioridad", "por_que", "enfoque"],
        "properties": {
            "slug": {"type": "string", "description": "kebab-case sin tildes, máx 60"},
            "keyword": {"type": "string"},
            "secundarias": {"type": "array", "items": {"type": "string"}},
            "intencion": {"type": "string", "enum": ["informativa", "comparativa", "procedimiento", "comercial", "local"]},
            "etapa": {"type": "string", "enum": ["descubrimiento", "consideracion", "decision"],
                      "description": "Etapa del embudo respecto al objetivo del sitio"},
            "cluster": {"type": "string", "description": "Grupo temático corto en kebab-case"},
            "prioridad": {"type": "integer", "description": "1-100: demanda × probabilidad de rankear × cercanía al objetivo"},
            "por_que": {"type": "string", "description": "Evidencia concreta: qué viste en Google/foros/GSC"},
            "enfoque": {"type": "string", "description": "Ángulo diferencial frente a lo que ya rankea"},
        }}}},
}


def investigar(n_temas=15):
    s = sitio()
    temas = leer("temas.json", [])
    publicados = leer("publicados.json", [])
    from .publicacion import existentes
    ya = [t["keyword"] for t in temas] + [p["keyword"] for p in publicados] + [e["titulo"] for e in existentes()]
    semillas = random.sample(s["semillas"], min(10, len(s["semillas"])))
    prompt = f"""Eres el estratega SEO de {s['nombre']} ({s['url']}).
Negocio: {s['negocio']}
Público: {s['publico']}
Objetivo de negocio del blog: {s['objetivo']}

Propón {n_temas} temas NUEVOS de artículo con la mayor probabilidad de traer tráfico cualificado que acabe en ese objetivo.

1. Investiga con Google Search a partir de estas semillas (y de lo que descubras): {', '.join(semillas)}
   - Qué preguntas hace realmente este público (búsquedas relacionadas, "Otras preguntas de los usuarios", foros y grupos profesionales, Reddit, medios del sector).
   - Para las candidatas más prometedoras, qué rankea hoy en Google España: resultados débiles, genéricos o antiguos = oportunidad; dominan portales enormes = baja la prioridad.
2. Consultas de Search Console donde el sitio ya aparece pero mal posicionado (query, página, impresiones, posición):
{json.dumps(oportunidades_gsc()[:60], ensure_ascii=False)}
3. Lo aprendido hasta ahora en este sitio:
{leer('aprendizajes.md', '(aún sin datos)')}
4. Lo que hace la empresa (los temas deben conectar con ello):
{conocimiento('empresa.md')[:3500]}
5. Artículos ya publicados y temas en cola: NO propongas nada que responda a la misma intención de búsqueda que alguno de ellos (ni con sinónimos, ni con un ángulo local o un título distinto):
{json.dumps(ya, ensure_ascii=False)}

Prioriza long-tail con intención clara. Mezcla etapas del embudo, con peso en las cercanas al objetivo."""
    r = ia.tarea("Eres un estratega SEO meticuloso y basado en datos. Respondes en español.", prompt, ESQUEMA, web=True)
    claves = {t["slug"] for t in temas} | {p["slug"] for p in publicados}
    nuevos = 0
    for t in r["temas"]:
        if t["slug"] in claves:
            continue
        t["estado"] = "pendiente"
        temas.append(t)
        nuevos += 1
    temas.sort(key=lambda t: (t["estado"] != "pendiente", -t.get("prioridad", 0)))
    guardar("temas.json", temas)
    registrar("investigacion", nuevos=nuevos, en_cola=sum(t["estado"] == "pendiente" for t in temas))
    return nuevos
