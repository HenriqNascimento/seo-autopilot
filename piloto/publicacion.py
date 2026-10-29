"""Elige el próximo tema del sitio activo, lo escribe y lo publica en su CMS."""
import datetime as dt
import html
import json
import random

from . import experimentos, hubspot, redaccion
from .cms import cms
from .base import SIMULAR, dir_sitio, guardar, leer, registrar, salida, sitio


def _imagenes_locales():
    f = dir_sitio() / "imagenes" / "descripciones.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def configurar():
    """Detecta blog y autor en el CMS y sube las fotos del sitio. Se ejecuta una vez por sitio."""
    cfg = leer("config.json", {})
    bl = cms().blogs()
    for b in bl:
        print(f"Blog: {b.get('name')} id={b['id']} url={b.get('absoluteUrl') or b.get('slug')}")
    if not cfg.get("blog_id"):
        ruta = sitio().get("blog_ruta", "")
        idioma = sitio().get("idioma", "es")
        elegido = next((b for b in bl if ruta and ruta in (b.get("absoluteUrl") or "")), None)             or next((b for b in bl if (b.get("language") or "").startswith(idioma)), bl[0])
        cfg["blog_id"] = elegido["id"]
        cfg["blog_url"] = elegido.get("absoluteUrl", "")
        print(f"Blog elegido: {elegido.get('name')} ({cfg['blog_url']})")
    au = cms().autores()
    for a in au:
        print(f"Autor: {a.get('fullName') or a.get('displayName')} id={a['id']}")
    if not cfg.get("autor_id") and au:
        nombre = sitio()["autor"].split(",")[0].split()[0].lower()
        elegido = next((a for a in au if nombre in (a.get("fullName") or a.get("displayName") or "").lower()), au[0])
        cfg["autor_id"] = elegido["id"]
    guardar("config.json", cfg)
    imgs = sincronizar_imagenes()
    registrar("configurar", blog=cfg["blog_id"], autor=cfg.get("autor_id"), imagenes=len(imgs))


def sincronizar_imagenes():
    """Sube al CMS las fotos nuevas de sitios/<id>/imagenes y actualiza descripciones."""
    imgs = leer("imagenes.json", {})
    nuevas = 0
    for nombre, desc in _imagenes_locales().items():
        ruta = dir_sitio() / "imagenes" / nombre
        if nombre not in imgs and ruta.exists():
            if SIMULAR:
                imgs[nombre] = {"url": f"https://sim/{nombre}", "descripcion": desc}
            else:
                imgs[nombre] = {"url": cms().subir_archivo(str(ruta), f"/blog-{sitio()['id']}"), "descripcion": desc}
            nuevas += 1
        elif nombre in imgs:
            imgs[nombre]["descripcion"] = desc
    if nuevas:
        registrar("imagenes_subidas", nuevas=nuevas, total=len(imgs))
    guardar("imagenes.json", imgs)
    return imgs


def existentes():
    """Posts publicados (incluye los que no hizo el piloto) para el enlazado interno."""
    if SIMULAR:
        return [{"titulo": p["titulo"], "url": p["url"]} for p in leer("publicados.json", [])]
    return [{"titulo": p["name"], "url": p["url"]} for p in cms().posts_publicados(leer("config.json", {}).get("blog_id"))]


def siguiente_tema():
    temas = leer("temas.json", [])
    pend = [t for t in temas if t["estado"] == "pendiente"]
    if not pend:
        return None, temas
    # 80 % explota la mejor prioridad, 20 % explora otro tema de la cola para no sesgar el aprendizaje
    tema = pend[0] if random.random() < 0.8 or len(pend) < 3 else random.choice(pend[1:min(len(pend), 8)])
    return tema, temas


def publicar_uno(intentos=2, borrador=False):
    """Escribe y publica un artículo. Si el control de calidad rechaza un tema, prueba con el siguiente."""
    ex = existentes()
    if sitio()["publicador"]["tipo"] == "hubspot":
        sincronizar_imagenes()
    i = saltados = 0
    while i < intentos:
        tema, temas = siguiente_tema()
        if not tema:
            registrar("sin_temas")
            return None
        conflicto, motivo = redaccion.canibaliza(tema, ex)
        if conflicto:  # no se escribe sobre lo que ya existe; no cuenta como fallo
            tema["estado"], tema["motivo"] = "repetido", motivo[:300]
            guardar("temas.json", temas)
            registrar("tema_repetido", slug=tema["slug"], motivo=motivo[:200])
            saltados += 1
            if saltados >= 8:
                raise RuntimeError("8 temas seguidos ya cubiertos: hay que investigar temas nuevos")
            continue
        i += 1
        variante = experimentos.asignar_variante(tema)
        try:
            a, nota, brief = redaccion.escribir(tema, ex, variante and variante["descripcion"])
            break
        except RuntimeError as e:
            tema["estado"] = "descartado"
            tema["motivo"] = str(e)[:300]
            guardar("temas.json", temas)
            registrar("descartado", slug=tema["slug"], motivo=str(e)[:200])
            if i == intentos:
                raise  # el workflow falla y GitHub avisa por email
    s = sitio()
    imgs = leer("imagenes.json", {})
    foto = imgs.get(a["foto"]) or (next(iter(imgs.values())) if imgs else {"url": ""})
    cfg = leer("config.json", {})
    cuerpo = redaccion.a_html(a, s["url"])
    datos = {
        "name": a["titulo"], "contentGroupId": cfg.get("blog_id"), "slug": tema["slug"],
        "htmlTitle": a["titulo_seo"], "metaDescription": a["meta_description"], "postSummary": a["resumen"],
        "postBody": cuerpo, "blogAuthorId": cfg.get("autor_id"),
        "featuredImage": foto["url"], "featuredImageAltText": a["alt_foto"], "useFeaturedImage": bool(foto["url"]),
    }
    hoy = dt.date.today().isoformat()
    if SIMULAR:
        salida().mkdir(exist_ok=True)
        (salida() / f"{tema['slug']}.html").write_text(
            f"<!doctype html><meta charset=utf-8><title>{html.escape(a['titulo_seo'])}</title>"
            f"<meta name=description content=\"{html.escape(a['meta_description'])}\">"
            f"<body style='max-width:760px;margin:40px auto;font-family:Georgia,serif;line-height:1.7;padding:0 16px'>"
            f"<h1>{html.escape(a['titulo'])}</h1>{cuerpo}", encoding="utf-8")
        post = {"id": f"sim-{tema['slug']}", "url": f"{cfg.get('blog_url', s['url'] + '/blog')}/{tema['slug']}"}
    else:
        datos["tagIds"] = cms().tag_ids(a["tags"])
        post = cms().crear_borrador(datos) if borrador else cms().crear_y_publicar(datos)
    registro = {
        "slug": tema["slug"], "post_id": post["id"], "url": post["url"], "titulo": a["titulo"],
        "titulo_seo": a["titulo_seo"], "meta_description": a["meta_description"], "keyword": tema["keyword"],
        "cluster": tema.get("cluster"), "intencion": tema.get("intencion"), "etapa": tema.get("etapa"),
        "prioridad": tema.get("prioridad"), "palabras": redaccion.palabras(a), "h2": sum(b["tipo"] == "h2" for b in a["bloques"]),
        "tablas": sum(b["tipo"] == "tabla" for b in a["bloques"]), "faq": len(a["faq"]),
        "variante": variante, "foto": a.get("foto"), "nota_editor": nota, "publicado": hoy, "simulado": SIMULAR, "borrador": borrador,
    }
    guardar(f"articulos/{tema['slug']}.json", {"articulo": a, "brief": brief, "html": cuerpo})  # copia para auditoría
    pub = leer("publicados.json", [])
    pub.append(registro)
    guardar("publicados.json", pub)
    tema["estado"] = "publicado"
    guardar("temas.json", temas)
    experimentos.confirmar(registro)
    registrar("publicado", slug=tema["slug"], url=post["url"], palabras=registro["palabras"])
    return registro
