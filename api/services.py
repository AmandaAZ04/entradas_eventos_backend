from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    Carro,
    Compra,
    DetalleCompra,
    Entrada,
    Sector,
)
from rest_framework.exceptions import PermissionDenied

# Checkout con pago simulado.
# Si falla cualquier paso, PostgreSQL revierte toda la operación.
@transaction.atomic
def pagar_carro(usuario):
    carro = Carro.objects.select_for_update().filter(
        usuario=usuario
    ).first()

    if carro is None:
        raise ValidationError("El carro está vacío.")

    items = list(carro.items.order_by("sector_id"))

    if not items:
        raise ValidationError("El carro está vacío.")

    # Bloquea los sectores en un orden estable para evitar que
    # dos compradores descuenten simultáneamente el mismo stock.
    sectores = {
        sector.pk: sector
        for sector in Sector.objects.select_for_update(
            of=("self",)
        ).select_related("evento").filter(
            pk__in=[item.sector_id for item in items]
        ).order_by("pk")
    }

    # Comprueba todo el carro antes de generar las compras.
    grupos = {}

    for item in items:
        sector = sectores[item.sector_id]
        evento = sector.evento

        if not evento.activo or evento.fecha_hora <= timezone.now():
            raise ValidationError(
                f"El evento {evento.nombre} no está disponible."
            )

        if item.cantidad > sector.stock:
            raise ValidationError(
                f"Stock insuficiente en {sector.nombre}. "
                f"Disponibles: {sector.stock}."
            )

        grupos.setdefault(evento.pk, []).append(item)

    compras = []

    # Se genera una compra por evento, conservando los precios
    # y cantidades como parte del historial.
    for items_evento in grupos.values():
        compra = Compra.objects.create(usuario=usuario)
        total = Decimal("0.00")

        for item in items_evento:
            sector = sectores[item.sector_id]

            detalle = DetalleCompra.objects.create(
                compra=compra,
                sector=sector,
                cantidad=item.cantidad,
                precio_unitario=sector.precio,
            )

            total += sector.precio * item.cantidad

            # Una entrada individual por cada ticket comprado.
            # El modelo asigna automáticamente su UUID.
            Entrada.objects.bulk_create([
                Entrada(detalle=detalle)
                for _ in range(item.cantidad)
            ])

        # El pago simulado se aprueba tras validar disponibilidad.
        # El cambio a PAGADO y el descuento se guardan juntos.
        compra.total = total
        compra.estado = Compra.Estado.PAGADO
        compra.save(update_fields=["total", "estado"])

        for item in items_evento:
            sector = sectores[item.sector_id]
            sector.stock -= item.cantidad
            sector.save(update_fields=["stock"])

        compras.append(compra)

    # Se vacían los ítems, conservando el carro del usuario.
    carro.items.all().delete()

    return compras

# Cambia el estado, las entradas y el stock en una sola operación.
@transaction.atomic
def cambiar_estado_compra(compra_id, organizador, nuevo_estado):
    compra = Compra.objects.select_for_update().get(
        pk=compra_id
    )

    detalles = list(compra.detalles.order_by("sector_id"))

    # Verifica que todos los detalles pertenezcan al organizador.
    if not detalles or compra.detalles.exclude(
        sector__evento__organizador=organizador
    ).exists():
        raise PermissionDenied(
            "Solo puedes gestionar compras de tus eventos."
        )

    if nuevo_estado not in {
        Compra.Estado.CANCELADO,
        Compra.Estado.ENTREGADO,
    }:
        raise ValidationError("Estado no permitido.")

    # Repetir la petición no duplica la devolución del stock.
    if compra.estado == nuevo_estado:
        return compra

    if compra.estado != Compra.Estado.PAGADO:
        raise ValidationError(
            "Solo puedes cancelar o entregar una compra pagada."
        )

    entradas = Entrada.objects.filter(
        detalle__compra=compra
    )

    if nuevo_estado == Compra.Estado.CANCELADO:
        # Los sectores se bloquean en el mismo orden del pago.
        sectores = {
            sector.pk: sector
            for sector in Sector.objects.select_for_update().filter(
                pk__in=[detalle.sector_id for detalle in detalles]
            ).order_by("pk")
        }

        for detalle in detalles:
            sector = sectores[detalle.sector_id]
            sector.stock += detalle.cantidad
            sector.save(update_fields=["stock"])

        # Conserva los UUID como historial, pero invalida los tickets.
        entradas.update(valida=False)

    elif nuevo_estado == Compra.Estado.ENTREGADO:
        entradas.update(utilizada=True)

    compra.estado = nuevo_estado
    compra.save(update_fields=["estado"])

    return compra