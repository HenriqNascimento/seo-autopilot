"""Experimentos SEO, diseñados para no confundir el efecto con el tema, la demanda o la época.

1. FORMATO (artículos nuevos, compartido entre todos los sitios para tener más potencia)
   - Aleatorización estratificada por sitio + cluster: dentro de cada grupo temático se alterna A/B, y A y B
     se publican intercalados en el mismo periodo (misma estacionalidad).
   - Resultado medido en la misma ventana de edad para todos (días 14-70 tras publicar).
   - Ajuste por demanda: se usa la prioridad estimada del tema como covariable (residuos de una OLS).
   - Test de permutación estratificado (las etiquetas solo se permutan dentro de cada cluster).
   - Análisis secuencial: solo se mira en 3 puntos fijos (12, 20 y 30 artículos por brazo) con el
     umbral de Pocock (p < 0,022 en cada mirada) para que el error total quede en ~5 %. Mirar cada
     domingo sin corrección inflaría los falsos positivos.
   - Potencia: se calcula el efecto mínimo detectable (MDE). Solo se concluye "sin efecto" si el MDE
     es ≤ 30 %; con pocos datos se sigue recogiendo, y se cierra como "no concluyente" al llegar al máximo.

2. SNIPPET (título + meta de artículos existentes)
   - Pares emparejados por impresiones; dentro de cada par, una página test y otra control al azar.
   - La ventana "después" empieza cuando la URL Inspection API confirma que Google ha vuelto a rastrear
     la página test (si no la rastrea en 21 días, se revierte y se excluye).
   - Métrica: clics observados / clics esperados por posición, sobre el MISMO conjunto de consultas
     antes y después, usando la curva de CTR del propio sitio. Así no cuenta como mejora un cambio
     de posición o de mezcla de consultas.
   - Diferencia en diferencias test vs control; se exigen datos mínimos; si la posición cambia > 1,5,
     el par no cuenta. Lo que no mejora se revierte.
   - Límite conocido: Google puede mostrar otro título distinto del <title>; la API no lo informa.
     Se mitiga con títulos ≤ 60 caracteres coherentes con el H1.
"""
import datetime as dt
import math
import random
import statistics

from . import gsc, hubspot, ia
from .cms import cms
from .base import SIMULAR, activar, guardar, leer, registrar, sitio

HIPOTESIS_INICIALES = [
    {"nombre": "longitud", "A": "Extensión 1000-1300 palabras, directo al grano.",
     "B": "Extensión 1900-2400 palabras, cobertura exhaustiva del tema."},
    {"nombre": "tabla", "A": "Sin tablas.", "B": "Incluye una tabla comparativa o de especificaciones."},
    {"nombre": "titulo", "A": "Título SEO en forma de afirmación con beneficio concreto.",
     "B": "Título SEO en forma de pregunta tal como la buscaría el lector."},
]
MIRADAS = (12, 20, 30)     # artículos medibles por brazo en los que se evalúa
MAX_POR_BRAZO = MIRADAS[-1]
VENTANA = (14, 70)          # días tras publicar en los que se mide el formato
MDE_OBJETIVO = 0.30         # efecto mínimo que nos importa detectar (30 % de impresiones)
MIN_IMPRESIONES = 1500      # impresiones totales mínimas en el experimento para evaluarlo
ALFA = 0.022                # Pocock, 3 miradas → ~5 % de error total
Z = 2.290 + 0.842           # z de 0,022 bilateral + potencia 80 %
DIAS_SNIPPET = 28
MAX_ESPERA_RASTREO = 21


def _hoy():
    return dt.date.today()


def _estado():
    """Experimentos de snippet del sitio activo."""
    return leer("experimentos.json", {"snippet": None, "historial": []})


def _fmt():
    """Experimento de formato global (todos los sitios)."""
    return leer("formato.json", {"activo": None, "cola": HIPOTESIS_INICIALES, "historial": []}, global_=True)


def _guardar_fmt(st):
    guardar("formato.json", st, global_=True)


# ======================= 1. FORMATO =======================

def asignar_variante(tema):
    st = _fmt()
    if not st["activo"]:
        if not st["cola"]:
            return None
        h = st["cola"].pop(0)
        st["activo"] = {**h, "inicio": _hoy().isoformat(), "asignados": []}
        registrar("experimento_formato_inicio", nombre=h["nombre"])
        _guardar_fmt(st)
    f = st["activo"]
    asig = f["asignados"]
    if min(sum(x["brazo"] == b for x in asig) for b in "AB") >= MAX_POR_BRAZO:
        return None  # muestra completa: se espera a la evaluación
    estrato = f"{sitio()['id']}:{tema.get('cluster') or 'general'}"

    def n(b, solo_estrato):
        return sum(x["brazo"] == b and (not solo_estrato or x["estrato"] == estrato) for x in asig)
    a, b = n("A", True), n("B", True)
    if a == b:
        a, b = n("A", False), n("B", False)
    brazo = "A" if a < b else "B" if b < a else random.choice("AB")
    return {"experimento": f["nombre"], "brazo": brazo, "descripcion": f[brazo], "estrato": estrato}


def confirmar(registro):
    """Registra el artículo publicado en su brazo (con estrato y covariable)."""
    v = registro.get("variante")
    st = _fmt()
    f = st["activo"]
    if not (f and v and v["experimento"] == f["nombre"]):
        return
    if any(x["slug"] == registro["slug"] for x in f["asignados"]):
        return
    f["asignados"].append({"slug": registro["slug"], "brazo": v["brazo"], "estrato": v["estrato"],
                           "prioridad": registro.get("prioridad") or 50, "publicado": registro["publicado"],
                           "url": registro["url"], "sitio": sitio()["id"]})
    _guardar_fmt(st)


def _residuos(y, x):
    """Residuos de y ~ a + b·x (OLS simple). Si x no varía, y centrado."""
    mx, my = statistics.mean(x), statistics.mean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    b = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sxx if sxx else 0
    return [yi - my - b * (xi - mx) for xi, yi in zip(x, y)]


def _permutacion_estratificada(valores, brazos, estratos, n=5000):
    """p-valor bilateral de mean(B) - mean(A) permutando etiquetas dentro de cada estrato."""
    def dif(br):
        a = [v for v, x in zip(valores, br) if x == "A"]
        b = [v for v, x in zip(valores, br) if x == "B"]
        return statistics.mean(b) - statistics.mean(a)
    obs = dif(brazos)
    grupos = {}
    for i, e in enumerate(estratos):
        grupos.setdefault(e, []).append(i)
    k = 0
    for _ in range(n):
        perm = list(brazos)
        for idx in grupos.values():
            etiquetas = [perm[i] for i in idx]
            random.shuffle(etiquetas)
            for i, et in zip(idx, etiquetas):
                perm[i] = et
        if abs(dif(perm)) >= abs(obs) - 1e-12:
            k += 1
    return obs, (k + 1) / (n + 1)


def evaluar_formato():
    st = _fmt()
    f = st["activo"]
    if not f or not gsc.disponible():
        return None
    filas = []
    for x in f["asignados"]:
        activar(x["sitio"])
        pub = dt.date.fromisoformat(x["publicado"])
        if (_hoy() - pub).days < VENTANA[1] + 3:
            continue
        m = gsc.metricas_pagina(x["url"], pub + dt.timedelta(days=VENTANA[0]), pub + dt.timedelta(days=VENTANA[1]))
        filas.append({**x, **m})
    n = {b: sum(r["brazo"] == b for r in filas) for b in "AB"}
    mirada = max([m for m in MIRADAS if min(n.values()) >= m], default=None)
    if mirada is None or mirada in f.setdefault("miradas", []):
        return None
    f["miradas"].append(mirada)
    _guardar_fmt(st)
    total_imp = sum(r["impresiones"] for r in filas)
    completo = min(n.values()) >= MAX_POR_BRAZO
    y = _residuos([math.log1p(r["impresiones"]) for r in filas], [r["prioridad"] for r in filas])
    brazos, estratos = [r["brazo"] for r in filas], [r["estrato"] for r in filas]
    d, p = _permutacion_estratificada(y, brazos, estratos)
    sd = statistics.pstdev(y) or 1e-9
    mde = math.exp(Z * sd * math.sqrt(1 / n["A"] + 1 / n["B"])) - 1
    efecto = math.exp(d) - 1
    if p < ALFA and total_imp >= MIN_IMPRESIONES:
        ganador = "B" if d > 0 else "A"
        conclusion = f"Gana {ganador} ({efecto:+.0%} impresiones, p={p:.3f}): {f[ganador]}"
    elif mde <= MDE_OBJETIVO and total_imp >= MIN_IMPRESIONES:
        ganador, conclusion = None, f"Sin efecto relevante: se descarta una diferencia > {MDE_OBJETIVO:.0%} (MDE {mde:.0%})."
    elif completo:
        ganador, conclusion = None, f"No concluyente con {n['A']}+{n['B']} artículos (MDE {mde:.0%}): no se adopta regla."
    else:
        registrar("experimento_formato_sigue", nombre=f["nombre"], n=sum(n.values()), mde=round(mde, 2), p=round(p, 3))
        return None
    clics = {b: statistics.mean(r["clics"] for r in filas if r["brazo"] == b) for b in "AB"}
    res = {"tipo": "formato", "nombre": f["nombre"], "A": f["A"], "B": f["B"], "inicio": f["inicio"],
           "fin": _hoy().isoformat(), "n": n, "impresiones_totales": total_imp, "efecto_B_vs_A": round(efecto, 3),
           "p_valor": round(p, 3), "mde": round(mde, 3), "clics_medios": {b: round(c, 1) for b, c in clics.items()},
           "ganador": ganador, "conclusion": conclusion}
    st["historial"].append(res)
    st["activo"] = None
    _guardar_fmt(st)
    registrar("experimento_formato_fin", nombre=f["nombre"], conclusion=conclusion)
    return res


# ======================= 2. SNIPPET =======================

SNIPPET = {
    "type": "object", "required": ["titulo_seo", "meta_description", "razon"],
    "properties": {"titulo_seo": {"type": "string", "description": "45-60 caracteres, coherente con el H1"},
                   "meta_description": {"type": "string", "description": "140-155 caracteres"},
                   "razon": {"type": "string"}},
}


def _clics_vs_esperados(url, inicio, fin, curva, consultas=None):
    """(clics observados, clics esperados por posición, posición media ponderada, consultas) en el periodo."""
    filas = gsc.consultas_de_pagina(url, limite=500, inicio=inicio, fin=fin)
    if consultas is not None:
        filas = [q for q in filas if q["query"] in consultas]
    obs = sum(q["clics"] for q in filas)
    esp = sum(q["impresiones"] * curva[min(20, max(1, round(q["posicion"])))] for q in filas)
    imp = sum(q["impresiones"] for q in filas) or 1
    pos = sum(q["posicion"] * q["impresiones"] for q in filas) / imp
    return obs, esp, pos, {q["query"] for q in filas}


def iniciar_snippet(publicados):
    st = _estado()
    if st["snippet"] or not gsc.disponible():
        return None
    recientes = set()  # páginas testadas en los últimos 90 días no vuelven a entrar
    for h in st["historial"]:
        if h.get("tipo") == "snippet" and (_hoy() - dt.date.fromisoformat(h["fin"])).days < 90:
            for par in h["pares"]:
                recientes |= {par["test"]["slug"], par["control"]["slug"]}
    curva = gsc.curva_ctr()
    fin = _hoy() - dt.timedelta(days=3)
    ini = fin - dt.timedelta(days=DIAS_SNIPPET - 1)
    cand = []
    for p in publicados:
        if p.get("simulado") or p["slug"] in recientes or (_hoy() - dt.date.fromisoformat(p["publicado"])).days < 45:
            continue
        obs, esp, pos, _ = _clics_vs_esperados(p["url"], ini, fin, curva)
        if esp >= 3 and pos <= 15:
            cand.append({"p": p, "ratio": obs / esp, "esp": esp})
    if len(cand) < 4:
        return None
    cand = sorted(cand, key=lambda c: c["ratio"])[:12]          # los snippets con más margen de mejora
    cand.sort(key=lambda c: -c["esp"])                          # emparejar por volumen
    pares = []
    for i in range(0, len(cand) - 1, 2):
        t, c = random.sample([cand[i], cand[i + 1]], 2)
        p = t["p"]
        consultas = gsc.consultas_de_pagina(p["url"])
        r = ia.tarea("Eres especialista en CTR orgánico. Español de España.",
                     f"""Reescribe el título SEO y la meta description para aumentar el CTR en Google sin perder relevancia.
Título actual: {p['titulo_seo']} · H1: {p['titulo']}
Meta actual: {p['meta_description']}
Consultas reales por las que aparece (query, impresiones, posición): {[(q['query'], q['impresiones'], round(q['posicion'], 1)) for q in consultas]}
Lo aprendido en este sitio: {leer('aprendizajes.md', '')[:2000]}
Reglas: ≤ 60 caracteres y coherente con el H1 (si no, Google lo reescribe), incluye la consulta principal, promete algo concreto que el artículo cumple, nada de clickbait.""", SNIPPET)
        if not SIMULAR:
            cms().actualizar_en_vivo(p["post_id"], {"htmlTitle": r["titulo_seo"], "metaDescription": r["meta_description"]})
        pares.append({"test": {"slug": p["slug"], "post_id": p["post_id"], "url": p["url"], "rastreo": None,
                               "original": {"htmlTitle": p["titulo_seo"], "metaDescription": p["meta_description"]},
                               "nuevo": {"htmlTitle": r["titulo_seo"], "metaDescription": r["meta_description"]},
                               "razon": r["razon"]},
                      "control": {"slug": c["p"]["slug"], "url": c["p"]["url"]}})
    st["snippet"] = {"cambio": _hoy().isoformat(), "pares": pares}
    guardar("experimentos.json", st)
    registrar("experimento_snippet_inicio", pares=len(pares))
    return st["snippet"]


def _revertir(t):
    if not SIMULAR:
        cms().actualizar_en_vivo(t["post_id"], t["original"])


def evaluar_snippet():
    st = _estado()
    s = st["snippet"]
    if not s:
        return None
    cambio = dt.date.fromisoformat(s["cambio"])
    # 1) esperar al rastreo de cada página test
    for par in s["pares"]:
        t = par["test"]
        if t["rastreo"] or par.get("excluido"):
            continue
        r = gsc.ultimo_rastreo(t["url"])
        if r and r >= cambio:
            t["rastreo"] = r.isoformat()
        elif (_hoy() - cambio).days > MAX_ESPERA_RASTREO:
            par["excluido"] = "no rastreada en 21 días"
            _revertir(t)
    guardar("experimentos.json", st)
    activos = [p for p in s["pares"] if not p.get("excluido")]
    if any(not p["test"]["rastreo"] for p in activos):
        return None
    inicio_post = {id(p): dt.date.fromisoformat(p["test"]["rastreo"]) + dt.timedelta(days=1) for p in activos}
    if activos and (_hoy() - max(inicio_post.values())).days < DIAS_SNIPPET + 3:
        return None
    # 2) medir con el mismo conjunto de consultas antes y después
    curva = gsc.curva_ctr()
    pre = (cambio - dt.timedelta(days=DIAS_SNIPPET), cambio - dt.timedelta(days=1))

    def lift(url, post_ini):
        post = (post_ini, post_ini + dt.timedelta(days=DIAS_SNIPPET - 1))
        _, _, _, q_pre = _clics_vs_esperados(url, *pre, curva)
        _, _, _, q_post = _clics_vs_esperados(url, *post, curva)
        comunes = q_pre & q_post
        o1, e1, p1, _ = _clics_vs_esperados(url, *pre, curva, comunes)
        o2, e2, p2, _ = _clics_vs_esperados(url, *post, curva, comunes)
        return {"lift": ((o2 + .5) / (e2 + .5)) / ((o1 + .5) / (e1 + .5)), "dpos": p2 - p1, "esperados": e1 + e2}

    for p in activos:
        p["m_test"] = lift(p["test"]["url"], inicio_post[id(p)])
        p["m_control"] = lift(p["control"]["url"], inicio_post[id(p)])
        p["valido"] = abs(p["m_test"]["dpos"]) <= 1.5 and abs(p["m_control"]["dpos"]) <= 1.5
    validos = [p for p in activos if p["valido"]]
    datos = sum(p["m_test"]["esperados"] for p in validos)
    if len(validos) >= 2 and datos >= 30:
        did = statistics.median(p["m_test"]["lift"] / p["m_control"]["lift"] for p in validos)
    else:
        did = None
    for p in activos:
        rel = p["m_test"]["lift"] / p["m_control"]["lift"]
        p["decision"] = "mantener" if (did and did >= 1.10 and p["valido"] and rel >= 1.0) else "revertir"
        if p["decision"] == "revertir":
            _revertir(p["test"])
        else:
            pub = leer("publicados.json", [])
            for x in pub:
                if x["slug"] == p["test"]["slug"]:
                    x["titulo_seo"], x["meta_description"] = p["test"]["nuevo"]["htmlTitle"], p["test"]["nuevo"]["metaDescription"]
            guardar("publicados.json", pub)
    conclusion = (f"Diferencia en diferencias {did:.2f}: {sum(p['decision'] == 'mantener' for p in activos)}/{len(activos)} títulos mantenidos"
                  if did else "Datos insuficientes: se revierte todo (conservador).")
    res = {"tipo": "snippet", "fin": _hoy().isoformat(), "did": did and round(did, 3), "pares": s["pares"], "conclusion": conclusion}
    st["historial"].append(res)
    st["snippet"] = None
    guardar("experimentos.json", st)
    registrar("experimento_snippet_fin", conclusion=conclusion)
    return res
