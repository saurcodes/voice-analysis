FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# nginx.conf.template is rendered to /etc/nginx/conf.d/default.conf by docker-entrypoint.sh
# (envsubst on ${KEYCLOAK_URL}, used only inside the CSP header) rather than copied straight
# to conf.d: the Keycloak host is a container env var, not a Vite build-time value, so one
# built image can be redeployed against any Keycloak instance.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
EXPOSE 80
ENTRYPOINT ["/docker-entrypoint.sh"]
