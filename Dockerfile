# ---- stage 1: fetch kubectl and verify its checksum ---------------------------------
FROM python:3.12-slim AS kubectl
# Matches the kind v0.33 node image (Kubernetes 1.37).
ARG KUBECTL_VERSION=v1.37.1
ARG TARGETARCH=amd64
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSLo /kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
 && curl -fsSLo /kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256" \
 && echo "$(cat /kubectl.sha256)  /kubectl" | sha256sum -c - \
 && chmod 0755 /kubectl

# ---- stage 2: runtime ---------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp
WORKDIR /app
COPY --from=kubectl /kubectl /usr/local/bin/kubectl
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY evals ./evals

# Non-root user; the pod also runs with a read-only root filesystem (HOME=/tmp is an emptyDir).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin agent
USER 10001
EXPOSE 8080
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
