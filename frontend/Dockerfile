# Oja Connect frontend: Vite build, then nginx serving the static bundle.
#
# Vite inlines VITE_* values into the JS bundle AT BUILD TIME, so they must
# arrive here as build args (docker compose wires them from the repo-root
# .env). Only public values belong here: the Monnify API key and contract
# code are the same ones the checkout popup exposes to every browser anyway.
# The Monnify secret key must never appear in this file or this image.

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Empty VITE_API_BASE_URL means "same origin": the nginx stage below proxies
# /v1, /api and /webhooks to the backend service, so the browser never needs
# to know a second host. Set it to http://localhost:8000 to talk to the
# backend directly instead (the local dev default).
ARG VITE_API_BASE_URL=""
ARG VITE_MONNIFY_API_KEY=""
ARG VITE_MONNIFY_CONTRACT_CODE=""
# Native live voice is compiled in only when this is "1"; empty keeps the
# browser Web Speech floor. It must be present at build time for Vite to inline.
ARG VITE_VOICE_NATIVE=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_MONNIFY_API_KEY=$VITE_MONNIFY_API_KEY \
    VITE_MONNIFY_CONTRACT_CODE=$VITE_MONNIFY_CONTRACT_CODE \
    VITE_VOICE_NATIVE=$VITE_VOICE_NATIVE

RUN npm run build

FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 5173
