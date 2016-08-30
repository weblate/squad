FROM debian:stretch
RUN apt-get update && \
  apt-get install -qy auto-apt-proxy && \
  apt-get install -qy \
    python3-django \
    fonts-font-awesome \
    libjs-angularjs \
    libjs-bootstrap \
    gunicorn3

WORKDIR /app
COPY . ./

# debug
RUN find
RUN env

# creates symlinks to packaged static assets
RUN python3 -m squad.frontend


USER www-data
CMD sh -c "./manage.py migrate && exec gunicorn3 squad.wsgi --bind 0.0.0.0:${PORT:-8000} --log-file -"
