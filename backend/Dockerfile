# Wheels are built in a separate stage: praat-parselmouth ships no linux/aarch64 wheel (Apple-silicon hosts),
# so pip compiles it from source there, which needs a C++ toolchain we do not want in the runtime image.
FROM python:3.12-slim AS wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ninja-build && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
RUN pip wheel --no-cache-dir -w /wheels -r /tmp/requirements.lock

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml requirements.lock alembic.ini ./
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links /wheels -r requirements.lock
COPY alembic ./alembic
COPY vocal_coach ./vocal_coach
COPY config.yaml ./config.yaml
COPY entrypoint.sh ./entrypoint.sh
RUN pip install --no-cache-dir --no-deps -e . && chmod +x entrypoint.sh
ENV DATA_DIR=/data HF_HOME=/models
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
