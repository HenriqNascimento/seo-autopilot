"""Elige el publicador del sitio activo (HubSpot o web estática en git) con la misma interfaz."""
from . import estatico, hubspot
from .base import sitio


def cms():
    tipo = sitio()["publicador"]["tipo"]
    if tipo == "hubspot":
        return hubspot
    if tipo == "estatico":
        return estatico
    raise SystemExit(f"{sitio()['nombre']}: publicador '{tipo}' no configurado.")
