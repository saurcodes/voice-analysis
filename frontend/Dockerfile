# Build-time Keycloak settings are baked into the static bundle: Vite inlines import.meta.env.* at
# build time, there is no runtime config step for a plain nginx image. Override at build with
# --build-arg or via the compose VITE_* variables; changing them after the image is built needs a rebuild.
FROM node:22-alpine AS build
ARG VITE_KEYCLOAK_URL=http://localhost:8080
ARG VITE_KEYCLOAK_REALM=vocal-coach
ARG VITE_KEYCLOAK_CLIENT_ID=vocal-coach-web
ENV VITE_KEYCLOAK_URL=${VITE_KEYCLOAK_URL} \
    VITE_KEYCLOAK_REALM=${VITE_KEYCLOAK_REALM} \
    VITE_KEYCLOAK_CLIENT_ID=${VITE_KEYCLOAK_CLIENT_ID}
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
