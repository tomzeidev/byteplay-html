FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CMS_DATABASE=/data/cms.sqlite3 CMS_UPLOADS=/data/uploads
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
COPY backend/wheels /wheels
ARG CMS_OFFLINE=false
RUN if [ "$CMS_OFFLINE" = "true" ]; then \
      pip install --no-cache-dir --no-index --find-links=/wheels -r backend/requirements.txt; \
    else pip install --no-cache-dir -r backend/requirements.txt; fi
COPY --chown=10001:10001 backend /app/backend
# Historical source posts are needed only for the initial import.
COPY --chown=10001:10001 posts /app/posts
COPY --chown=10001:10001 developer-blog.html post1.html post2.html post3.html post4.html post5.html post6.html post8.html /app/
COPY --chown=10001:10001 img /app/img
COPY --chown=10001:10001 *.png *.PNG *.jpg *.webp /app/
RUN useradd --uid 10001 --create-home cms && mkdir /data && chown cms:cms /data
USER cms
EXPOSE 8080
CMD ["gunicorn", "--no-control-socket", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "2", "backend.app:create_app()"]
