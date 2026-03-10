FROM python:3.11.9-slim

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Virtual environment path
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    # Playwright environment
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    # Test mode flag (will be overridden in test container)
    TEST_MODE=false

WORKDIR /app

# Install system dependencies (including Playwright dependencies)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    default-libmysqlclient-dev \
    default-mysql-client \
    pkg-config \
    # Additional useful tools
    vim \
    nano \
    # Playwright dependencies
    wget \
    gnupg \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    libxss1 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv

# Upgrade pip in venv
RUN /opt/venv/bin/python -m pip install --upgrade pip setuptools wheel

# Copy requirements first for better caching
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN /opt/venv/bin/playwright install chromium
RUN /opt/venv/bin/playwright install-deps

# Copy the app code (will be overridden by volume mount)
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Default command (for production)
CMD ["/opt/venv/bin/python", "-m", "streamlit", "run", "prof.py", "--server.port=8501", "--server.address=0.0.0.0"]
