"""Disponibilidad de sillas: venta confirmada o reserva de checkout vigente."""

from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Asiento, Compra, DetalleCompra, Entrada, Pago


def asientos_ocupados(sector_ids, excluir_pago=None):
    ocupados = set(
        Entrada.objects.filter(valida=True, asiento__sector_id__in=sector_ids)
        .exclude(asiento=None)
        .values_list("asiento_id", flat=True)
    )
    pendientes = DetalleCompra.objects.filter(
        sector_id__in=sector_ids,
        compra__estado=Compra.Estado.PENDIENTE,
        compra__pago__estado=Pago.Estado.PENDIENTE,
        compra__pago__creada__gt=timezone.now() - timedelta(minutes=15),
    )
    if excluir_pago:
        pendientes = pendientes.exclude(compra__pago_id=excluir_pago)
    for seleccion in pendientes.values_list("asientos", flat=True):
        ocupados.update(seleccion)
    return ocupados


def validar_asientos(sector, ids, cantidad, ocupados=None):
    if not ids:
        if sector.asientos.exists():
            raise ValidationError(
                {"asientos": "Elige tus asientos en el mapa antes de continuar."}
            )
        return
    if len(ids) != cantidad or len(ids) != len(set(ids)):
        raise ValidationError(
            {
                "asientos": "La cantidad debe coincidir con los asientos y no se pueden repetir."
            }
        )
    if Asiento.objects.filter(sector=sector, pk__in=ids).count() != len(ids):
        raise ValidationError(
            {"asientos": "Hay asientos que no pertenecen al sector elegido."}
        )
    ocupados = asientos_ocupados([sector.pk]) if ocupados is None else ocupados
    if ocupados.intersection(ids):
        raise ValidationError(
            {
                "asientos": "Uno de los asientos elegidos ya no está disponible. Selecciona otro en el mapa."
            }
        )


# El plano de cada sector se crea al registrarlo; no modifica el inventario.
def generar_asientos(sector):
    existentes = set(sector.asientos.values_list("fila", "numero"))
    nuevos = []
    for n in range(sector.stock):
        fila = chr(65 + n // 10) if n // 10 < 26 else f"F{n // 10 + 1}"
        numero = n % 10 + 1
        if (fila, numero) not in existentes:
            nuevos.append(Asiento(sector=sector, fila=fila, numero=numero))
    Asiento.objects.bulk_create(nuevos)
