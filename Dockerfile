# =====================================================================
# [CONCEPTO: Docker — Containerización]
# Un Dockerfile define cómo construir una imagen de tu aplicación.
# La imagen es un paquete portable que incluye tu código + dependencias
# y corre igual en cualquier máquina que tenga Docker.
#
# Aprende más: "Docker tutorial for beginners"
# Curso: "Docker and Kubernetes: The Complete Guide" (Udemy)
# =====================================================================

# Imagen base: Python 3.12 en Debian Slim (imagen pequeña, ~50MB)
FROM python:3.12-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# [CONCEPTO: Capas de Docker y caché]
# Copiamos requirements.txt PRIMERO y los instalamos ANTES de copiar el código.
# Si no cambias las dependencias, Docker usa la capa cacheada y el build es rápido.
# Si copias todo junto, cualquier cambio en el código re-instala dependencias.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Crear directorio para la base de datos
RUN mkdir -p data

# El comando que se ejecuta cuando el contenedor arranca
CMD ["python", "-m", "bot.main"]
