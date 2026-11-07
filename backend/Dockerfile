# =============================================================================
# Stage 1: Build Rust workout-parse module
# =============================================================================
FROM python:3.11-slim AS rust-builder

# Install Rust toolchain and build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin
RUN pip install maturin

# Copy workout-parse source (context is repo root)
WORKDIR /build
COPY workout-parse/ ./workout-parse/

# Build the wheel
WORKDIR /build/workout-parse
RUN maturin build --release --strip

# =============================================================================
# Stage 2: Runtime image
# =============================================================================
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    USE_RUST_PARSER=true

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install the Rust wheel from builder stage
COPY --from=rust-builder /build/workout-parse/target/wheels/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

# Copy and install Python dependencies (paths relative to repo root)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home appuser && mkdir -p scripts

COPY --chown=appuser:appuser backend/app app
COPY --chown=appuser:appuser backend/tools tools
# Independent keeper recompute: only its committed modules, ratified policy,
# and this stack's IDL. Preserve config.py's relative policy path.
COPY --chown=appuser:appuser tools/stage1_reference/__init__.py tools/stage1_reference/keeper.py tools/stage1_reference/arithmetic.py tools/stage1_reference/merkle.py tools/stage1_reference/config.py app/stage1_runtime/tools/stage1_reference/
COPY --chown=appuser:appuser history/hill-bonding-diamond-2026-10-08/diamond.yaml app/stage1_runtime/history/hill-bonding-diamond-2026-10-08/diamond.yaml
COPY --chown=appuser:appuser protocol/anchor/idl/boulder_rollers.json app/stage1_runtime/idl/boulder_rollers.json
COPY --chown=appuser:appuser \
    backend/scripts/apply_sql_migrations.py \
    backend/scripts/check_schema_invariants.py \
    scripts/
COPY --chown=appuser:appuser backend/sql sql
COPY --chown=appuser:appuser backend/idl idl
COPY --chown=appuser:appuser \
    workout-parse/resources/philly_ratified_boundary_3dep_profiles_v1.json \
    resources/philly_ratified_boundary_3dep_profiles_v1.json

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.revision="${APP_VERSION}"

USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
