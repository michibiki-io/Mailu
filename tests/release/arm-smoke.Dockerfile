FROM ghcr.io/mailu/alpine:3.20.7
ARG TARGETARCH
RUN case "$TARGETARCH:$(uname -m)" in \
      arm64:aarch64) ;; \
      *) echo "Unexpected build architecture: $TARGETARCH:$(uname -m)" >&2; exit 1 ;; \
    esac
