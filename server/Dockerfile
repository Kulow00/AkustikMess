# Lizenzserver für AkustikMess. Bauen im Projektordner (Kontext = Projektwurzel):
#   docker build -f server/Dockerfile -t akmess-license .
FROM python:3.12-slim
RUN pip install --no-cache-dir "cryptography>=42" \
 && useradd --system --uid 10001 --home /app akmess \
 && mkdir -p /data && chown akmess /data
WORKDIR /app
COPY akustik/__init__.py akustik/license_config.py akustik/licensing.py akustik/
COPY server/license_server.py .
USER akmess
ENV AKM_DATA=/data PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=3)"
CMD ["python", "license_server.py", "serve"]
