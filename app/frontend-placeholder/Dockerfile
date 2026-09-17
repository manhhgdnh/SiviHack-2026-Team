# Placeholder that serves a static page on :3000 so nginx "/" has a target.
# The real frontend lives at ../../frontend — replace this service with its build.
FROM python:3.12-slim
WORKDIR /app
RUN printf '<h1>frontend placeholder</h1><p>The real app is at ../frontend (Vite). API is under /api/.</p>' > index.html
EXPOSE 3000
CMD ["python", "-m", "http.server", "3000"]
