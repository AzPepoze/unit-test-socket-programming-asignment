FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
	iproute2 \
	iputils-ping \
	net-tools \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only scripts needed at build time
COPY scripts/network_setup.sh /app/scripts/
RUN mkdir -p /app/tmp /app/received /app/src
RUN chmod +x /app/scripts/network_setup.sh

# Source files will be mounted as volumes for live updates

ENV PYTHONUNBUFFERED=1
CMD ["python", "--version"]