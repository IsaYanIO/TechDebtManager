FROM python:3.12-slim-bookworm

ARG SONAR_SCANNER_VERSION=6.2.1.4610

ENV PYTHONUNBUFFERED=1 \
    SONAR_SCANNER_HOME=/opt/sonar-scanner \
    PATH=/opt/sonar-scanner/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        nodejs \
        openjdk-17-jre-headless \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/sonar-scanner.zip \
        "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux-x64.zip" \
    && unzip -q /tmp/sonar-scanner.zip -d /opt \
    && mv "/opt/sonar-scanner-${SONAR_SCANNER_VERSION}-linux-x64" "$SONAR_SCANNER_HOME" \
    && rm /tmp/sonar-scanner.zip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY api.py .

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
