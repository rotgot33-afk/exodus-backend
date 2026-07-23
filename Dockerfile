# Use Kali Linux base image
FROM kalilinux/kali-rolling:latest

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Install minimal Kali tools + Python + SSH + system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    nmap sqlmap nikto whois dnsutils netcat-openbsd \
    curl wget git \
    openssh-client sshpass \
    iproute2 iputils-ping traceroute \
    tcpdump hydra john \
    vim nano \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Install EXODUS framework from GitHub
RUN git clone --depth 1 https://github.com/exodialabsxyz/exodus.git /tmp/exodus && \
    cd /tmp/exodus && \
    pip3 install --no-cache-dir --break-system-packages -e . && \
    rm -rf /tmp/exodus

# Copy app code
COPY . .

# Create non-root user for terminal (with sudo for kali tools)
RUN useradd -m -s /bin/bash agent && \
    apt-get update && apt-get install -y --no-install-recommends sudo && \
    echo "agent ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    rm -rf /var/lib/apt/lists/*

# Create /sec directory (mimics Segfault persistent storage)
RUN mkdir -p /sec && chmod 777 /sec

USER agent
WORKDIR /home/agent

# Expose port
EXPOSE $PORT

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# Start the server
CMD ["python3", "/app/main.py"]
