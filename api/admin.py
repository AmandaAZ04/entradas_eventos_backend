from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario, Recinto, Evento, Sector, Pago, Reembolso
from .seating import generar_asientos


# Permite administrar usuarios y asignar sus roles
# desde el panel administrativo de Django.
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Rol del sistema", {"fields": ("rol",)}),
        ("Identificación", {"fields": ("extranjero", "rut", "documento_extranjero")}),
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
    list_filter = ("activo", "recinto", "categoria", "es_demo")
    search_fields = ("nombre", "artista")


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "evento", "precio", "stock")
    list_filter = ("evento",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            generar_asientos(obj)


# Auditoría sin cambiar estados, inventario ni tokens manualmente.
class AuditoriaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Pago)
class PagoAdmin(AuditoriaAdmin):
    list_display = ("orden", "usuario", "total", "estado", "ambiente", "creada")
    list_filter = ("estado", "ambiente")
    search_fields = ("orden", "usuario__username")
    exclude = ("token", "url")


@admin.register(Reembolso)
class ReembolsoAdmin(AuditoriaAdmin):
    list_display = ("compra", "estado", "creado")
    list_filter = ("estado",)
