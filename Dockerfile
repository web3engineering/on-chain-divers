# syntax=docker/dockerfile:1

FROM python:3.12-slim AS checker-base

WORKDIR /app

COPY scripts/requirements.txt ./scripts/requirements.txt
RUN pip install --no-cache-dir --requirement scripts/requirements.txt

COPY scripts ./scripts
COPY examples ./examples
COPY docs ./docs

FROM checker-base AS checker

# Database credentials are available only for this command and are not stored
# in this stage or in the final image.
RUN --mount=type=secret,id=docs_env,target=/app/.env,required=true \
    DOCS_STRICT_GENERATION=1 python3 -u scripts/generate_table_docs.py \
    && python3 -u scripts/verify_examples.py --strict-live

FROM node:22-bookworm-slim AS builder

WORKDIR /app

# Vocs reads Git timestamps while generating its routes.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install the exact dependency versions recorded in the lockfile.
COPY package.json package-lock.json ./
RUN npm ci

# Build the site from the MDX generated in the preceding Python stage.
COPY --from=checker /app/docs ./docs
COPY scripts/verify_static_links.mjs ./scripts/verify_static_links.mjs
COPY tsconfig.json vocs.config.ts ./

RUN npm run build && npm run verify-links

# Artifact-only image: its filesystem contains just the generated static site.
FROM scratch AS static
COPY --from=builder /app/docs/dist /
