"""Piloto SEO multi-sitio.

  python -m piloto diario                      lo que toque hoy en cada sitio (lo lanza GitHub Actions)
  python -m piloto <comando> --sitio <id>      comando manual en un sitio:
      verificar    prueba cada conexión (HubSpot, Search Console, Gemini) y dice qué arreglar
      configurar   detecta blog/autor en el CMS y sube las fotos (una vez)
      investigar   añade temas nuevos a la cola
      borrador     escribe el próximo artículo y lo deja como borrador en el CMS (para revisarlo)
      publicar     escribe y publica el próximo artículo
      semanal      mide, evalúa/lanza experimentos, refresca y actualiza aprendizajes
      estado       resumen
  python -m piloto estado                      resumen de todos los sitios

Cada sitio se configura en sitios/<id>/sitio.json (articulos_semana, presupuesto_usd_mes, publicador…).
SIMULAR=1 hace todo sin tocar el CMS (HTML en sitios/<id>/salida/). PAUSADO=1 no hace nada.
"""
import datetime as dt
import os
import sys
import traceback

from . import aprendizaje, experimentos, ia, investigacion, publicacion
from .base import SIMULAR, activar, ids_sitios, leer, registrar

MIN_COLA = 6


def cuantos_hoy(n, dia_semana):
    """Reparte n artículos/semana: hasta 5 de lunes a viernes; más de 5, los 7 días."""
    dias = 5 if n <= 5 else 7
    if dia_semana >= dias:
        return 0
    return sum(1 for i in range(n) if (i * dias) // n == dia_semana)


def _cola():
    return sum(t["estado"] == "pendiente" for t in leer("temas.json", []))


def publicar():
    if _cola() < MIN_COLA:
        investigacion.investigar()
    return publicacion.publicar_uno()


def borrador():
    if _cola() < MIN_COLA:
        investigacion.investigar()
    r = publicacion.publicar_uno(borrador=True)
    if r:
        registrar("borrador_listo", slug=r["slug"], post_id=r["post_id"],
                  editar=f"https://app-eu1.hubspot.com/blog/146519427/editor/{r['post_id']}/content")


def exportar():
    """Guarda en el repositorio el contenido actual (borrador incluido) del último artículo del piloto."""
    from . import hubspot
    p = leer("publicados.json", [])[-1]
    post = hubspot.obtener(p["post_id"])
    try:
        borr = hubspot._get(f"/cms/v3/blogs/posts/{p['post_id']}/draft")
    except Exception:
        borr = post
    from .base import guardar
    guardar(f"articulos/{p['slug']}.hubspot.json", {k: borr.get(k) for k in
            ("name", "htmlTitle", "metaDescription", "postSummary", "postBody", "featuredImage", "state", "url")})
    registrar("exportado", slug=p["slug"])


def semanal():
    aprendizaje.ciclo()
    if _cola() < 2 * MIN_COLA:
        investigacion.investigar()


def estado(sid):
    s = activar(sid)
    pub = leer("publicados.json", [])
    exp = leer("experimentos.json", {})
    print(f"\n=== {s['nombre']} ({s['url']}) · {s['articulos_semana']}/semana · publicador: {s['publicador']['tipo']}")
    print(f"Cola: {_cola()} temas · publicados: {len(pub)} · gasto del mes: {ia.gasto_mes(sid):.2f} / {s['presupuesto_usd_mes']} USD")
    for t in [t for t in leer("temas.json", []) if t["estado"] == "pendiente"][:5]:
        print(f"  {t.get('prioridad', 0):>3}  {t['keyword']}")
    if exp.get("snippet"):
        print(f"Test de títulos activo desde {exp['snippet']['cambio']}")


def verificar():
    """Comprueba cada conexión con una llamada mínima y explica cómo arreglar lo que falle."""
    from . import gsc, hubspot
    from .base import sitio
    s = sitio()
    pruebas = [
        ("HubSpot (token y blog)", lambda: f"{len(hubspot.blogs())} blog(s)",
         "Revisa el secret HUBSPOT_TOKEN_* y los permisos content + files de la app privada."),
        ("Search Console", lambda: f"{len(gsc.consulta(['query'], dias=7, limite=5))} consultas en 7 días",
         f"Añade el email de la cuenta de servicio como usuario de la propiedad {s['gsc_sitio']} en Search Console."),
        ("Gemini", lambda: ia.tarea("Responde en JSON.", "Di ok.", {"type": "object", "required": ["ok"],
                                    "properties": {"ok": {"type": "string"}}}, max_tokens=50)["ok"],
         "Vertex AI: activa la «Vertex AI API» en el proyecto de la cuenta de servicio, dale el rol «Vertex AI User» "
         "y vincula el proyecto a la cuenta de facturación con los créditos de Google AI Pro."),
        ("Gemini con búsqueda Google", lambda: ia.tarea("Responde en JSON.", "¿Qué día es hoy? Búscalo.",
                                                         {"type": "object", "required": ["fecha"],
                                                          "properties": {"fecha": {"type": "string"}}}, web=True, max_tokens=300)["fecha"],
         "El modelo responde pero no puede buscar: revisa que el modelo admita grounding en Vertex."),
    ]
    fallos = 0
    for nombre, prueba, arreglo in pruebas:
        try:
            res = prueba()
            print(f"✅ {nombre}: {res}")
            registrar("verificar", prueba=nombre, ok=True, detalle=str(res)[:200])
        except BaseException as e:
            fallos += 1
            print(f"❌ {nombre}: {str(e)[:400]}\n   → Cómo arreglarlo: {arreglo}")
            registrar("verificar", prueba=nombre, ok=False, detalle=str(e)[:600])
    print("\nTodo listo para publicar." if not fallos else f"\n{fallos} problema(s): corrígelos y vuelve a ejecutar «verificar».")
    if fallos:
        raise SystemExit(1)


def _en_sitio(sid, fn):
    """Ejecuta fn en un sitio aislando errores: un sitio que falla no para a los demás."""
    s = activar(sid)
    try:
        fn()
        return True
    except ia.PresupuestoAgotado as e:
        registrar("presupuesto_agotado", motivo=str(e))
        return True
    except SystemExit as e:  # falta una clave o configuración
        registrar("error", tipo="configuracion", motivo=str(e))
        return False
    except Exception as e:
        registrar("error", tipo=type(e).__name__, motivo=str(e)[:300])
        traceback.print_exc()
        return False
    finally:
        ia.guardar_gasto()


def diario():
    hoy = dt.date.today().weekday()
    ok = True
    for sid in ids_sitios():
        s = activar(sid)
        if s["publicador"]["tipo"] == "pendiente" and not SIMULAR:
            registrar("omitido", motivo="publicador pendiente de configurar")
            continue
        dias = s.get("dias_publicacion")  # p. ej. [1, 3, 5] = martes, jueves, sábado
        n = (1 if hoy in dias else 0) if dias else cuantos_hoy(s.get("articulos_semana", 3), hoy)
        for _ in range(n):
            ok &= _en_sitio(sid, publicar)
        if hoy == 6:
            ok &= _en_sitio(sid, semanal)
    if hoy == 6 and ids_sitios():
        ok &= _en_sitio(ids_sitios()[0], experimentos.evaluar_formato)  # experimento global
    if not ok:
        sys.exit(1)  # GitHub avisa por email


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    cmd = args[0] if args else "estado"
    if cmd == "diario" and os.environ.get("PAUSADO") == "1":
        print("Piloto en pausa (PAUSADO=1): la ejecución automática no hace nada; los comandos manuales sí funcionan.")
        return
    sid = args[args.index("--sitio") + 1] if "--sitio" in args else None
    if cmd == "diario":
        diario()
    elif cmd == "estado":
        for x in ([sid] if sid else ids_sitios()):
            estado(x)
        f = experimentos._fmt()["activo"]
        if f:
            print(f"\nExperimento de formato (todos los sitios): {f['nombre']} · {len(f['asignados'])} artículos")
        print(f"\nGasto total del mes: {ia.gasto_mes():.2f} / {ia.PRESUPUESTO} USD (crédito Google AI Pro: 10 USD)")
    elif cmd in ("verificar", "configurar", "investigar", "publicar", "borrador", "exportar", "semanal") and sid:
        fn = {"exportar": exportar, "borrador": borrador, "verificar": verificar, "configurar": publicacion.configurar, "investigar": investigacion.investigar,
              "publicar": publicar, "semanal": semanal}[cmd]
        if not _en_sitio(sid, fn):
            sys.exit(1)
    else:
        print(__doc__)


main()
