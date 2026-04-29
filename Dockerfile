FROM python:3.14-slim-bookworm AS builder

# Copy uv from the official distroless image
# COPY astral-sh/uv:latest /uv /uvx /bin/
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory
WORKDIR /app

# Install dependencies using intermediate layers for better caching
# This allows dependencies to be cached separately from the project code
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --group prod

# Copy the project into the image
ADD . /app

# Sync the project (install the project itself)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --group prod

# -----------------------------------------------------------------------------
# Production stage
FROM python:3.14-slim-bookworm

# Copy uv from the official distroless image
# COPY --from=astral-sh/uv:latest /uv /uvx /bin/
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies required by Python packages
# Add this block here to ensure system libs are available before Python deps are installed
RUN apt-get update 

RUN apt-get install -y --fix-missing ffmpeg

# Set the working directory
WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy the project files
COPY --from=builder /app /app

# Fix line endings if built on Windows (optional but safe)
# Install dos2unix in the builder stage or use sed/tr here
RUN find /app -type f -name "*.sh" -exec sed -i 's/\r$//' {} +

# Make the scripts executable
RUN chmod a+x /app/scripts/*.sh

# Activate the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Expose the port Django runs on
EXPOSE 8000

ENTRYPOINT ["./scripts/command.server.sh"]
