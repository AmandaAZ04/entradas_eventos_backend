from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.core.exceptions import ValidationError
from django.utils import timezone
import uuid


# Usuario del sistema: conserva las funciones de Django
# y agrega un rol para controlar los permisos de la API.
class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        ESPECTADOR = "ESPECTADOR", "Espectador"
        ORGANIZADOR = "ORGANIZADOR", "Organizador"

    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.ESPECTADOR,
    )
    rut = models.CharField(max_length=10, unique=True, null=True, blank=True)
    extranjero = models.BooleanField(default=False)
    documento_extranjero = models.CharField(
        max_length=30, unique=True, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="usuario_email_unico",
            )
        ]

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"


# Lugar donde se realizan los eventos.
class Recinto(models.Model):
    nombre = models.CharField(max_length=150)
    direccion = models.CharField(max_length=250)
    ciudad = models.CharField(max_length=100)

    def __str__(self):
        return self.nombre


# Evento administrado por un organizador.
# PROTECT conserva las referencias a usuarios y recintos.
class Evento(models.Model):
    class Categoria(models.TextChoices):
        POP = "POP", "Pop"
        KPOP = "KPOP", "K-pop"
        ROCK = "ROCK", "Rock"
        URBANO = "URBANO", "Urbano"
        ELECTRONICA = "ELECTRONICA", "Electrónica"
        INDIE = "INDIE", "Indie / Alternativo"
        JAZZ = "JAZZ", "Jazz / Blues"
        CLASICA = "CLASICA", "Música clásica"
        TEATRO = "TEATRO", "Teatro / Comedia"
        FAMILIAR = "FAMILIAR", "Familiares"
        OTROS = "OTROS", "Otros eventos"

    categoria = models.CharField(
        max_length=20, choices=Categoria.choices, default=Categoria.OTROS
    )
    # Portada configurable y etiqueta para distinguir eventos académicos.
    imagen_url = models.URLField(max_length=1000, blank=True)
    es_demo = models.BooleanField(default=False)
    nombre = models.CharField(max_length=200)
    artista = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    fecha_hora = models.DateTimeField()
    activo = models.BooleanField(default=True)

    recinto = models.ForeignKey(
        Recinto,
        on_delete=models.PROTECT,
        related_name="eventos",
    )

    organizador = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="eventos",
        limit_choices_to={"rol": Usuario.Rol.ORGANIZADOR},
    )

    class Meta:
        ordering = ["fecha_hora"]

    def __str__(self):
        return f"{self.nombre} - {self.artista}"

    # El administrador también impide fechas nuevas vencidas y portadas inseguras.
    def clean(self):
        super().clean()
        anterior = (
            Evento.objects.filter(pk=self.pk)
            .values_list("fecha_hora", flat=True)
            .first()
            if self.pk
            else None
        )
        if (
            self.fecha_hora
            and self.fecha_hora <= timezone.now()
            and self.fecha_hora != anterior
        ):
            raise ValidationError(
                {"fecha_hora": "La fecha del evento debe ser futura."}
            )
        if self.imagen_url and not self.imagen_url.startswith("https://"):
            raise ValidationError({"imagen_url": "La imagen debe usar HTTPS."})
        if self.organizador_id and self.organizador.rol != Usuario.Rol.ORGANIZADOR:
            raise ValidationError(
                {"organizador": "Selecciona un usuario con rol Organizador."}
            )


# Localidad del evento con precio y entradas disponibles.
# El stock se descontará al pagar, nunca al agregar al carro.
class Sector(models.Model):
    evento = models.ForeignKey(
        Evento,
        on_delete=models.CASCADE,
        related_name="sectores",
    )
    nombre = models.CharField(max_length=100)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["evento", "nombre"],
                name="sector_unico_por_evento",
            ),
            models.CheckConstraint(
                condition=models.Q(precio__gt=0),
                name="sector_precio_positivo",
            ),
        ]

    def __str__(self):
        return f"{self.evento.nombre} - {self.nombre}"

    def clean(self):
        super().clean()
        if self.precio is not None and (
            self.precio <= 0 or self.precio != self.precio.to_integral_value()
        ):
            raise ValidationError(
                {"precio": "El precio debe ser positivo y expresarse en pesos enteros."}
            )


# Cada usuario tiene un carro persistente.
class Asiento(models.Model):
    """La numeración pertenece al sector de un evento, no al recinto completo."""

    sector = models.ForeignKey(
        Sector, on_delete=models.CASCADE, related_name="asientos"
    )
    fila = models.CharField(max_length=4)
    numero = models.PositiveIntegerField()

    class Meta:
        ordering = ["fila", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["sector", "fila", "numero"], name="asiento_unico_sector"
            )
        ]

    @property
    def etiqueta(self):
        return f"{self.fila}-{self.numero:02d}"

    def __str__(self):
        return f"{self.sector} · {self.etiqueta}"


# Cada usuario tiene un carro persistente.
# Cerrar sesión no elimina el carro ni sus ítems.
class Carro(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name="carro",
    )
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Carro de {self.usuario.username}"


# Cada sector aparece una sola vez en el carro.
# Para comprar varias entradas se utiliza cantidad.
class ItemCarro(models.Model):
    carro = models.ForeignKey(
        Carro,
        on_delete=models.CASCADE,
        related_name="items",
    )
    sector = models.ForeignKey(
        Sector,
        on_delete=models.PROTECT,
        related_name="items_carro",
    )
    cantidad = models.PositiveIntegerField(default=1)
    asientos = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["carro", "sector"],
                name="sector_unico_en_carro",
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad__gte=1),
                name="cantidad_carro_positiva",
            ),
        ]

    def __str__(self):
        return f"{self.sector} x {self.cantidad}"


# Registro histórico de la compra y su estado.
# El stock se modifica mediante la lógica de pago y cancelación.
class Pago(models.Model):
    """Una sesión Webpay puede reunir compras de varios eventos."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        AUTORIZADO = "AUTORIZADO", "Autorizado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        CANCELADO = "CANCELADO", "Cancelado"
        REEMBOLSADO = "REEMBOLSADO", "Reembolsado"
        REVISION = "REVISION", "Requiere conciliación"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="pagos")
    orden = models.CharField(max_length=26, unique=True)
    token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    url = models.URLField(max_length=500, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.PENDIENTE
    )
    ambiente = models.CharField(max_length=12, default="integration")
    autorizacion = models.CharField(max_length=20, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total__gt=0), name="pago_total_positivo"
            )
        ]


class Compra(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        PAGADO = "PAGADO", "Pagado"
        ENTREGADO = "ENTREGADO", "Entregado"
        CANCELADO = "CANCELADO", "Cancelado"

    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="compras",
    )
    pago = models.ForeignKey(
        Pago, on_delete=models.PROTECT, related_name="compras", null=True, blank=True
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total__gte=0),
                name="total_compra_no_negativo",
            ),
        ]

    def __str__(self):
        return f"Compra #{self.pk} - {self.estado}"


# Guarda la cantidad y el precio unitario al comprar.
# Cambiar el precio del sector no modifica compras anteriores.
class DetalleCompra(models.Model):
    compra = models.ForeignKey(
        Compra,
        on_delete=models.CASCADE,
        related_name="detalles",
    )
    sector = models.ForeignKey(
        Sector,
        on_delete=models.PROTECT,
        related_name="detalles_compra",
    )
    cantidad = models.PositiveIntegerField()
    asientos = models.JSONField(default=list, blank=True)
    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["compra", "sector"],
                name="sector_unico_en_compra",
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad__gte=1),
                name="cantidad_compra_positiva",
            ),
            models.CheckConstraint(
                condition=models.Q(precio_unitario__gt=0),
                name="precio_detalle_positivo",
            ),
        ]

    def __str__(self):
        return f"Compra #{self.compra_id} - {self.sector}"


# Se generará una entrada por cada ticket comprado.
# uuid.uuid4 crea un código distinto para cada entrada.
class Entrada(models.Model):
    detalle = models.ForeignKey(
        DetalleCompra,
        on_delete=models.PROTECT,
        related_name="entradas",
    )
    codigo = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    valida = models.BooleanField(default=True)
    utilizada = models.BooleanField(default=False)
    asiento = models.ForeignKey(
        Asiento,
        on_delete=models.PROTECT,
        related_name="entradas",
        null=True,
        blank=True,
    )
    emitida = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["asiento"],
                condition=models.Q(valida=True, asiento__isnull=False),
                name="entrada_valida_unica_asiento",
            )
        ]

    def __str__(self):
        return str(self.codigo)


class Reembolso(models.Model):
    """Intento durable: una respuesta incierta nunca permite devolver dinero dos veces."""

    compra = models.OneToOneField(
        Compra, on_delete=models.PROTECT, related_name="reembolso"
    )
    estado = models.CharField(
        max_length=20,
        choices=[
            ("SOLICITADO", "Solicitado"),
            ("CONFIRMADO", "Confirmado"),
            ("REVISION", "Revisión"),
        ],
    )
    creado = models.DateTimeField(auto_now_add=True)
