from django.contrib import admin
from django.urls import include, path
from rest_framework.permissions import AllowAny
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from api.web_views import inicio, webpay_retorno

# Administración, documentación pública y rutas de la API.
urlpatterns = [
    path("pago/retorno/", webpay_retorno, name="webpay-retorno"),
    path("admin/", admin.site.urls),
    path(
        "api/schema/",
        SpectacularAPIView.as_view(permission_classes=[AllowAny]),
        name="schema",
    ),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(
            url_name="schema",
            permission_classes=[AllowAny],
        ),
        name="swagger-ui",
    ),
    path("api/", include("api.urls")),
    path("", inicio, name="inicio"),
]
