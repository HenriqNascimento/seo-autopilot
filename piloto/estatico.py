"""Publicador para webs estáticas en un repositorio git (p. ej. cresco.es en Cloudflare).

Misma interfaz que hubspot.py, para que el resto del piloto no distinga el CMS:
cada artículo es <dir_repo>/<carpeta_blog>/<slug>.html generado desde sitios/<id>/plantilla.html.
Al publicar actualiza la lista del blog, sitemap.xml y llms.txt, hace commit y (en Actions) push;
el despliegue lo hace la integración Git de Cloudflare al recibir el push.

sitio.json → "publicador": {"tipo": "estatico", "dir_env": "CRESCO_WEB_DIR", "carpeta_blog": "public/blog",
               "url_blog": "https://cresco.es/blog/", "pagina_blog": "public/blog.html",
               "sitemap": "public/sitemap.xml", "llms": "public/llms.txt"}
"""
import datetime as dt
import html
import json
import os
import re
import subprocess
from pathlib import Path

from .base import SIMULAR, dir_sitio, registrar, requerido, sitio

MARCA_LISTA = "<!-- PILOTO:ARTICULOS -->"


def _pub():
    return sitio()["publicador"]


def _repo():
    return Path(requerido(_pub()["dir_env"]))


def _ruta(slug):
    return _repo() / _pub()["carpeta_blog"] / f"{slug}.html"


def _url(slug):
    return _pub()["url_blog"].rstrip("/") + "/" + slug


def _git(*args):
    return subprocess.run(["git", "-C", str(_repo()), *args], capture_output=True, text=True, check=True).stdout


def _commit(mensaje):
    if SIMULAR:
        return
    _git("add", "-A")
    if not _git("status", "--porcelain").strip():
        return
    _git("-c", "user.name=piloto-seo", "-c", "user.email=piloto-seo@users.noreply.github.com", "commit", "-m", mensaje)
    if os.environ.get("PILOTO_GIT_PUSH") == "1":
        _git("pull", "--rebase", "--autostash")
        _git("push")


# ---------- interfaz común con hubspot.py ----------

def blogs():
    return [{"id": "estatico", "name": sitio()["nombre"], "absoluteUrl": _pub()["url_blog"].rstrip("/")}]


def autores():
    return []


def tag_ids(nombres):
    return []


def subir_archivo(ruta, carpeta=None):
    raise SystemExit("La web estática no usa subida de archivos: las fotos van en el repositorio.")


def posts_publicados(blog_id=None):
    out = []
    carpeta = _repo() / _pub()["carpeta_blog"]
    for f in sorted(carpeta.glob("*.html")) if carpeta.exists() else []:
        t = f.read_text(encoding="utf-8")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S)
        out.append({"name": html.unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip()) if m else f.stem, "url": _url(f.stem)})
    return out


def obtener(post_id):
    t = _ruta(post_id).read_text(encoding="utf-8")
    m = re.search(r"<!--CUERPO-->(.*?)<!--/CUERPO-->", t, re.S)
    return {"postBody": m.group(1) if m else "", "url": _url(post_id)}


def actualizar_en_vivo(post_id, cambios):
    f = _ruta(post_id)
    t = f.read_text(encoding="utf-8")
    if "htmlTitle" in cambios:
        t = re.sub(r"<title>.*?</title>", f"<title>{html.escape(cambios['htmlTitle'])}</title>", t, count=1, flags=re.S)
        t = re.sub(r'(<meta property="og:title" content=")[^"]*', lambda m: m.group(1) + html.escape(cambios["htmlTitle"]), t, count=1)
    if "metaDescription" in cambios:
        t = re.sub(r'(<meta name="description" content=")[^"]*', lambda m: m.group(1) + html.escape(cambios["metaDescription"]), t, count=1)
        t = re.sub(r'(<meta property="og:description" content=")[^"]*', lambda m: m.group(1) + html.escape(cambios["metaDescription"]), t, count=1)
    if "postBody" in cambios:
        t = re.sub(r"<!--CUERPO-->.*?<!--/CUERPO-->", lambda m: "<!--CUERPO-->" + cambios["postBody"] + "<!--/CUERPO-->", t, count=1, flags=re.S)
        t = re.sub(r'("dateModified":\s*")[^"]*', lambda m: m.group(1) + dt.date.today().isoformat(), t, count=1)
    f.write_text(t, encoding="utf-8")
    _commit(f"blog: actualiza {post_id}")


def crear_borrador(datos):
    """En una web estática no hay borradores: se genera en la carpeta de salida del sitio para revisarlo."""
    salida = dir_sitio() / "salida"
    salida.mkdir(exist_ok=True)
    (salida / f"{datos['slug']}.html").write_text(_render(datos), encoding="utf-8")
    return {"id": datos["slug"], "url": str(salida / f"{datos['slug']}.html")}


def crear_y_publicar(datos):
    slug = datos["slug"]
    f = _ruta(slug)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_render(datos), encoding="utf-8")
    _anadir_a_lista(slug, datos)
    _anadir_a_sitemap(slug)
    _anadir_a_llms(slug, datos)
    _commit(f"blog: publica {slug}")
    registrar("estatico_publicado", slug=slug, archivo=str(f.relative_to(_repo())))
    return {"id": slug, "url": _url(slug)}


# ---------- generación ----------

def _render(d):
    s = sitio()
    hoy = dt.date.today().isoformat()
    url = _url(d["slug"])
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BlogPosting", "@id": url + "#articulo", "headline": d["name"], "description": d["metaDescription"],
         "datePublished": hoy, "dateModified": hoy, "inLanguage": "es-ES", "mainEntityOfPage": url,
         "author": {"@type": "Person", "name": s["autor"].split(",")[0]},
         "publisher": {"@type": "Organization", "@id": s["url"].rstrip("/") + "/#negocio", "name": s["nombre"], "url": s["url"]}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Inicio", "item": s["url"].rstrip("/") + "/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": _pub()["url_blog"].rstrip("/")},
            {"@type": "ListItem", "position": 3, "name": d["name"], "item": url}]}]}
    plantilla = (dir_sitio() / "plantilla.html").read_text(encoding="utf-8")
    valores = {
        "{{TITULO_SEO}}": html.escape(d["htmlTitle"]), "{{META}}": html.escape(d["metaDescription"]),
        "{{TITULO}}": html.escape(d["name"]), "{{RESUMEN}}": html.escape(d.get("postSummary", "")),
        "{{URL}}": url, "{{SLUG}}": d["slug"], "{{FECHA}}": hoy,
        "{{FECHA_HUMANA}}": dt.date.today().strftime("%d/%m/%Y"), "{{AUTOR}}": html.escape(s["autor"]),
        "{{JSONLD}}": json.dumps(ld, ensure_ascii=False), "{{CUERPO}}": d["postBody"],
    }
    for k, v in valores.items():
        plantilla = plantilla.replace(k, v)
    return plantilla


def _anadir_a_lista(slug, d):
    pag = _repo() / _pub()["pagina_blog"]
    if not pag.exists():
        return
    t = pag.read_text(encoding="utf-8")
    if MARCA_LISTA not in t:
        # primera vez: se inserta una sección de artículos antes de la lista de guías
        seccion = ('<section class="articulos" style="padding-block:56px 0"><div class="wrap">'
                   '<div class="list-head"><h2>Artículos</h2><span class="fine">Para dueños de pequeños negocios</span></div>'
                   f'<div class="guides">{MARCA_LISTA}</div></div></section>\n')
        if '<main class="list">' not in t:
            return
        t = t.replace('<main class="list">', seccion + '<main class="list">', 1)
    if f'href="blog/{slug}"' in t:
        return
    item = (f'<a href="blog/{slug}" style="display:grid;gap:4px;padding:18px 0;border-bottom:1px solid var(--line);text-decoration:none">'
            f'<h3>{html.escape(d["name"])}</h3><span style="color:var(--muted);font-size:15px">{html.escape(d.get("postSummary", ""))}</span></a>')
    pag.write_text(t.replace(MARCA_LISTA, MARCA_LISTA + "\n" + item, 1), encoding="utf-8")


def _anadir_a_sitemap(slug):
    sm = _repo() / _pub()["sitemap"]
    if not sm.exists():
        return
    t = sm.read_text(encoding="utf-8")
    if _url(slug) in t:
        return
    hoy = dt.date.today().isoformat()
    t = t.replace("</urlset>", f"  <url><loc>{_url(slug)}</loc><lastmod>{hoy}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>\n</urlset>")
    sm.write_text(t, encoding="utf-8")


def _anadir_a_llms(slug, d):
    f = _repo() / _pub().get("llms", "")
    if not _pub().get("llms") or not f.exists():
        return
    t = f.read_text(encoding="utf-8")
    if _url(slug) in t:
        return
    if "## Artículos" not in t:
        t = t.rstrip() + "\n\n## Artículos\n"
    t = t.rstrip() + f"\n- [{d['name']}]({_url(slug)}): {d.get('postSummary', '')}\n"
    f.write_text(t, encoding="utf-8")
