FROM python:3.12-slim

WORKDIR /app

# Copy source tree before install so `pip install .` can resolve the backend package
# (see [tool.setuptools.packages.find] include = ["backend*"] in pyproject.toml)
COPY pyproject.toml .
COPY backend ./backend

RUN pip install --no-cache-dir .

# Run as a non-root user; give the app full ownership of its workdir so it can
# write runtime artifacts (model caches, Excel export output, static assets).
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]