from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


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