"""Ciclo semanal: medir → experimentos → refrescar → destilar aprendizajes que alimentan al redactor y al estratega."""
import datetime as dt
import json

from . import experimentos, gsc, hubspot, ia, redaccion
from .base import SIMULAR, guardar, leer, registrar, sitio


def medir(publicados):
    """Métricas de los últimos 28 días por artículo + histórico semanal."""
    if not gsc.disponible():
        return []
    fin = dt.date.today() - dt.timedelta(days=3)
    filas = {f["page"]: f for f in gsc.consulta(["page"], dias=28)}
    tabla = []
    for p in publicados:
        m = filas.get(p["url"], {"clics": 0, "impresiones": 0, "ctr": 0, "posicion": None})
        edad = (dt.date.today() - dt.date.fromisoformat(p["publicado"])).days
        tabla.append({k: p.get(k) for k in ("slug", "keyword", "cluster", "intencion", "etapa", "palabras", "h2",
                                            "tablas", "faq", "variante", "titulo_seo")} | {"edad_dias": edad, **m})
    hist = leer("metricas.json", [])
    hist.append({"fecha": fin.isoformat(), "paginas": tabla,
                 "total": {k: sum(t[k] for t in tabla) for k in ("clics", "impresiones")}})
    guardar("metricas.json", hist[-104:])
    return tabla


REFRESCO = {"type": "object", "required": ["bloques_nuevos", "faq_nuevas", "resumen_cambios"],
            "properties": {"bloques_nuevos": redaccion.ARTICULO["properties"]["bloques"],
                           "faq_nuevas": redaccion.ARTICULO["properties"]["faq"],
                           "resumen_cambios": {"type": "string"}}}


def refrescar_uno(publicados, tabla):
    """Amplía el artículo con más potencial (posición 6-20, muchas impresiones) usando sus consultas reales."""
    ya = {r["slug"]: r["fecha"] for r in leer("refrescos.json", [])}
    cand = [t for t in tabla if t["posicion"] and 6 <= t["posicion"] <= 20 and t["impresiones"] >= 50
            and t["edad_dias"] >= 60 and t["slug"] not in ya]
    if not cand:
        return None
    t = max(cand, key=lambda x: x["impresiones"])
    p = next(x for x in publicados if x["slug"] == t["slug"])
    consultas = gsc.consultas_de_pagina(p["url"], dias=56, limite=40)
    actual = "" if SIMULAR else hubspot.obtener(p["post_id"])["postBody"]
    r = ia.tarea(redaccion._system(), f"""Este artículo está en posición {t['posicion']:.1f} para «{p['keyword']}». Para subir, debe responder mejor a las consultas reales por las que Google ya lo muestra:
{[(q['query'], q['impresiones'], round(q['posicion'], 1)) for q in consultas]}

Contenido actual (HTML): {actual[:15000]}

Escribe SOLO las secciones nuevas (H2 + contenido) que cubren las consultas no respondidas y 1-3 FAQ nuevas. Mismo estilo, sin repetir lo que ya está. Verifica los datos técnicos.""",
                 REFRESCO, web=True, max_busquedas=5)
    extra = redaccion.a_html({"bloques": r["bloques_nuevos"], "faq": []}, sitio()["url"])
    faq = "".join(f"<h3>{f['q']}</h3><p>{f['a']}</p>" for f in r["faq_nuevas"])
    if not SIMULAR:
        cuerpo = actual.replace("<h2>Preguntas frecuentes</h2>", extra + "\n<h2>Preguntas frecuentes</h2>", 1) \
            if "<h2>Preguntas frecuentes</h2>" in actual else actual + extra
        cuerpo += faq
        hubspot.actualizar_en_vivo(p["post_id"], {"postBody": cuerpo})
    refs = leer("refrescos.json", [])
    refs.append({"slug": p["slug"], "fecha": dt.date.today().isoformat(), "posicion_antes": t["posicion"],
                 "impresiones_antes": t["impresiones"], "cambios": r["resumen_cambios"]})
    guardar("refrescos.json", refs)
    registrar("refresco", slug=p["slug"], posicion=round(t["posicion"], 1))
    return p["slug"]


DESTILADO = {
    "type": "object", "required": ["aprendizajes_md", "ajuste_clusters", "nuevas_hipotesis"],
    "properties": {
        "aprendizajes_md": {"type": "string", "description": "Reglas accionables en markdown, cada una con evidencia y nivel de confianza (alta/media/baja). Máx 40 líneas."},
        "ajuste_clusters": {"type": "object", "additionalProperties": {"type": "number"},
                            "description": "Multiplicador de prioridad por cluster (0.5-1.5)"},
        "nuevas_hipotesis": {"type": "array", "items": {"type": "object", "required": ["nombre", "A", "B"],
                             "properties": {"nombre": {"type": "string"}, "A": {"type": "string"}, "B": {"type": "string"}}},
                             "description": "0-2 hipótesis de formato a testar después, si los datos sugieren alguna"},
    },
}


def destilar(tabla):
    st = experimentos._estado()
    fmt = experimentos._fmt()
    hist_total = [h["total"] | {"fecha": h["fecha"]} for h in leer("metricas.json", [])][-12:]
    r = ia.tarea("Eres un analista SEO riguroso. No confundes correlación con causalidad y con pocos datos lo dices.",
                 f"""Analiza el rendimiento del blog de {sitio()['nombre']} (objetivo: {sitio()['objetivo']}) y actualiza las reglas de redacción y estrategia.

Métricas por artículo (últimos 28 días): {json.dumps(tabla, ensure_ascii=False)}
Evolución semanal total: {json.dumps(hist_total)}
Experimentos de formato (compartidos entre todos los sitios del piloto): {json.dumps(fmt['historial'][-6:], ensure_ascii=False)}
Experimentos de títulos en este sitio: {json.dumps(st['historial'][-4:], ensure_ascii=False)[:6000]}
Refrescos de contenido: {json.dumps(leer('refrescos.json', [])[-10:], ensure_ascii=False)}
Aprendizajes vigentes: {leer('aprendizajes.md', '(ninguno)')}
Hipótesis ya en cola: {[h['nombre'] for h in fmt['cola']]}

Reglas: compara artículos de edad similar (los de menos de 30 días aún no son evaluables). Mantén una regla vigente salvo que los datos la contradigan. Las conclusiones de experimentos con p<0,05 tienen confianza alta; patrones observacionales, media o baja.""",
                 DESTILADO)
    guardar("aprendizajes.md", r["aprendizajes_md"])
    temas = leer("temas.json", [])
    for t in temas:
        if t["estado"] == "pendiente" and t.get("cluster") in r["ajuste_clusters"]:
            t["prioridad"] = round(min(100, t["prioridad"] * r["ajuste_clusters"][t["cluster"]]))
    temas.sort(key=lambda t: (t["estado"] != "pendiente", -t.get("prioridad", 0)))
    guardar("temas.json", temas)
    nombres = {h["nombre"] for h in fmt["cola"]} | {h["nombre"] for h in fmt["historial"]} | {(fmt["activo"] or {}).get("nombre")}
    fmt["cola"] += [h for h in r["nuevas_hipotesis"] if h["nombre"] not in nombres]
    experimentos._guardar_fmt(fmt)
    registrar("aprendizaje", clusters=len(r["ajuste_clusters"]), hipotesis=len(r["nuevas_hipotesis"]))


def ciclo():
    publicados = leer("publicados.json", [])
    reales = [p for p in publicados if not p.get("simulado")]
    tabla = medir(reales)
    experimentos.evaluar_snippet()
    experimentos.iniciar_snippet(reales)
    if tabla:
        refrescar_uno(reales, tabla)
        destilar(tabla)
