# Garmin Biometric Service - Setup Guide

This guide provides comprehensive instructions for setting up and running the Garmin Biometric Service. This service fetches data from the Garmin Connect API, stores it in TimescaleDB, calculates analytics metrics, and visualizes the results using Streamlit.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Installation Options](#installation-options)
  - [Docker Installation (Recommended)](#docker-installation-recommended)
  - [Local Installation](#local-installation)
- [Configuration](#configuration)
- [Running the Services](#running-the-services)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

## Prerequisites

To use this service, you'll need:

- A Garmin Connect account (email and password)
- Git to clone the repository
- Docker Desktop (for Docker installation) or Python 3.9+ (for local installation)

## Installation Options

The service can be set up in two ways:

### Docker Installation (Recommended)

Docker provides the easiest setup experience as it handles all dependencies and configurations automatically.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/timchankins/treat-garmin-service.git
   cd treat-garmin-service
   ```

2. **Run the setup script with your Garmin credentials**:
   ```bash
   source ./setup.zsh --garmin-email="$GARMIN_EMAIL" --garmin-password="$GARMIN_PASSWORD"
   ```

   This script will:
   - Create required configuration files
   - Set up Docker containers for:
     - TimescaleDB
     - PostgreSQL
     - Biometric Data Service
     - Analytics Service
     - Streamlit Dashboard
   - Start all services

3. **Access the dashboard**:
   Once setup is complete, visit http://localhost:8501 in your browser to see the Streamlit dashboard.

### Local Installation

If you prefer not to use Docker, you can install the services directly on your machine.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/timchankins/treat-garmin-service.git
   cd treat-garmin-service
   ```

2. **Run the setup script with the local flag "--no-docker" **:
   ```bash
   source ./setup.zsh --no-docker --garmin-email="$GARMIN_EMAIL" --garmin-password="$GARMIN_PASSWORD"
   ```

   This script will:
   - Create a Python virtual environment
   - Install required dependencies
   - Install and configure TimescaleDB and PostgreSQL
   - Set up necessary database tables

3. **Run the services** (in separate terminal windows):
   ```bash
   # Terminal 1
   python biometric_data_service.py
   
   # Terminal 2
   python biometric_data_analytics.py
   
   # Terminal 3
   streamlit run dashboard.py
   ```

4. **Access the dashboard**:
   Visit http://localhost:8501 in your browser.

## Configuration

All configuration is managed through the `.env` file. The setup script creates this file with default values, but you can modify it to suit your needs:

```
# Garmin Connect credentials
GARMIN_EMAIL=your@email.com
GARMIN_PASSWORD=your_password

# Database configuration
TIMESCALE_DB_NAME=biometric_data
TIMESCALE_DB_USER=postgres
TIMESCALE_DB_PASSWORD=postgres
TIMESCALE_DB_HOST=timescaledb  # Use 'localhost' for local installation
TIMESCALE_DB_PORT=5432

POSTGRES_DB_NAME=analytics_data
POSTGRES_DB_USER=postgres
POSTGRES_DB_PASSWORD=postgres
POSTGRES_DB_HOST=postgres  # Use 'localhost' for local installation
POSTGRES_DB_PORT=5432

# Fetch settings
FETCH_INTERVAL_HOURS=1
DAYS_TO_FETCH=7
ANALYTICS_PROCESSING_INTERVAL=300

# For Docker deployment
COMPOSE_PROJECT_NAME=garmin-biometric-service
```

Key settings to consider changing:
- `FETCH_INTERVAL_HOURS`: How often to fetch new data (default: 1 hour)
- `DAYS_TO_FETCH`: How many days of historical data to fetch (default: 7 days)
- `ANALYTICS_PROCESSING_INTERVAL`: How often to recalculate analytics (default: 300 seconds)

## Running the Services

### Docker Mode

In Docker mode, all services start automatically after running the setup script. You can manage them with Docker Compose commands:

```bash
# Stop all services
docker-compose down

# Start all services
docker-compose up -d

# Restart a specific service
docker-compose restart biometric_data_service
```

### Local Mode

In local mode, you need to start each service manually in separate terminal windows:

```bash
# Terminal 1
source garmin-env/bin/activate
python biometric_data_service.py

# Terminal 2
source garmin-env/bin/activate
python biometric_data_analytics.py

# Terminal 3
source garmin-env/bin/activate
streamlit run dashboard.py
```

## Monitoring

The `monitor.sh` script provides a comprehensive monitoring solution using tmux. This allows you to monitor all services in a single terminal window with multiple panes.

To use it:

1. Make the script executable:
   ```bash
   chmod +x monitor.sh
   ```

2. Run the script:
   ```bash
   ./monitor.sh
   ```

3. Navigate between windows:
   - `Ctrl+b` then a number key (0-5) to switch windows
   - `Ctrl+b` then `d` to detach (the session keeps running)
   - `tmux attach -t garmin-monitor` to reattach later

## Troubleshooting

For detailed troubleshooting information, see the [TROUBLESHOOTING.md](TROUBLESHOOTING.md) document.

### Using Mock Data

If you're having issues with the Garmin API returning empty data, or just want to test the system without connecting to Garmin:

```bash
# Start the mock data generator service
docker-compose up -d mockdata
```

This will populate your database with realistic mock biometric data for the past 30 days.

### Common Issues

#### Port 8501 Already in Use

If Streamlit fails to start because port 8501 is in use:

```bash
# Find the process using port 8501
lsof -i :8501

# Kill the process
kill -9 <PID>

# Restart the services
docker-compose down
docker-compose up -d
```

#### Docker Containers Not Starting

If containers fail to start:

```bash
# Check container status
docker ps -a

# View container logs
docker-compose logs -f <service_name>

# Common fix: remove old containers and volumes
docker-compose down -v
docker-compose up -d
```

#### Database Connection Issues

If the services can't connect to the databases:

```bash
# Check database container logs
docker-compose logs -f timescaledb
docker-compose logs -f postgres

# Verify database is accepting connections
docker exec -it garmin-biometric-service-timescaledb-1 psql -U postgres -c "SELECT 'Connection test';"
```

#### Garmin API Data Issues

If the Garmin API authenticates but returns no data:

1. Check if your Garmin Connect account has data for the requested timeframe
2. Verify that your Garmin device is properly syncing with Garmin Connect
3. Look for warnings in the logs:
   ```bash
   docker-compose logs -f biometric_data_service | grep "returned no data"
   ```
4. Use the mock data generator to test the rest of the pipeline:
   ```bash
   docker-compose up -d mockdata
   ```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more details.

#### Garmin API Connectivity

If the Garmin API is connecting but not retrieving data, try rebuilding the services with the updated dependencies:

```bash
# Rebuild the biometric data service with updated dependencies
docker-compose build biometric_data_service

# Restart the service
docker-compose restart biometric_data_service

# Check logs to confirm it's working properly
docker-compose logs -f biometric_data_service
```

You can also run the test script to verify Garmin API connectivity:

```bash
python test_garmin_api.py
```

