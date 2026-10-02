import django_filters

from .models import Evento, Sector


# Búsqueda de eventos por nombre, artista, ciudad y fechas.
class EventoFilter(django_filters.FilterSet):
    nombre = django_filters.CharFilter(
        lookup_expr="icontains"
    )
    artista = django_filters.CharFilter(
        lookup_expr="icontains"
    )
    ciudad = django_filters.CharFilter(
        field_name="recinto__ciudad",
        lookup_expr="icontains",
    )
    fecha_desde = django_filters.IsoDateTimeFilter(
        field_name="fecha_hora",
        lookup_expr="gte",
    )
    fecha_hasta = django_filters.IsoDateTimeFilter(
        field_name="fecha_hora",
        lookup_expr="lte",
    )

    class Meta:
        model = Evento
        fields = ["recinto", "activo"]


# Filtrado de sectores por evento, precio y disponibilidad.
class SectorFilter(django_filters.FilterSet):
    precio_min = django_filters.NumberFilter(
        field_name="precio",
        lookup_expr="gte",
    )
    precio_max = django_filters.NumberFilter(
        field_name="precio",
        lookup_expr="lte",
    )
    stock_min = django_filters.NumberFilter(
        field_name="stock",
        lookup_expr="gte",
    )

    class Meta:
        model = Sector
        fields = ["evento"]