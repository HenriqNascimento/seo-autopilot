"""Configuración por sitio, estado persistente y utilidades HTTP.

Cada sitio vive en sitios/<id>/ (sitio.json, conocimiento/, imagenes/, estado/). Antes de trabajar
con un sitio se llama a activar(<id>); leer/guardar/conocimiento operan sobre el sitio activo.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITIOS = RAIZ / "sitios"
COMUN = RAIZ / "comun"
GLOBAL = RAIZ / "estado_global"

MODELO = os.environ.get("PILOTO_MODELO", "gemini-3.8-flash")
SIMULAR = os.environ.get("SIMULAR") == "1"  # no escribe en el CMS

_activo = {}


def ids_sitios():
    return sorted(p.parent.name for p in SITIOS.glob("*/sitio.json"))


def activar(sid):
    cfg = json.loads((SITIOS / sid / "sitio.json").read_text(encoding="utf-8"))
    _activo.clear()
    _activo.update(cfg, id=sid)
    return cfg


def sitio():
    if not _activo:
        raise RuntimeError("Ningún sitio activo: llama a base.activar(id).")
    return _activo


def dir_sitio():
    return SITIOS / sitio()["id"]


def salida():
    return dir_sitio() / "salida"  # HTML de las simulaciones


def _ruta(nombre, global_=False):
    return (GLOBAL if global_ else dir_sitio() / "estado") / nombre


def leer(nombre, defecto=None, global_=False):
    f = _ruta(nombre, global_)
    if not f.exists():
        return defecto
    if f.suffix == ".json":
        return json.loads(f.read_text(encoding="utf-8"))
    return f.read_text(encoding="utf-8")


def guardar(nombre, datos, global_=False):
    f = _ruta(nombre, global_)
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.suffix == ".json":
        f.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        f.write_text(datos, encoding="utf-8")


def conocimiento(nombre):
    """Archivo del sitio activo; si no existe, el común."""
    for f in (dir_sitio() / "conocimiento" / nombre, COMUN / nombre):
        if f.exists():
            return f.read_text(encoding="utf-8")
    return ""


def registrar(evento, **datos):
    """Bitácora append-only del sitio activo (estado/bitacora.jsonl)."""
    import datetime as dt
    linea = {"t": dt.datetime.now().isoformat(timespec="seconds"), "sitio": _activo.get("id"), "evento": evento, **datos}
    f = _ruta("bitacora.jsonl", global_=not _activo)
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(linea, ensure_ascii=False) + "\n")
    print(f"[{_activo.get('id', '-')}:{evento}] " + ", ".join(f"{k}={v}" for k, v in datos.items() if not isinstance(v, (dict, list))))


def http(metodo, url, cuerpo=None, cabeceras=None, timeout=120, crudo=False):
    data = None
    cab = dict(cabeceras or {})
    if cuerpo is not None and not isinstance(cuerpo, bytes):
        data = json.dumps(cuerpo).encode()
        cab.setdefault("content-type", "application/json")
    elif isinstance(cuerpo, bytes):
        data = cuerpo
    req = urllib.request.Request(url, data=data, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read()
            return txt if crudo else (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{metodo} {url} -> {e.code}: {e.read().decode(errors='replace')[:800]}") from None


def requerido(var):
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"Falta la variable de entorno {var}.")
    return v
