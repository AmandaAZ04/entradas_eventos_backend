"""Cambios de estado autorizados, devolución bancaria y restitución de stock."""

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Compra, Entrada, Pago, Reembolso, Sector
from .payments import cliente_webpay, reembolso_confirmado


def verificar_organizador(compra, organizador):
    if (
        not compra.detalles.exists()
        or compra.detalles.exclude(sector__evento__organizador=organizador).exists()
    ):
        raise PermissionDenied("Solo puedes gestionar compras de tus eventos.")


def cambiar_estado_compra(compra_id, organizador, nuevo_estado):
    if nuevo_estado not in {Compra.Estado.CANCELADO, Compra.Estado.ENTREGADO}:
        raise ValidationError("Estado no permitido.")
    compra = Compra.objects.get(pk=compra_id)
    verificar_organizador(compra, organizador)
    if compra.estado == nuevo_estado:
        return compra
    if compra.estado != Compra.Estado.PAGADO:
        raise ValidationError("Solo puedes cancelar o entregar una compra pagada.")
    if nuevo_estado == Compra.Estado.CANCELADO and compra.pago_id:
        # El intento se guarda ANTES de contactar al banco. Si la conexión se
        # corta después de devolver dinero, no repetimos una devolución incierta.
        with transaction.atomic():
            Pago.objects.select_for_update().get(pk=compra.pago_id)
            compra = Compra.objects.select_for_update().get(pk=compra_id)
            if compra.estado == Compra.Estado.CANCELADO:
                return compra
            if compra.estado != Compra.Estado.PAGADO:
                raise ValidationError("Esta compra ya no puede cancelarse.")
            intento, creado = Reembolso.objects.get_or_create(
                compra=compra, defaults={"estado": "SOLICITADO"}
            )
            if not creado and intento.estado != "CONFIRMADO":
                raise ValidationError(
                    "La devolución anterior necesita conciliación. No se repetirá el cobro ni el reembolso."
                )
        if creado:
            try:
                respuesta = cliente_webpay(compra.pago.ambiente).refund(
                    compra.pago.token, int(compra.total)
                )
                confirmado = reembolso_confirmado(respuesta)
            except Exception:
                confirmado = False
            intento.estado = "CONFIRMADO" if confirmado else "REVISION"
            intento.save(update_fields=["estado"])
            if not confirmado:
                raise ValidationError(
                    "Webpay no confirmó la devolución. La compra sigue pagada y requiere revisión."
                )
    return aplicar_estado(compra_id, organizador, nuevo_estado)


@transaction.atomic
def aplicar_estado(compra_id, organizador, nuevo_estado):
    referencia = Compra.objects.get(pk=compra_id)
    if referencia.pago_id:
        Pago.objects.select_for_update().get(pk=referencia.pago_id)
    compra = Compra.objects.select_for_update().get(pk=compra_id)
    verificar_organizador(compra, organizador)
    if compra.estado == nuevo_estado:
        return compra
    if compra.estado != Compra.Estado.PAGADO:
        raise ValidationError("Solo puedes cancelar o entregar una compra pagada.")
    # No se puede entregar mientras se devuelve el dinero.
    if (
        nuevo_estado == Compra.Estado.ENTREGADO
        and Reembolso.objects.filter(compra=compra).exists()
    ):
        raise ValidationError("Esta compra tiene una devolución en curso.")
    entradas = Entrada.objects.filter(detalle__compra=compra)
    if nuevo_estado == Compra.Estado.CANCELADO:
        if (
            compra.pago_id
            and not Reembolso.objects.filter(
                compra=compra, estado="CONFIRMADO"
            ).exists()
        ):
            raise ValidationError(
                "El banco debe confirmar la devolución antes de cancelar."
            )
        detalles = list(compra.detalles.order_by("sector_id"))
        sectores = {
            s.pk: s
            for s in Sector.objects.select_for_update()
            .filter(pk__in=[d.sector_id for d in detalles])
            .order_by("pk")
        }
        for detalle in detalles:
            sector = sectores[detalle.sector_id]
            sector.stock += detalle.cantidad
            sector.save(update_fields=["stock"])
        entradas.update(valida=False)
    else:
        entradas.update(utilizada=True)
    compra.estado = nuevo_estado
    compra.save(update_fields=["estado"])
    return compra
