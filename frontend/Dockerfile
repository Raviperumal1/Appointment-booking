FROM nginx:alpine

# Copy custom Nginx configuration
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Copy static frontend files to Nginx web root
COPY frontend /usr/share/nginx/html

EXPOSE 80
