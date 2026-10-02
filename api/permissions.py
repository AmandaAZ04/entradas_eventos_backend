from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Usuario


# Lectura pública; escritura exclusiva para organizadores.
class LecturaPublicaOrganizador(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        return (
            request.user.is_authenticated
            and request.user.rol == Usuario.Rol.ORGANIZADOR
        )

    # Cada organizador modifica únicamente sus propios eventos
    # y los sectores asociados a ellos.
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        if hasattr(obj, "organizador_id"):
            return obj.organizador_id == request.user.pk

        if hasattr(obj, "evento"):
            return obj.evento.organizador_id == request.user.pk

        return True

# Solo los espectadores autenticados pueden utilizar el carro.
class EsEspectador(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.rol == Usuario.Rol.ESPECTADOR
        )