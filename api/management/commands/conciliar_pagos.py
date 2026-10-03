"""Recupera pagos pendientes si el navegador no volvió desde Webpay."""

from django.core.management.base import BaseCommand
from rest_framework.exceptions import ValidationError

from api.models import Pago
from api.payments import confirmar_pago


class Command(BaseCommand):
    help = "Consulta Webpay y concilia pagos pendientes. Las devoluciones inciertas requieren revisión comercial."

    def handle(self, *args, **options):
        for pago in Pago.objects.filter(
            estado=Pago.Estado.PENDIENTE, token__isnull=False
        ).iterator():
            try:
                resultado = confirmar_pago(pago.token, confirmar=False)
                self.stdout.write(f"Orden {pago.orden}: {resultado.estado}")
            except ValidationError:
                self.stderr.write(
                    f"Orden {pago.orden}: proveedor no disponible; se conserva pendiente."
                )
