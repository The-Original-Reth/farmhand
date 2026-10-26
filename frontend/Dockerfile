FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .

# Left unset by default on purpose: the app detects the right API host at
# runtime from whatever the browser used to load the page (see api.js) —
# baking in "localhost" here breaks the moment this is viewed from a
# different machine than the one running Docker. Only pass this build arg
# to override with something other than ":4545" on the same host.
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3636
