from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario, Recinto, Evento, Sector

# Permite administrar usuarios y asignar sus roles
# desde el panel administrativo de Django.
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Rol del sistema", {"fields": ("rol",)}),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Rol del sistema", {"fields": ("rol",)}),
    )

    list_display = (
        "username",
        "email",
        "rol",
        "is_staff",
        "is_active",
    )

    list_filter = UserAdmin.list_filter + ("rol",)

# Administración del catálogo de recintos, eventos y sectores.
@admin.register(Recinto)
class RecintoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "ciudad")
    search_fields = ("nombre", "ciudad")


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "artista",
        "fecha_hora",
        "recinto",
        "organizador",
        "activo",
    )
    list_filter = ("activo", "recinto")
    search_fields = ("nombre", "artista")


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "evento", "precio", "stock")
    list_filter = ("evento",)