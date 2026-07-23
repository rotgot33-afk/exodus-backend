# Use lightweight Python image instead of Kali (faster build, smaller)
FROM python:3.11-slim

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Install system deps + SSH + minimal Kali-style tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client sshpass \
    curl wget git dnsutils \
    iproute2 iputils-ping traceroute \
    nmap netcat-openbsd \
    whois tcpdump \
    vim nano \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose port
EXPOSE $PORT

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# Start the server
CMD ["python3", "/app/main.py"]
