ARG GO_IMAGE=golang:1.26.0-bookworm
ARG NODE_IMAGE=node:22.23.4-bookworm-slim
ARG RUNTIME_IMAGE=alpine:3.21.3
ARG MYSQL_IMAGE=mysql:8.4.7@sha256:0426ec38c7a10aa45ba383887df7878f74ee70e2fd589c7b69207f3577901903
ARG NGINX_IMAGE=nginx:1.27.5-alpine
FROM ${GO_IMAGE} AS backend-build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG APP_PACKAGE
ARG SOURCE_REVISION=uncommitted
RUN test -n "$APP_PACKAGE" && CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2 GOMEMLIMIT=512MiB go build -p=2 -trimpath -buildvcs=false -o /out/maas "$APP_PACKAGE"
RUN CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2 GOMEMLIMIT=512MiB go build -p=2 -trimpath -buildvcs=false -o /out/maas-probe ./deploy/probe
FROM ${NODE_IMAGE} AS web-build
WORKDIR /src/console
COPY console/package.json console/package-lock.json ./
RUN npm ci --fetch-retries=5 --fetch-retry-mintimeout=1000 --fetch-retry-maxtimeout=10000
COPY console/ ./
RUN NODE_OPTIONS=--max-old-space-size=512 npm run build
FROM ${RUNTIME_IMAGE} AS app
RUN apk add --no-cache ca-certificates
COPY --from=backend-build /out/maas /maas
COPY --from=backend-build /out/maas-probe /maas-probe
COPY docs/contracts/agent-runtime /app/docs/contracts/agent-runtime
COPY --from=web-build /src/console/dist /app/console
WORKDIR /app
ARG SOURCE_REVISION=uncommitted
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/maas"]
FROM ${NGINX_IMAGE} AS web
COPY deploy/release/nginx.conf /etc/nginx/nginx.conf
COPY --from=web-build /src/console/dist /usr/share/nginx/html
ARG SOURCE_REVISION=uncommitted
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx","-g","daemon off;"]
FROM ${MYSQL_IMAGE} AS installer-audit
USER 0:0
RUN microdnf install -y python3 && microdnf clean all
COPY config/mysql/ /app/sql/
COPY deploy/agent/session-role.sql /app/sql/agent-runtime-role.sql
COPY deploy/release/audit_runtime_privileges.py /app/audit_runtime_privileges.py
COPY deploy/release/migrate.sh /app/migrate.sh
COPY deploy/build-sources.lock.json /app/build-sources.lock.json
ARG SOURCE_REVISION=uncommitted
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}
FROM installer-audit AS migrate
COPY --from=backend-build /out/maas /maas
COPY docs/contracts/agent-runtime /app/docs/contracts/agent-runtime
WORKDIR /app
ARG SOURCE_REVISION=uncommitted
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}
USER 65532:65532
ENTRYPOINT ["bash","/app/migrate.sh"]
