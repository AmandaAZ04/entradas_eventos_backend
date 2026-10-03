"""Prepara localidades numeradas sin restituir stock ni eliminar ventas."""

from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import Asiento, Entrada, Evento, Recinto


class Command(BaseCommand):
    help = "Distribuye la cartelera en ciudades y configura el plano común de asientos."

    @transaction.atomic
    def handle(self, *args, **options):
        ciudades = [
            "Santiago",
            "Viña del Mar",
            "Concepción",
            "Valparaíso",
            "Antofagasta",
            "La Serena",
            "Temuco",
        ]
        for i, evento in enumerate(Evento.objects.filter(es_demo=True).order_by("id")):
            ciudad = ciudades[i % len(ciudades)]
            recinto, _ = Recinto.objects.get_or_create(
                nombre=f"Arena Encore · {ciudad}",
                ciudad=ciudad,
                defaults={"direccion": f"Acceso principal Arena Encore, {ciudad}"},
            )
            evento.recinto = recinto
            evento.descripcion = f"Vive una noche de música con {evento.artista} en {ciudad}. Elige tu zona, encuentra tu asiento y prepárate para cantar cada canción."
            evento.save(update_fields=["recinto", "descripcion"])
            for sector in evento.sectores.order_by("pk"):
                # Incluye las entradas vendidas; repetir el comando conserva los mismos IDs.
                entradas = list(
                    Entrada.objects.filter(
                        detalle__sector=sector, valida=True
                    ).order_by("pk")
                )
                capacidad = max(sector.stock + len(entradas), sector.asientos.count())
                for n in range(capacidad):
                    fila = chr(65 + n // 10) if n // 10 < 26 else f"F{n // 10 + 1}"
                    Asiento.objects.get_or_create(
                        sector=sector, fila=fila, numero=n % 10 + 1
                    )
                asignados = set(
                    Entrada.objects.filter(
                        asiento__sector=sector, valida=True
                    ).values_list("asiento_id", flat=True)
                )
                disponibles = iter(
                    sector.asientos.exclude(pk__in=asignados).order_by("fila", "numero")
                )
                for entrada in entradas:
                    if entrada.asiento_id is None:
                        entrada.asiento = next(disponibles)
                        entrada.save(update_fields=["asiento"])
        self.stdout.write(
            self.style.SUCCESS(
                "Ciudades y localidades numeradas configuradas sin cambiar el stock."
            )
        )
