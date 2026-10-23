"""Briefing (análisis de la SERP) → borrador → edición con verificación → control de calidad automático."""
import html
import json
import re

from . import ia
from .base import conocimiento, leer, registrar, sitio

ARTICULO = {
    "type": "object",
    "required": ["titulo", "titulo_seo", "meta_description", "resumen", "bloques", "faq", "tags", "foto", "alt_foto"],
    "properties": {
        "titulo": {"type": "string", "description": "H1, máx 70 caracteres"},
        "titulo_seo": {"type": "string", "description": "<title> 45-60 caracteres, keyword al principio, sin marca"},
        "meta_description": {"type": "string", "description": "140-155 caracteres, con la keyword y un motivo para hacer clic"},
        "resumen": {"type": "string", "description": "1-2 frases para el listado del blog"},
        "bloques": {"type": "array", "items": {
            "type": "object", "required": ["tipo", "texto"],
            "properties": {
                "tipo": {"type": "string", "enum": ["p", "h2", "h3", "ul", "ol", "tabla", "cita"]},
                "texto": {"type": "string", "description": "p: HTML simple (<strong>, <em>, <a href>). ul/ol: un elemento por línea. tabla: filas por línea, celdas separadas por ' | ', primera fila = cabecera. Resto: texto plano."}}}},
        "faq": {"type": "array", "items": {"type": "object", "required": ["q", "a"],
                                           "properties": {"q": {"type": "string"}, "a": {"type": "string"}}}},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "2-4 etiquetas del blog"},
        "foto": {"type": "string", "description": "Nombre de archivo de la lista de fotos"},
        "alt_foto": {"type": "string"},
    },
}

BRIEF = {
    "type": "object",
    "required": ["intencion", "respuesta_directa", "que_cubren_los_top", "huecos", "preguntas_reales", "estructura", "palabras_objetivo", "entidades", "fuentes_verificadas"],
    "properties": {
        "intencion": {"type": "string"},
        "respuesta_directa": {"type": "string", "description": "La respuesta correcta a la búsqueda en 2-3 frases"},
        "que_cubren_los_top": {"type": "array", "items": {"type": "string"}},
        "huecos": {"type": "array", "items": {"type": "string"}, "description": "Lo que nadie explica bien y podemos aportar"},
        "preguntas_reales": {"type": "array", "items": {"type": "string"}},
        "estructura": {"type": "array", "items": {"type": "string"}, "description": "H2 propuestos en orden"},
        "palabras_objetivo": {"type": "integer"},
        "entidades": {"type": "array", "items": {"type": "string"}, "description": "Términos/materiales/marcas que un experto mencionaría"},
        "fuentes_verificadas": {"type": "array", "items": {"type": "object", "required": ["url", "dato"],
                                "properties": {"url": {"type": "string"}, "dato": {"type": "string"}}}},
    },
}

EDICION = {
    "type": "object", "required": ["articulo", "puntuacion", "problemas"],
    "properties": {
        "articulo": ARTICULO,
        "puntuacion": {"type": "object", "required": ["utilidad", "rigor", "naturalidad", "seo", "experiencia"],
                       "properties": {k: {"type": "integer", "description": "0-10"} for k in
                                      ["utilidad", "rigor", "naturalidad", "seo", "experiencia"]}},
        "problemas": {"type": "array", "items": {"type": "string"}, "description": "Problemas que quedan tras la edición"},
    },
}

PROHIBIDAS = ["en el mundo de", "hoy en día", "en la actualidad", "cuando se trata de", "en conclusión", "en resumen",
              "en definitiva", "sin lugar a dudas", "cabe destacar", "es importante señalar", "es importante destacar",
              "juega un papel", "adentrarnos", "sumergirnos", "panorama", "un sinfín de", "en el ámbito de", "potenciar",
              "desbloquear", "revolucion", "a la vanguardia", "crucial"]


def _fotos():
    return leer("imagenes.json", {})


def briefing(tema, existentes):
    prompt = f"""Analiza la búsqueda «{tema['keyword']}» (secundarias: {', '.join(tema.get('secundarias', []))}) en Google España.
Público: {sitio()['publico']}. Enfoque sugerido: {tema.get('enfoque', '')}

Busca y lee los 4-6 primeros resultados, "Otras preguntas de los usuarios" y alguna discusión de profesionales. Verifica en fuentes de autoridad (organismos oficiales, fabricantes, revistas, asociaciones profesionales) cualquier dato técnico o cifra que el artículo vaya a necesitar y anótalo con su URL.
Artículos nuestros ya publicados (no repetir; enlazar si encaja): {json.dumps([e['titulo'] for e in existentes], ensure_ascii=False)}"""
    return ia.tarea(f"Eres un analista SEO y experto en el sector de {sitio()['nombre']}: {sitio()['negocio']} Español de España.", prompt, BRIEF, web=True)


def _system():
    s = sitio()
    return f"""Eres {s['autor']}. Escribes el blog de {s['nombre']} ({s['negocio']}) para: {s['publico']}

{conocimiento('estilo.md')}

{conocimiento('voz.md')}

# Hechos de la empresa (únicos que puedes presentar como experiencia propia)
{conocimiento('empresa.md')}"""


def borrador(tema, brief, existentes, variante):
    lista = "\n".join(f"- {e['url']} — {e['titulo']}" for e in existentes)
    usos = {}
    for p in leer("publicados.json", []):
        usos[p.get("foto")] = usos.get(p.get("foto"), 0) + 1
    fotos = "\n".join(f"- {k}: {v['descripcion']} (usada {usos.get(k, 0)} veces)"
                      for k, v in sorted(_fotos().items(), key=lambda kv: usos.get(kv[0], 0)))
    prompt = f"""Escribe el artículo para la búsqueda «{tema['keyword']}».

Briefing (análisis de la competencia y datos verificados):
{json.dumps(brief, ensure_ascii=False, indent=1)}

Lo que el blog ha aprendido que funciona (aplícalo):
{leer('aprendizajes.md', '(aún sin datos)')}

Variante de formato asignada por el experimento en curso (obligatoria): {variante or 'ninguna'}

Enlaces internos posibles (2-4 donde aporten de verdad, con anchor descriptivo):
{lista or '(ninguno aún)'}
Llamada a la acción del cierre: {sitio()['cta']} → {sitio()['contacto_url']}

Fotos reales del laboratorio (elige la que mejor ilustre el tema; a igualdad, la menos usada):
{fotos}

Supera a los resultados actuales: cubre los huecos, responde las preguntas reales y aporta el criterio propio de la empresa. Datos y cifras solo los del briefing con fuente o los de los hechos de la empresa."""
    return ia.tarea(_system(), prompt, ARTICULO, pensar="high")


def editar(tema, brief, articulo, problemas_previos=()):
    prompt = f"""Eres el editor jefe. Revisa y MEJORA este artículo para «{tema['keyword']}» antes de publicarlo sin revisión humana. Tu responsabilidad es que no salga nada falso ni nada que suene a IA.

1. Rigor: elimina cualquier plazo, tiempo de entrega, garantía o condición comercial sobre la empresa que no esté literalmente en sus hechos (revisa también título y meta description). Comprueba con búsqueda web cada afirmación técnica que no esté respaldada por el briefing o por los hechos de la empresa. Corrige o elimina lo que no se sostenga. Nada de estudios, porcentajes o casos inventados.
2. Naturalidad: elimina todo patrón de la lista de prohibidos, rompe estructuras repetitivas, varía ritmo, quita relleno. Debe sonar a un experto con oficio hablando a un colega.
3. SEO: keyword en título SEO, H1, primer párrafo y algún H2 de forma natural; meta 140-155; respuesta directa al principio. FAQ solo si aporta preguntas reales no respondidas en el cuerpo (si no, déjala vacía).
4. Experiencia: que se note el criterio propio de la empresa (decisiones, errores típicos que ve, cómo lo hace).
{('Problemas detectados en la revisión anterior que DEBES resolver: ' + '; '.join(problemas_previos)) if problemas_previos else ''}

Briefing: {json.dumps(brief, ensure_ascii=False)}

Artículo: {json.dumps(articulo, ensure_ascii=False)}

Devuelve el artículo final completo, puntuación honesta 0-10 por criterio y los problemas que queden."""
    return ia.tarea(_system(), prompt, EDICION, web=True, pensar="high")


def control_calidad(a, tema, palabras_min=700):
    """Comprobaciones deterministas. Devuelve lista de fallos (vacía = apto)."""
    texto = " ".join(re.sub(r"<[^>]+>", " ", b["texto"]) for b in a["bloques"])
    bajo = texto.lower()
    fallos = []
    n = len(texto.split())
    if n < palabras_min:
        fallos.append(f"solo {n} palabras")
    for p in PROHIBIDAS:
        if p in bajo:
            fallos.append(f"expresión prohibida: «{p}»")
    if texto.count("—") > 4:
        fallos.append("abuso de rayas (—)")
    if not 120 <= len(a["meta_description"]) <= 160:
        fallos.append(f"meta description de {len(a['meta_description'])} caracteres")
    if len(a["titulo_seo"]) > 65:
        fallos.append("título SEO demasiado largo")
    kw = tema["keyword"].lower().split()
    primer_p = next((b["texto"].lower() for b in a["bloques"] if b["tipo"] == "p"), "")
    if sum(w in primer_p for w in kw) < max(1, len(kw) - 1):
        fallos.append("la keyword no aparece en el primer párrafo")
    if sum(b["tipo"] == "h2" for b in a["bloques"]) < 3:
        fallos.append("menos de 3 H2")
    # promesas de plazo que no están en los hechos de la empresa
    hechos = conocimiento("empresa.md").lower()
    todo = " ".join([bajo, a["titulo"].lower(), a["titulo_seo"].lower(), a["meta_description"].lower()])
    comercial = re.compile(r"entreg|plazo|env[ií]|log[ií]stic|recib|respond|respuesta|devolv|urgen|express|exprés|garant")
    tiempo = re.compile(r"\b\d+\s*(?:[-–a]\s*\d+\s*)?(?:h\b|horas|días|dias|semanas)")
    for frase in re.split(r"[.;:!?\n]", todo):
        if comercial.search(frase):
            for m in tiempo.finditer(frase):
                if m.group(0) not in hechos:
                    fallos.append(f"promesa de plazo no respaldada: «{frase.strip()[:80]}»")
    parrafos = [b["texto"] for b in a["bloques"] if b["tipo"] == "p"]
    if parrafos and sum(1 for p in parrafos if p.strip().startswith("Además")) > 1:
        fallos.append("muletilla «Además» repetida")
    return fallos


CANIBAL = {"type": "object", "required": ["conflicto", "url", "razon"],
           "properties": {"conflicto": {"type": "boolean"}, "url": {"type": "string"}, "razon": {"type": "string"}}}


def canibaliza(tema, existentes):
    """¿Ya existe un artículo que responde a la misma intención de búsqueda? Devuelve (bool, motivo)."""
    from . import gsc
    # 1) Datos: si una página existente ya recibe impresiones por esta keyword, es su terreno
    if gsc.disponible():
        palabras = [w for w in tema["keyword"].lower().split() if len(w) > 3]
        filas = gsc.consulta(["query", "page"], dias=90)
        for f in filas:
            q = f["query"].lower()
            if f["impresiones"] >= 20 and sum(w in q for w in palabras) >= max(2, len(palabras) - 1):
                if any(f["page"].rstrip("/") == e["url"].rstrip("/") for e in existentes):
                    return True, f"«{f['query']}» ya da {f['impresiones']} impresiones a {f['page']}"
    # 2) Juicio semántico contra todos los títulos publicados
    if not existentes:
        return False, ""
    lista = "\n".join(f"- {e['url']} — {e['titulo']}" for e in existentes)
    r = ia.tarea("Eres un editor SEO estricto. Español.",
                 f"""¿El artículo propuesto responde a la MISMA intención de búsqueda que alguno ya publicado (aunque cambie el título o el ángulo local)? Si un lector que buscara la keyword quedaría bien servido por un artículo existente, es conflicto.
Propuesto: keyword «{tema['keyword']}», enfoque: {tema.get('enfoque', '')}
Publicados:
{lista}""", CANIBAL)
    return bool(r["conflicto"]), f"{r['url']}: {r['razon']}"


def escribir(tema, existentes, variante=None):
    brief = briefing(tema, existentes)
    a = borrador(tema, brief, existentes, variante)
    problemas = []
    for intento in range(3):
        ed = editar(tema, brief, a, problemas)
        a = ed["articulo"]
        nota = ed["puntuacion"]
        problemas = control_calidad(a, tema) + ed["problemas"]
        minima = min(nota.values())
        registrar("edicion", slug=tema["slug"], intento=intento + 1, nota_min=minima, problemas=len(problemas))
        if minima >= 8 and not control_calidad(a, tema):
            return a, nota, brief
    raise RuntimeError(f"Calidad insuficiente tras 3 ediciones: {problemas[:6]}")


# ---------- HTML para HubSpot ----------

def _limpiar(s, sitio):
    s = re.sub(r"<(?!/?(strong|em|a)\b)[^>]+>", "", s)

    def a(m):
        href, txt = m.group(1), m.group(2)
        if href.startswith("http") and not href.startswith(sitio):
            return f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{txt}</a>'
        return f'<a href="{html.escape(href)}">{txt}</a>'
    return re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', a, s, flags=re.S)


def a_html(a, sitio):
    out = []
    for b in a["bloques"]:
        t = b["texto"].strip()
        if b["tipo"] in ("h2", "h3"):
            out.append(f"<{b['tipo']}>{html.escape(t)}</{b['tipo']}>")
        elif b["tipo"] in ("ul", "ol"):
            li = "".join(f"<li>{_limpiar(x.strip().lstrip('-•0123456789. '), sitio)}</li>" for x in t.split("\n") if x.strip())
            out.append(f"<{b['tipo']}>{li}</{b['tipo']}>")
        elif b["tipo"] == "tabla":
            filas = [f.split(" | ") for f in t.split("\n") if f.strip()]
            cab = "".join(f"<th>{html.escape(c.strip())}</th>" for c in filas[0])
            cuerpo = "".join("<tr>" + "".join(f"<td>{html.escape(c.strip())}</td>" for c in f) + "</tr>" for f in filas[1:])
            out.append(f'<div style="overflow-x:auto"><table><thead><tr>{cab}</tr></thead><tbody>{cuerpo}</tbody></table></div>')
        elif b["tipo"] == "cita":
            out.append(f"<blockquote>{html.escape(t)}</blockquote>")
        else:
            out.append(f"<p>{_limpiar(t, sitio)}</p>")
    if a["faq"]:
        out.append("<h2>Preguntas frecuentes</h2>")
        for f in a["faq"]:
            out.append(f"<h3>{html.escape(f['q'])}</h3><p>{html.escape(f['a'])}</p>")
    return "\n".join(out)


def palabras(a):
    return len(" ".join(re.sub(r"<[^>]+>", " ", b["texto"]) for b in a["bloques"]).split())
