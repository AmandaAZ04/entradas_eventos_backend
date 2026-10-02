from django.contrib.auth.models import AbstractUser
from django.db import models
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
    emitida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.codigo)