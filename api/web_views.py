from django.shortcuts import render


# Página principal con enlaces y los datos del estudiante.
def inicio(request):
    return render(request, "inicio.html")