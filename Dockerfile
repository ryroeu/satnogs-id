# satnogs-id image. The container IS the environment (no host venv), matching the sibling repos.
# It bundles Cees Bassa's strf/rffit (the identification engine) + the Python package.
FROM python:3.14-slim

# strf/rffit build deps. pgplot5 is non-free on Debian Trixie and the package is pgplot5-dev.
RUN sed -i 's/^Components: .*/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
      git make gcc gfortran \
      pgplot5-dev libpng-dev libx11-dev libgsl-dev libfftw3-dev libsox-dev dos2unix \
      libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build strf with a minimal headless `-I` identify patch (uses rffit's OWN identify; no reimplement).
RUN git clone --depth 1 https://github.com/cbassa/strf.git /opt/strf
COPY scripts/patch_rffit.py /tmp/patch_rffit.py
RUN python3 /tmp/patch_rffit.py /opt/strf/rffit.c && cd /opt/strf && make
ENV ST_DATADIR=/opt/strf
ENV PATH=/opt/strf:${PATH}

WORKDIR /app
COPY pyproject.toml ./
COPY satnogs_id ./satnogs_id
RUN pip install --no-cache-dir -e ".[dev]"
COPY app.py ./

# Default: serve the Gradio Identify view (binds 0.0.0.0:7860). An HF Docker Space runs this CMD;
# local dev overrides it (e.g. `docker compose run --rm app pytest`). Set SatNOGS/HF tokens as
# Space secrets -- shared.config reads them from the environment.
ENV GRADIO_ANALYTICS_ENABLED=False
EXPOSE 7860
CMD ["python", "app.py"]
