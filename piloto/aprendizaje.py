"""Ciclo semanal: medir → experimentos → refrescar → destilar aprendizajes que alimentan al redactor y al estratega."""
import datetime as dt
import json

from . import experimentos, gsc, hubspot, ia, leads, redaccion
from .cms import cms
from .base import SIMULAR, guardar, leer, registrar, sitio


def medir(publicados, lista_leads=None):
    """Métricas por artículo: contactos (objetivo principal), clics en CTA y Search Console (28 días)."""
    if not gsc.disponible():
        return []
    fin = dt.date.today() - dt.timedelta(days=3)
    filas = {f["page"].rstrip("/"): f for f in gsc.consulta(["page"], dias=28)}
    lista_leads = lista_leads or []
    l_total, l_28 = leads.por_articulo(lista_leads), leads.por_articulo(lista_leads, 28)
    try:
        cta = leads.clics_cta(28)
    except Exception as e:
        registrar("error_cta", motivo=str(e)[:200])
        cta = {}
    tabla = []
    for p in publicados:
        m = filas.get(p["url"].rstrip("/"), {"clics": 0, "impresiones": 0, "ctr": 0, "posicion": None})
        edad = (dt.date.today() - dt.date.fromisoformat(p["publicado"])).days
        s = p["slug"]
        tabla.append({k: p.get(k) for k in ("slug", "keyword", "cluster", "intencion", "etapa", "palabras", "h2",
                                            "tablas", "faq", "variante", "titulo_seo")}
                     | {"edad_dias": edad, **m,
                        "leads_cualificados_total": l_total.get(s, {}).get("cualificados", 0),
                        "leads_total": l_total.get(s, {}).get("leads", 0),
                        "leads_cualificados_28d": l_28.get(s, {}).get("cualificados", 0),
                        "clics_cta_28d": cta.get(s, 0)})
    hist = leer("metricas.json", [])
    total_28 = leads.por_articulo([x | {"origen": "todo"} for x in lista_leads], 28).get("todo", {"leads": 0, "cualificados": 0})
    hist.append({"fecha": fin.isoformat(), "paginas": tabla,
                 "total": {k: sum(t[k] for t in tabla) for k in ("clics", "impresiones")}
                 | {"leads_28d_sitio": total_28["leads"], "leads_cualificados_28d_sitio": total_28["cualificados"],
                    "leads_cualificados_28d_desde_blog": sum(t["leads_cualificados_28d"] for t in tabla),
                    "articulos_semana": frecuencia_actual()}})
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
    actual = "" if SIMULAR else cms().obtener(p["post_id"])["postBody"]
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
        cms().actualizar_en_vivo(p["post_id"], {"postBody": cuerpo})
    refs = leer("refrescos.json", [])
    refs.append({"slug": p["slug"], "fecha": dt.date.today().isoformat(), "posicion_antes": t["posicion"],
                 "impresiones_antes": t["impresiones"], "cambios": r["resumen_cambios"]})
    guardar("refrescos.json", refs)
    registrar("refresco", slug=p["slug"], posicion=round(t["posicion"], 1))
    return p["slug"]


DESTILADO = {
    "type": "object", "required": ["aprendizajes_md", "ajuste_clusters", "nuevas_hipotesis", "frecuencia_recomendada", "motivo_frecuencia"],
    "properties": {
        "aprendizajes_md": {"type": "string", "description": "Reglas accionables en markdown, cada una con evidencia y nivel de confianza (alta/media/baja). Máx 40 líneas."},
        "ajuste_clusters": {"type": "object", "additionalProperties": {"type": "number"},
                            "description": "Multiplicador de prioridad por cluster (0.5-1.5)"},
        "nuevas_hipotesis": {"type": "array", "items": {"type": "object", "required": ["nombre", "A", "B"],
                             "properties": {"nombre": {"type": "string"}, "A": {"type": "string"}, "B": {"type": "string"}}},
                             "description": "0-2 hipótesis de formato a testar después, si los datos sugieren alguna"},
        "frecuencia_recomendada": {"type": "integer", "description": "Artículos por semana recomendados"},
        "motivo_frecuencia": {"type": "string"},
    },
}


def frecuencia_actual():
    s = sitio()
    if s.get("dias_publicacion"):
        return len(s["dias_publicacion"])
    return leer("frecuencia.json", {}).get("articulos_semana", s.get("articulos_semana", 3))


def ajustar_frecuencia(recomendada, motivo):
    """Aplica la recomendación con prudencia: solo sitios con frecuencia_auto, ±1 como mucho cada 28 días.
    Los sitios con días fijos (decididos por el dueño) solo registran la recomendación."""
    s = sitio()
    actual = frecuencia_actual()
    f = leer("frecuencia.json", {})
    f["recomendacion"] = {"fecha": dt.date.today().isoformat(), "valor": recomendada, "motivo": motivo[:400]}
    auto = s.get("frecuencia_auto")
    ultimo = f.get("ultimo_cambio")
    if auto and not s.get("dias_publicacion") and recomendada != actual and \
            (not ultimo or (dt.date.today() - dt.date.fromisoformat(ultimo)).days >= 28):
        nuevo = max(auto["min"], min(auto["max"], actual + (1 if recomendada > actual else -1)))
        if nuevo != actual:
            f.update(articulos_semana=nuevo, ultimo_cambio=dt.date.today().isoformat())
            registrar("frecuencia_cambiada", de=actual, a=nuevo, motivo=motivo[:200])
    guardar("frecuencia.json", f)


def destilar(tabla):
    st = experimentos._estado()
    fmt = experimentos._fmt()
    hist_total = [h["total"] | {"fecha": h["fecha"]} for h in leer("metricas.json", [])][-12:]
    r = ia.tarea("Eres un analista SEO riguroso. No confundes correlación con causalidad y con pocos datos lo dices.",
                 f"""Analiza el rendimiento del blog de {sitio()['nombre']} (objetivo: {sitio()['objetivo']}) y actualiza las reglas de redacción y estrategia.

OBJETIVO SUPREMO: contactos cualificados (personas que encajan con el cliente ideal y dejan sus datos). Jerarquía de métricas: contactos cualificados > clics en la llamada a la acción > clics orgánicos > impresiones. Un artículo con pocas visitas pero contactos vale más que uno con muchas visitas sin contactos. Los contactos son escasos: con pocos casos, trátalos como indicio, no como prueba.

Métricas por artículo (Search Console de 28 días, contactos y clics en CTA): {json.dumps(tabla, ensure_ascii=False)}
Frecuencia actual: {frecuencia_actual()} artículos/semana. Presupuesto IA: {sitio().get('presupuesto_usd_mes')} USD/mes (≈0,15-0,20 USD por artículo).
Evolución semanal total: {json.dumps(hist_total)}
Experimentos de formato (compartidos entre todos los sitios del piloto): {json.dumps(fmt['historial'][-6:], ensure_ascii=False)}
Experimentos de títulos en este sitio: {json.dumps(st['historial'][-4:], ensure_ascii=False)[:6000]}
Refrescos de contenido: {json.dumps(leer('refrescos.json', [])[-10:], ensure_ascii=False)}
Aprendizajes vigentes: {leer('aprendizajes.md', '(ninguno)')}
Hipótesis ya en cola: {[h['nombre'] for h in fmt['cola']]}

Frecuencia: recomienda cuántos artículos/semana publicar. Sube si los artículos recientes se indexan y ganan impresiones o contactos y hay temas de calidad en cola; baja si los nuevos no se indexan, canibalizan, la cola se agota o la calidad cae. Con menos de 8 semanas de datos, mantén la actual. No es un experimento causal: dilo en el motivo.
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
    ajustar_frecuencia(int(r["frecuencia_recomendada"]), r["motivo_frecuencia"])
    registrar("aprendizaje", clusters=len(r["ajuste_clusters"]), hipotesis=len(r["nuevas_hipotesis"]),
              frecuencia_recomendada=r["frecuencia_recomendada"])


def ciclo():
    publicados = leer("publicados.json", [])
    reales = [p for p in publicados if not p.get("simulado") and not p.get("borrador")]
    try:
        lista_leads = leads.actualizar()
    except Exception as e:  # una fuente de contactos caída no para el ciclo
        registrar("error_leads", motivo=str(e)[:300])
        lista_leads = leer("leads.json", [])
    tabla = medir(reales, lista_leads)
    experimentos.evaluar_snippet()
    experimentos.iniciar_snippet(reales)
    if tabla:
        refrescar_uno(reales, tabla)
        destilar(tabla)
