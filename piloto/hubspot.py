"""HubSpot CMS — blog posts, autores, tags y archivos (app privada, scopes: content, files)."""
import json
import mimetypes
import os
import re
import unicodedata
import uuid

from .base import http, requerido, sitio

API = "https://api.hubapi.com"


def _h():
    pub = sitio()["publicador"]
    if pub.get("tipo") != "hubspot":
        raise SystemExit(f"{sitio()['nombre']}: publicador '{pub.get('tipo')}' no soportado todavía.")
    return {"authorization": f"Bearer {requerido(pub['token_env'])}"}


def _get(ruta):
    return http("GET", API + ruta, cabeceras=_h())


def blogs():
    return _get("/cms/v3/blog-settings/settings").get("results", [])


def autores():
    return _get("/cms/v3/blogs/authors?limit=100").get("results", [])


def posts_publicados(blog_id):
    out, after = [], None
    while True:
        q = f"/cms/v3/blogs/posts?limit=100&state=PUBLISHED&contentGroupId={blog_id}" + (f"&after={after}" if after else "")
        r = _get(q)
        out += r.get("results", [])
        after = (r.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return out


def _clave_tag(nombre):
    """Como el slug de HubSpot: «CAD/CAM dental» y «CAD-CAM dental» son la misma etiqueta."""
    s = "".join(c for c in unicodedata.normalize("NFD", nombre.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def tag_ids(nombres):
    existentes = {_clave_tag(t["name"]): t["id"] for t in _get("/cms/v3/blogs/tags?limit=300").get("results", [])}
    ids = []
    for n in nombres:
        clave = _clave_tag(n)
        if clave not in existentes:
            try:
                existentes[clave] = http("POST", API + "/cms/v3/blogs/tags", {"name": n}, _h())["id"]
            except RuntimeError as e:  # 409 NONUNIQUE_SLUG: la etiqueta ya existe con otro nombre
                m = re.search(r'"tagId":\s*\["(\d+)"', str(e))
                if not m:
                    raise
                existentes[clave] = m.group(1)
        ids.append(existentes[clave])
    return ids


def crear_borrador(datos):
    """Crea el post como borrador (no se publica)."""
    return http("POST", API + "/cms/v3/blogs/posts", datos, _h(), idempotente=False)


def crear_y_publicar(datos):
    """datos: campos de BlogPost (name, slug, htmlTitle, metaDescription, postBody, …). Devuelve el post publicado."""
    post = http("POST", API + "/cms/v3/blogs/posts", datos, _h(), idempotente=False)
    return http("PATCH", f"{API}/cms/v3/blogs/posts/{post['id']}", {"state": "PUBLISHED"}, _h())


def obtener(post_id):
    return _get(f"/cms/v3/blogs/posts/{post_id}")


def actualizar_en_vivo(post_id, cambios):
    """Cambia el borrador del post publicado y lo pasa a vivo (título, meta, cuerpo…)."""
    http("PATCH", f"{API}/cms/v3/blogs/posts/{post_id}/draft", cambios, _h())
    http("POST", f"{API}/cms/v3/blogs/posts/{post_id}/draft/push-live", {}, _h())


def subir_archivo(ruta, carpeta="/blog-innovadental"):
    """Sube una imagen al File Manager (pública e indexable) y devuelve su URL."""
    limite = uuid.uuid4().hex
    nombre = os.path.basename(ruta)
    tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    partes = []
    for campo, valor in (("folderPath", carpeta), ("options", json.dumps({"access": "PUBLIC_INDEXABLE", "overwrite": True}))):
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{campo}"\r\n\r\n{valor}\r\n'.encode())
    with open(ruta, "rb") as f:
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\n'
                      f"Content-Type: {tipo}\r\n\r\n".encode() + f.read() + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    r = http("POST", API + "/files/v3/files", b"".join(partes),
             {**_h(), "content-type": f"multipart/form-data; boundary={limite}"}, timeout=300)
    return r["url"]
