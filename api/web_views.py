from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .payments import resultado_pago
from .models import Evento


# Página principal con enlaces y los datos del estudiante.
def inicio(request):
    # La cartelera usa los mismos eventos y sectores que la API.
    eventos = []
    queryset = (
        Evento.objects.filter(activo=True, fecha_hora__gt=timezone.now())
        .select_related("recinto")
        .prefetch_related("sectores")
    )
    for evento in queryset:
        sectores = [
            {
                "id": sector.pk,
                "nombre": sector.nombre,
                "precio": str(sector.precio),
                "stock": sector.stock,
            }
            for sector in evento.sectores.all()
        ]
        eventos.append(
            {
                "id": evento.pk,
                "nombre": evento.nombre,
                "artista": evento.artista,
                "descripcion": evento.descripcion,
                "fecha": evento.fecha_hora.isoformat(),
                "recinto": evento.recinto.nombre,
                "ciudad": evento.recinto.ciudad,
                "imagen": evento.imagen_url,
                "demo": evento.es_demo,
                "sectores": sectores,
                "categoria": evento.get_categoria_display(),
            }
        )
    return render(
        request,
        "inicio.html",
        {
            "eventos": eventos,
            "categorias": Evento.Categoria.choices,
            "webpay_ambiente": settings.WEBPAY_ENVIRONMENT,
            "mensajes_pago": [
                str(m) for m in messages.get_messages(request) if "pago" in m.tags
            ],
        },
    )


# Transbank retorna desde otro dominio por GET o POST. El token se verifica
# contra el proveedor; la vista no acepta estados, totales ni datos bancarios.
@csrf_exempt
@require_http_methods(["GET", "POST"])
def webpay_retorno(request):
    mensaje = resultado_pago(request)
    messages.info(request, mensaje, extra_tags="pago")
    response = redirect("inicio")
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
