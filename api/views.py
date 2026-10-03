from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .filters import EventoFilter, SectorFilter
from .models import (
    Carro,
    Compra,
    Entrada,
    Evento,
    ItemCarro,
    Pago,
    Recinto,
    Sector,
    Usuario,
)
from .permissions import EsEspectador, EsOrganizador, LecturaPublicaOrganizador
from .serializer import (
    CambiarEstadoCompraSerializer,
    CompraSerializer,
    EntradaSerializer,
    EventoSerializer,
    ItemCarroSerializer,
    LoginSerializer,
    MapaSectorSerializer,
    PagoSerializer,
    RecintoSerializer,
    RegistroSerializer,
    SectorSerializer,
)
from .services import cambiar_estado_compra
from .payments import confirmar_pago, iniciar_pago
from .seating import asientos_ocupados


# Alta pública de espectadores para utilizar la tienda desde el navegador.
class RegistroView(CreateAPIView):
    serializer_class = RegistroSerializer
    throttle_scope = "registro"
    permission_classes = [AllowAny]
    authentication_classes = []


# Permite iniciar sesión sin tener un token previo.
# SimpleJWT verifica el usuario y la contraseña.
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"
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
    filterset_class = EventoFilter

    def get_queryset(self):
        queryset = Evento.objects.select_related(
            "recinto", "organizador"
        ).prefetch_related("sectores")

        usuario = self.request.user

        if usuario.is_authenticated:
            return queryset.filter(Q(activo=True) | Q(organizador=usuario)).order_by(
                "fecha_hora"
            )

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

    # La geometría es común; los números y las ventas pertenecen a cada evento.
    @extend_schema(responses=MapaSectorSerializer(many=True))
    @action(detail=True, methods=["get"])
    def asientos(self, request, pk=None):
        evento = self.get_object()
        sectores = evento.sectores.prefetch_related("asientos").order_by("id")
        contexto = {
            **self.get_serializer_context(),
            "ocupados": asientos_ocupados([s.pk for s in sectores]),
        }
        return Response(
            MapaSectorSerializer(sectores, many=True, context=contexto).data
        )


# Permite crear sectores y consultar su disponibilidad.
# Los cambios de stock se implementarán en el flujo de compras.
class SectorViewSet(viewsets.ModelViewSet):
    serializer_class = SectorSerializer
    permission_classes = [LecturaPublicaOrganizador]
    filterset_class = SectorFilter
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = Sector.objects.select_related("evento")
        usuario = self.request.user

        if usuario.is_authenticated:
            return queryset.filter(
                Q(evento__activo=True) | Q(evento__organizador=usuario)
            ).order_by("nombre")

        return queryset.filter(evento__activo=True).order_by("nombre")


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
        # Swagger genera el esquema sin un espectador autenticado.
        if getattr(self, "swagger_fake_view", False):
            return ItemCarro.objects.none()

        return (
            ItemCarro.objects.filter(carro__usuario=self.request.user)
            .select_related(
                "sector",
                "sector__evento",
            )
            .order_by("id")
        )

    # Bloquea el carro mientras se modifica para evitar
    # perder cantidades cuando llegan peticiones simultáneas.
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        carro, _ = Carro.objects.get_or_create(usuario=request.user)
        carro = Carro.objects.select_for_update().get(pk=carro.pk)

        sector = serializer.validated_data["sector"]
        cantidad = serializer.validated_data["cantidad"]
        asientos = serializer.validated_data.get("asientos", [])

        actual = ItemCarro.objects.filter(carro=carro, sector=sector).first()
        if actual and set(actual.asientos).intersection(asientos):
            raise ValidationError({"asientos": "Este asiento ya está en tu carro."})
        if cantidad + (actual.cantidad if actual else 0) > min(20, sector.stock):
            raise ValidationError(
                {
                    "cantidad": "No puedes superar 20 entradas ni el stock disponible del sector."
                }
            )

        item, creado = ItemCarro.objects.get_or_create(
            carro=carro,
            sector=sector,
            defaults={"cantidad": cantidad, "asientos": asientos},
        )

        if not creado:
            item.cantidad += cantidad
            item.asientos += asientos
            item.save(update_fields=["cantidad", "asientos"])

        # Aquí no se descuenta stock ni se garantiza disponibilidad.
        # La validación definitiva se realizará al pagar.
        return Response(
            self.get_serializer(item).data,
            status=(status.HTTP_201_CREATED if creado else status.HTTP_200_OK),
        )

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        carro = Carro.objects.filter(usuario=request.user).select_for_update().first()

        # get_object usa el queryset del usuario:
        # un ID ajeno devuelve 404 y no puede eliminarse.
        item = self.get_object()
        item.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# El espectador consulta sus compras.
# El organizador consulta y gestiona ventas de sus eventos.
class CompraViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CompraSerializer
    filter_backends = []

    def get_permissions(self):
        if self.action in {"pagar", "conciliar"}:
            return [EsEspectador()]

        if self.action == "estado":
            return [EsOrganizador()]

        return [IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Compra.objects.none()

        usuario = self.request.user
        queryset = Compra.objects.prefetch_related(
            "detalles__entradas",
            "detalles__sector__evento",
        )

        if usuario.rol == Usuario.Rol.ORGANIZADOR:
            return queryset.filter(
                detalles__sector__evento__organizador=usuario
            ).distinct()

        return queryset.filter(usuario=usuario)

    # Checkout exclusivo del espectador.
    @extend_schema(
        request=None,
        responses={201: PagoSerializer},
        description="Genera compras pendientes y devuelve la sesión de pago Webpay Plus.",
    )
    @action(detail=False, methods=["post"])
    def pagar(self, request):
        pago = iniciar_pago(
            request.user, request.build_absolute_uri(reverse("webpay-retorno"))
        )

        return Response(
            PagoSerializer(pago).data,
            status=status.HTTP_201_CREATED,
        )

    # Recuperación manual del propietario sin confirmar una sesión sin autorizar.
    @extend_schema(request=None, responses={200: CompraSerializer(many=True)})
    @action(detail=False, methods=["post"])
    def conciliar(self, request):
        pendientes = Pago.objects.filter(
            usuario=request.user, estado=Pago.Estado.PENDIENTE, token__isnull=False
        ).order_by("-creada")[:5]
        for pago in pendientes:
            confirmar_pago(pago.token, confirmar=False)
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    # PATCH /api/compras/{id}/estado/
    @extend_schema(
        request=CambiarEstadoCompraSerializer,
        responses={200: CompraSerializer},
    )
    @action(detail=True, methods=["patch"])
    def estado(self, request, pk=None):
        compra = self.get_object()

        serializer = CambiarEstadoCompraSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        compra = cambiar_estado_compra(
            compra_id=compra.pk,
            organizador=request.user,
            nuevo_estado=serializer.validated_data["estado"],
        )

        return Response(self.get_serializer(compra).data)


# Cada espectador consulta exclusivamente sus propias entradas.
class MisEntradasViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EntradaSerializer
    permission_classes = [EsEspectador]
    filter_backends = []

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Entrada.objects.none()

        return (
            Entrada.objects.filter(detalle__compra__usuario=self.request.user)
            .select_related("detalle__sector__evento", "detalle__compra__pago", "asiento")
            .order_by("-emitida")
        )
