# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
# Never prompt for Angular CLI telemetry in containers (it would block or opt in).
ENV NG_CLI_ANALYTICS=false CI=true
WORKDIR /web
COPY package.json package-lock.json .npmrc ./
RUN npm ci

FROM deps AS test
COPY . .
CMD ["npx", "ng", "test", "--watch=false"]

FROM deps AS build
COPY . .
RUN npx ng build --configuration production

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist/frontend/browser /usr/share/nginx/html
EXPOSE 80
