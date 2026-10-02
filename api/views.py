from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializer import LoginSerializer
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Recinto, Evento, Sector
from .permissions import LecturaPublicaOrganizador
from .serializer import (RecintoSerializer, EventoSerializer, SectorSerializer)
from django.db import transaction
from rest_framework import mixins, status
from .models import Carro, ItemCarro
from .permissions import EsEspectador
from .serializer import ItemCarroSerializer

# Permite iniciar sesión sin tener un token previo.
# SimpleJWT verifica el usuario y la contraseña.
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

# Los recintos forman un catálogo compartido.
# Los organizadores pueden registrarlos y consultarlos.
class RecintoViewSet(viewsets.ModelViewSet):
    queryset = Recinto.objects.all().order_by("nombre")
    serializer_class = RecintoSerializer
    permission_classes = [LecturaPublicaOrganizador]
    http_method_names = ["get", "post", "head", "options"]


# Catálogo público de eventos activos.
# Cada organizador también puede consultar sus eventos inactivos.
class EventoViewSet(viewsets.ModelViewSet):
    serializer_class = EventoSerializer
    permission_classes = [LecturaPublicaOrganizador]
    filterset_fields = ["recinto", "artista", "activo"]

    def get_queryset(self):
        from django.db.models import Q

        queryset = Evento.objects.select_related(
            "recinto", "organizador"
        ).prefetch_related("sectores")

        usuario = self.request.user

        if usuario.is_authenticated:
            return queryset.filter(
                Q(activo=True) | Q(organizador=usuario)
            ).order_by("fecha_hora")

        return queryset.filter(activo=True).order_by("fecha_hora")

    def perform_create(self, serializer):
        serializer.save(organizador=self.request.user)

    # Desactiva el evento conservando su historial de compras.
    def perform_destroy(self, instance):
        instance.activo = False
        instance.save(update_fields=["activo"])

    # GET /api/eventos/{id}/sectores/
    @action(detail=True, methods=["get"])
    def sectores(self, request, pk=None):
        evento = self.get_object()
        serializer = SectorSerializer(
            evento.sectores.all().order_by("nombre"),
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)


# Permite crear sectores y consultar su disponibilidad.
# Los cambios de stock se implementarán en el flujo de compras.
class SectorViewSet(viewsets.ModelViewSet):
    serializer_class = SectorSerializer
    permission_classes = [LecturaPublicaOrganizador]
    filterset_fields = ["evento"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        from django.db.models import Q

        queryset = Sector.objects.select_related("evento")
        usuario = self.request.user

        if usuario.is_authenticated:
            return queryset.filter(
                Q(evento__activo=True)
                | Q(evento__organizador=usuario)
            ).order_by("nombre")

        return queryset.filter(
            evento__activo=True
        ).order_by("nombre")

# Permite listar, agregar y eliminar los ítems del carro.
# Todas las consultas se restringen al usuario autenticado.
class CarroTicketsViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ItemCarroSerializer
    permission_classes = [EsEspectador]
    filter_backends = []

    def get_queryset(self):
        return ItemCarro.objects.filter(
            carro__usuario=self.request.user
        ).select_related(
            "sector",
            "sector__evento",
        ).order_by("id")

    # Bloquea el carro mientras se modifica para evitar
    # perder cantidades cuando llegan peticiones simultáneas.
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        carro, _ = Carro.objects.get_or_create(
            usuario=request.user
        )
        carro = Carro.objects.select_for_update().get(
            pk=carro.pk
        )

        sector = serializer.validated_data["sector"]
        cantidad = serializer.validated_data["cantidad"]

        item, creado = ItemCarro.objects.get_or_create(
            carro=carro,
            sector=sector,
            defaults={"cantidad": cantidad},
        )

        if not creado:
            item.cantidad += cantidad
            item.save(update_fields=["cantidad"])

        # Aquí no se descuenta stock ni se garantiza disponibilidad.
        # La validación definitiva se realizará al pagar.
        return Response(
            self.get_serializer(item).data,
            status=(
                status.HTTP_201_CREATED
                if creado
                else status.HTTP_200_OK
            ),
        )

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        carro = Carro.objects.filter(
            usuario=request.user
        ).select_for_update().first()

        # get_object usa el queryset del usuario:
        # un ID ajeno devuelve 404 y no puede eliminarse.
        item = self.get_object()
        item.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)