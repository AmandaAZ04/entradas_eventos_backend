import json
from django.conf import settings
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from api.models import Usuario, Recinto, Evento, Sector


class Command(BaseCommand):
    help = "Carga trece conciertos ficticios para la presentación académica."

    @transaction.atomic
    def handle(self, *args, **options):
        # No modifica eventos existentes ni asigna una contraseña pública.
        organizador = Usuario.objects.filter(rol="ORGANIZADOR").first()
        if organizador is None:
            organizador = Usuario.objects.create_user(
                username="organizador_demo", rol="ORGANIZADOR"
            )
        recinto, _ = Recinto.objects.get_or_create(
            nombre="Arena Encore · Santiago",
            defaults={
                "direccion": "Acceso principal Arena Encore, Santiago",
                "ciudad": "Santiago",
            },
        )
        carteles = [
            (
                "TVXQ!",
                "RED OCEAN",
                45,
                "https://prcdn.freetls.fastly.net/release_image/5358/573/5358-573-0ba0ecbbd3c0a0f856f9c6e01510a5ae-3059x2039.jpg?auto=webp&fit=bounds&format=jpeg&height=1260&width=2400",
            ),
            (
                "ALPHA DRIVE ONE",
                "THE FIRST CHAPTER",
                60,
                "https://6.soompi.io/wp-content/uploads/image/20260112082521_ald1.jpg?e=t&s=900x600",
            ),
            (
                "Taylor Swift",
                "A NIGHT TO REMEMBER",
                75,
                "https://lumiere-a.akamaihd.net/v1/images/b577705257690e1467a1dc7e1bb8ea50_4096x2732_55e32d50.jpeg?region=0%2C0%2C4096%2C2732",
            ),
        ]
        imagenes = json.loads(
            (settings.BASE_DIR / "static/encore/image_credits.json").read_text(
                encoding="utf-8"
            )
        )
        adicionales = [
            ("Billie Eilish", "Billie Eilish", "WHEN THE LIGHTS GO DOWN", "POP"),
            ("DAY6", "Day6", "SING IT TOGETHER", "KPOP"),
            ("TXT", "Tomorrow X Together", "OUR NEXT CHAPTER", "KPOP"),
            ("BABYMONSTER", "Babymonster", "TURN IT UP", "KPOP"),
            ("aespa", "Aespa", "INTO THE NEXT WORLD", "KPOP"),
            ("NCT WISH", "NCT Wish", "MAKE A WISH", "KPOP"),
            ("Santos Bravos", "Santos Bravos", "UNA NOCHE MÁS", "POP"),
            ("Red Velvet", "Red Velvet (group)", "VELVET NIGHTS", "KPOP"),
            ("ZEROBASEONE", "Zerobaseone", "FROM ZERO TO YOU", "KPOP"),
            ("Wanna One", "Wanna One", "ONE MORE MEMORY", "KPOP"),
        ]
        categorias = {"Taylor Swift": "POP", "TVXQ!": "KPOP", "ALPHA DRIVE ONE": "KPOP"}
        for i, (artista, referencia, nombre, categoria) in enumerate(adicionales):
            carteles.append(
                (artista, nombre, 85 + i * 8, imagenes[referencia]["image"])
            )
            categorias[artista] = categoria
        for artista, nombre, dias, imagen in carteles:
            evento, creado = Evento.objects.get_or_create(
                nombre=nombre,
                artista=artista,
                es_demo=True,
                defaults={
                    "categoria": categorias[artista],
                    "organizador": organizador,
                    "recinto": recinto,
                    "fecha_hora": (timezone.now() + timedelta(days=dias)).replace(
                        hour=23, minute=0, second=0, microsecond=0
                    ),
                    "imagen_url": imagen,
                    "descripcion": "Concierto ficticio para demostrar la plataforma. Fecha, recinto y precios de ejemplo; no corresponde a una venta oficial.",
                },
            )
            if evento.categoria == "OTROS":
                evento.categoria = categorias[artista]
                evento.save(update_fields=["categoria"])
            if creado:
                for sector, precio, stock in [
                    ("Cancha general", 35000, 120),
                    ("Tribuna", 55000, 80),
                    ("VIP", 85000, 40),
                ]:
                    Sector.objects.create(
                        evento=evento, nombre=sector, precio=precio, stock=stock
                    )
        call_command("configurar_recintos", stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                "Cartelera de demostración lista. No se modificaron eventos existentes."
            )
        )
