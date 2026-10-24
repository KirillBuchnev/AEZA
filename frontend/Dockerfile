FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

FROM nginx:1.30.5-alpine
RUN sed -i \
    -e '/^user[[:space:]]*nginx;/d' \
    -e 's#pid .*nginx.pid;#pid /tmp/nginx.pid;#' \
    -e 's#worker_processes auto;#worker_processes 2;#' \
    /etc/nginx/nginx.conf \
    && rm -rf /etc/nginx/templates
ENV NGINX_ENVSUBST_TEMPLATE_DIR=/etc/nginx/templates-disabled
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-limits.conf /etc/nginx/conf.d/00-limits.conf
COPY snippets/ /etc/nginx/snippets/
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
