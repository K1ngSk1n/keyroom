FROM python:3.15-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock .
RUN pip install -r requirements.lock && useradd --uid 10001 --create-home app
COPY app ./app
RUN test -s app/static/keyroom-source.zip && test -s app/static/build-info.json
USER 10001
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
