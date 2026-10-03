"""Webpay Plus: sesiones, verificación del proveedor y emisión atómica de tickets."""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from requests.exceptions import ConnectionError, Timeout, SSLError
from transbank.error.transbank_error import TransbankError

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from transbank.common.integration_api_keys import IntegrationApiKeys
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes
from transbank.common.integration_type import IntegrationType
from transbank.common.options import WebpayOptions
from transbank.webpay.webpay_plus.transaction import Transaction

from .models import Carro, Compra, DetalleCompra, Entrada, Pago, Sector
from .seating import asientos_ocupados, validar_asientos

logger = logging.getLogger(__name__)
RESERVA_MINUTOS = 15


def cliente_webpay(ambiente=None):
    ambiente = ambiente or settings.WEBPAY_ENVIRONMENT
    if ambiente == "production":
        if not settings.WEBPAY_COMMERCE_CODE or not settings.WEBPAY_API_KEY:
            raise ValidationError("Falta configurar la cuenta comercial de Webpay.")
        opciones = WebpayOptions(
            settings.WEBPAY_COMMERCE_CODE,
            settings.WEBPAY_API_KEY,
            IntegrationType.LIVE,
            timeout=20,
        )
    elif ambiente == "integration":
        opciones = WebpayOptions(
            IntegrationCommerceCodes.WEBPAY_PLUS,
            IntegrationApiKeys.WEBPAY,
            IntegrationType.TEST,
            timeout=20,
        )
    else:
        raise ValidationError(
            "El ambiente de Webpay no está configurado correctamente."
        )
    return Transaction(opciones)


def URL_checkout_segura(url, ambiente):
    parsed = urlparse(url)
    host = (
        "webpay3g.transbank.cl"
        if ambiente == "production"
        else "webpay3gint.transbank.cl"
    )
    return parsed.scheme == "https" and parsed.netloc == host


# Estas reservas no modifican el stock: solo evitan vender a dos compradores
# el último ticket mientras ambos están en la pantalla bancaria.
def cantidades_reservadas(sector_ids, excluir=None):
    detalles = DetalleCompra.objects.filter(
        sector_id__in=sector_ids,
        compra__estado=Compra.Estado.PENDIENTE,
        compra__pago__estado=Pago.Estado.PENDIENTE,
        compra__pago__creada__gt=timezone.now() - timedelta(minutes=RESERVA_MINUTOS),
    )
    if excluir:
        detalles = detalles.exclude(compra__pago_id=excluir)
    return {
        d["sector_id"]: d["cantidad"]
        for d in detalles.values("sector_id").annotate(cantidad=Sum("cantidad"))
    }


@transaction.atomic
def iniciar_pago(usuario, return_url):
    carro = Carro.objects.select_for_update().filter(usuario=usuario).first()
    items = list(carro.items.order_by("sector_id")) if carro else []
    if not items:
        # Doble clic/reintento de red recupera la misma sesión, sin nuevas compras.
        pendiente = (
            Pago.objects.filter(
                usuario=usuario,
                estado=Pago.Estado.PENDIENTE,
                creada__gt=timezone.now() - timedelta(minutes=RESERVA_MINUTOS),
            )
            .order_by("-creada")
            .first()
        )
        if pendiente and pendiente.token:
            return pendiente
        raise ValidationError("El carro está vacío.")
    sectores = {
        s.pk: s
        for s in Sector.objects.select_for_update(of=("self",))
        .select_related("evento")
        .filter(pk__in=[i.sector_id for i in items])
        .order_by("pk")
    }
    reservados = cantidades_reservadas(sectores.keys())
    ocupados = asientos_ocupados(sectores.keys())
    grupos, total = {}, Decimal("0")
    for item in items:
        sector = sectores[item.sector_id]
        if not sector.evento.activo or sector.evento.fecha_hora <= timezone.now():
            raise ValidationError(
                f"El evento {sector.evento.nombre} ya no está disponible."
            )
        if settings.WEBPAY_ENVIRONMENT == "production" and sector.evento.es_demo:
            raise ValidationError(
                "No se pueden cobrar conciertos ficticios. Registra primero un evento real autorizado."
            )
        disponibles = sector.stock - reservados.get(sector.pk, 0)
        if item.cantidad > disponibles:
            raise ValidationError(
                f"Stock insuficiente en {sector.nombre}. Disponibles: {max(0, disponibles)}."
            )
        if (
            not 1 <= item.cantidad <= 20
            or sector.precio <= 0
            or sector.precio != sector.precio.to_integral_value()
        ):
            raise ValidationError(
                "Cantidad o precio inválido. Webpay utiliza pesos enteros."
            )
        validar_asientos(sector, item.asientos, item.cantidad, ocupados)
        grupos.setdefault(sector.evento_id, []).append(item)
        total += sector.precio * item.cantidad
    if total > Decimal("9999999999"):
        raise ValidationError("El total supera el límite permitido para una compra.")
    retorno = settings.WEBPAY_RETURN_URL or return_url
    if settings.WEBPAY_ENVIRONMENT == "production" and not retorno.startswith(
        "https://"
    ):
        raise ValidationError(
            "Configura una URL HTTPS pública de retorno antes de activar cobros reales."
        )
    cliente = cliente_webpay()
    pago = Pago.objects.create(
        usuario=usuario,
        orden=uuid.uuid4().hex[:26],
        total=total,
        ambiente=settings.WEBPAY_ENVIRONMENT,
    )
    for grupo in grupos.values():
        compra = Compra.objects.create(
            usuario=usuario,
            pago=pago,
            total=sum(sectores[i.sector_id].precio * i.cantidad for i in grupo),
        )
        DetalleCompra.objects.bulk_create(
            [
                DetalleCompra(
                    compra=compra,
                    sector=sectores[i.sector_id],
                    cantidad=i.cantidad,
                    asientos=i.asientos,
                    precio_unitario=sectores[i.sector_id].precio,
                )
                for i in grupo
            ]
        )
    # Reintentar únicamente la creación de una sesión: no autoriza ni cobra.
    # Las confirmaciones y devoluciones conservan su propia conciliación.
    for intento in range(2):
        try:
            respuesta = cliente.create(pago.orden, str(usuario.pk), int(total), retorno)
            if (
                not isinstance(respuesta, dict)
                or not URL_checkout_segura(respuesta.get("url", ""), pago.ambiente)
                or not respuesta.get("token")
            ):
                raise ValueError("Respuesta inválida del proveedor")
            break
        except Exception as error:
            codigo = getattr(error, "code", None)
            temporal = (
                isinstance(error, (Timeout, ConnectionError, TimeoutError))
                and not isinstance(error, SSLError)
            ) or (isinstance(error, TransbankError) and codigo in {502, 503, 504})
            # No imprimir respuesta, credenciales ni token del proveedor.
            logger.warning(
                "Inicio Webpay fallido: tipo=%s codigo=%s intento=%s ambiente=%s",
                type(error).__name__,
                codigo,
                intento + 1,
                pago.ambiente,
            )
            if temporal and intento == 0:
                continue
            if isinstance(error, SSLError):
                mensaje = "No se pudo verificar la conexión segura con Webpay. Revisa la fecha del equipo y la conexión a Internet."
            elif codigo in {401, 403}:
                mensaje = "Webpay rechazó la configuración del comercio. Revisa el ambiente y las credenciales configuradas."
            elif isinstance(error, (Timeout, TimeoutError)):
                mensaje = "Webpay tardó demasiado en responder. Vuelve a intentar en unos momentos."
            elif temporal:
                mensaje = "No pudimos conectarnos con Webpay después de reintentar. Revisa tu conexión y vuelve a intentar."
            else:
                mensaje = "No pudimos abrir una sesión de Webpay. El servidor registró la causa para revisarla."
            # El rollback conserva toda la selección sin tickets ni stock descontado.
            raise ValidationError(mensaje + " Tu carro sigue guardado.") from error
    pago.token, pago.url = respuesta["token"], respuesta["url"]
    pago.save(update_fields=["token", "url"])
    carro.items.all().delete()
    return pago


def coincide_respuesta(pago, respuesta):
    try:
        return (
            respuesta.get("buy_order") == pago.orden
            and str(respuesta.get("session_id")) == str(pago.usuario_id)
            and Decimal(str(respuesta.get("amount"))) == pago.total
        )
    except (ValueError, TypeError, ArithmeticError):
        return False


def reembolso_confirmado(respuesta):
    return respuesta.get("type") == "REVERSED" or (
        respuesta.get("type") in {"NULLIFIED", "REVERSED_PARTIAL"}
        and respuesta.get("response_code") == 0
    )


@transaction.atomic
def confirmar_pago(token, confirmar=True, cancelar=False):
    pago = Pago.objects.select_for_update().filter(token=token).first()
    if not pago:
        raise ValidationError("No encontramos esta sesión de pago.")
    if pago.estado != Pago.Estado.PENDIENTE:
        return pago
    cliente = cliente_webpay(pago.ambiente)
    # Estado recupera confirmaciones que el banco recibió aunque se haya cortado
    # nuestra conexión. Nunca se confía en un estado enviado por el navegador.
    try:
        respuesta = cliente.status(token)
        if respuesta.get("status") == "INITIALIZED" and confirmar:
            respuesta = cliente.commit(token)
    except Exception:
        logger.warning("Webpay requiere reintentar una confirmación")
        raise ValidationError(
            "No pudimos verificar el pago todavía. No repitas la compra; vuelve a consultar tus compras."
        )
    if not coincide_respuesta(pago, respuesta):
        pago.estado = Pago.Estado.REVISION
        pago.save(update_fields=["estado"])
        return pago
    estado = respuesta.get("status")
    if estado == "INITIALIZED" and cancelar:
        # El token de retorno y la consulta bancaria prueban que esta sesión
        # no está pagada; cancelar no toca stock ni ejecuta un reembolso.
        pago.estado = Pago.Estado.CANCELADO
        pago.save(update_fields=["estado"])
        pago.compras.filter(estado=Compra.Estado.PENDIENTE).update(
            estado=Compra.Estado.CANCELADO
        )
        return pago
    if estado in {"FAILED", "ABORTED", "NULLIFIED", "REVERSED"}:
        pago.estado = Pago.Estado.RECHAZADO
        pago.save(update_fields=["estado"])
        pago.compras.filter(estado=Compra.Estado.PENDIENTE).update(
            estado=Compra.Estado.CANCELADO
        )
        return pago
    if estado != "AUTHORIZED" or respuesta.get("response_code") != 0:
        # Una respuesta desconocida no emite entradas ni rechaza un pago incierto.
        return pago
    detalles = list(
        DetalleCompra.objects.filter(compra__pago=pago)
        .select_related("compra")
        .order_by("sector_id")
    )
    sectores = {
        s.pk: s
        for s in Sector.objects.select_for_update(of=("self",))
        .select_related("evento")
        .filter(pk__in=[d.sector_id for d in detalles])
        .order_by("pk")
    }
    reservados = cantidades_reservadas(sectores.keys(), excluir=pago.pk)
    ocupados = asientos_ocupados(sectores.keys(), excluir_pago=pago.pk)
    invalido = any(
        bool(set(d.asientos).intersection(ocupados))
        or not sectores[d.sector_id].evento.activo
        or sectores[d.sector_id].evento.fecha_hora <= timezone.now()
        or d.cantidad > sectores[d.sector_id].stock - reservados.get(d.sector_id, 0)
        for d in detalles
    )
    if invalido:
        # Una reserva vencida puede perder su cupo. Se revierte el cobro recibido
        # y no se emite ningún ticket; una devolución incierta exige conciliación.
        try:
            confirmado = reembolso_confirmado(cliente.refund(token, int(pago.total)))
        except Exception:
            confirmado = False
        pago.estado = Pago.Estado.REEMBOLSADO if confirmado else Pago.Estado.REVISION
        pago.save(update_fields=["estado"])
        pago.compras.update(
            estado=Compra.Estado.CANCELADO if confirmado else Compra.Estado.PENDIENTE
        )
        return pago
    for detalle in detalles:
        sector = sectores[detalle.sector_id]
        sector.stock -= detalle.cantidad
        sector.save(update_fields=["stock"])
        Entrada.objects.bulk_create(
            [
                Entrada(
                    detalle=detalle,
                    asiento_id=detalle.asientos[i] if detalle.asientos else None,
                )
                for i in range(detalle.cantidad)
            ]
        )
    pago.compras.update(estado=Compra.Estado.PAGADO)
    pago.estado = Pago.Estado.AUTORIZADO
    pago.autorizacion = str(respuesta.get("authorization_code", ""))[:20]
    pago.save(update_fields=["estado", "autorizacion"])
    return pago


def resultado_pago(request):
    """Solo expone el resultado genérico; los tickets requieren JWT del propietario."""
    token = request.POST.get("token_ws") or request.GET.get("token_ws")
    abortado = request.POST.get("TBK_TOKEN") or request.GET.get("TBK_TOKEN")
    if not token and abortado:
        # Consulta al proveedor incluso en un retorno de cancelación.
        token = abortado
    if not token or len(token) > 64:
        return "No recibimos una sesión de Webpay válida. Revisa tus compras antes de volver a pagar."
    try:
        pago = confirmar_pago(
            token, confirmar=not bool(abortado), cancelar=bool(abortado)
        )
    except ValidationError as error:
        return (
            str(error.detail[0])
            if isinstance(error.detail, list)
            else str(error.detail)
        )
    return {
        Pago.Estado.AUTORIZADO: "¡Pago aprobado! Tus entradas ya están disponibles en tu cuenta.",
        Pago.Estado.RECHAZADO: "El pago fue rechazado o cancelado. No se emitieron entradas.",
        Pago.Estado.CANCELADO: "Cancelaste el pago. No se realizó ningún cobro ni se emitieron entradas.",
        Pago.Estado.REEMBOLSADO: "La disponibilidad cambió y Webpay confirmó la devolución. No se emitieron entradas.",
        Pago.Estado.REVISION: "El pago requiere revisión. No vuelvas a pagar: consulta con el organizador.",
    }.get(
        pago.estado,
        "Tu pago todavía está pendiente de confirmación. Consulta tus compras.",
    )
