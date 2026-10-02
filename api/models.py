from django.contrib.auth.models import AbstractUser
from django.db import models


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