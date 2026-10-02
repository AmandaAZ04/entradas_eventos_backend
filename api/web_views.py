from django.shortcuts import render
from django.utils import timezone
from .models import Evento


# Página principal con enlaces y los datos del estudiante.
def inicio(request):
    # La cartelera usa los mismos eventos y sectores que la API.
    eventos = []
    queryset = Evento.objects.filter(
        activo=True, fecha_hora__gt=timezone.now()
    ).select_related("recinto").prefetch_related("sectores")
    for evento in queryset:
        sectores = [
            {"id": sector.pk, "nombre": sector.nombre,
             "precio": str(sector.precio), "stock": sector.stock}
            for sector in evento.sectores.all()
        ]
        eventos.append({
            "id": evento.pk, "nombre": evento.nombre,
            "artista": evento.artista, "descripcion": evento.descripcion,
            "fecha": evento.fecha_hora.isoformat(),
            "recinto": evento.recinto.nombre, "ciudad": evento.recinto.ciudad,
            "imagen": evento.imagen_url, "demo": evento.es_demo,
            "sectores": sectores,
        })
    return render(request, "inicio.html", {"eventos": eventos})
