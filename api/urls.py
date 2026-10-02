from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    RecintoViewSet,
    EventoViewSet,
    SectorViewSet,
    CarroTicketsViewSet,
    CompraViewSet,
    MisEntradasViewSet,
)


# El router genera automáticamente las rutas del catálogo.
router = DefaultRouter()
router.register("recintos", RecintoViewSet, basename="recinto")
router.register("eventos", EventoViewSet, basename="evento")
router.register("sectores", SectorViewSet, basename="sector")
router.register("carro-tickets", CarroTicketsViewSet, basename="carro-tickets")
router.register(
    "compras",
    CompraViewSet,
    basename="compra",
)
router.register(
    "mis-entradas",
    MisEntradasViewSet,
    basename="mis-entradas",
)

urlpatterns = [
    path("token/", LoginView.as_view(), name="token_obtain_pair"),
    path(
        "token/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),
    path("", include(router.urls)),
]