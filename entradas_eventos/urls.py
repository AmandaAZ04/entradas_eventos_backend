from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework.permissions import AllowAny
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from api.web_views import inicio, webpay_retorno, pagina_no_encontrada

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
    # Siempre al final: las rutas reales tienen prioridad. API y archivos
    # conservan su 404 para no devolver HTML como si fuera JSON o una imagen.
    re_path(
        r"^(?!(?:api|admin|static|media)(?:/|$)).+$",
        pagina_no_encontrada,
        name="pagina-no-encontrada",
    ),
]
