FROM debian:buster-slim

WORKDIR /
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
  && apt-get install -y python3-certbot python3-certbot-dns-google python3-certbot-dns-route53 curl python3 python3-requests \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

EXPOSE 80

WORKDIR /certbot
COPY run_cert.py /certbot/run_cert.py

ENTRYPOINT ["python3","/certbot/run_cert.py","service"]
