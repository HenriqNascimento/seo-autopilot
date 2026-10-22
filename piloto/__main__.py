"""Piloto SEO multi-sitio.

  python -m piloto diario                      lo que toque hoy en cada sitio (lo lanza GitHub Actions)
  python -m piloto <comando> --sitio <id>      comando manual en un sitio:
      configurar   detecta blog/autor en el CMS y sube las fotos (una vez)
      investigar   añade temas nuevos a la cola
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
        for _ in range(cuantos_hoy(s.get("articulos_semana", 3), hoy)):
            ok &= _en_sitio(sid, publicar)
        if hoy == 6:
            ok &= _en_sitio(sid, semanal)
    if hoy == 6 and ids_sitios():
        ok &= _en_sitio(ids_sitios()[0], experimentos.evaluar_formato)  # experimento global
    if not ok:
        sys.exit(1)  # GitHub avisa por email


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if os.environ.get("PAUSADO") == "1":
        print("Piloto en pausa.")
        return
    args = sys.argv[1:]
    cmd = args[0] if args else "estado"
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
    elif cmd in ("configurar", "investigar", "publicar", "semanal") and sid:
        fn = {"configurar": publicacion.configurar, "investigar": investigacion.investigar,
              "publicar": publicar, "semanal": semanal}[cmd]
        if not _en_sitio(sid, fn):
            sys.exit(1)
    else:
        print(__doc__)


main()
