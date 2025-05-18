#!/bin/zsh

# Detect if script is sourced
# $ZSH_EVAL_CONTEXT contains `file` when sourced
if [[ "$ZSH_EVAL_CONTEXT" != *file* ]]; then
  echo "❌ Please run this script with: source ./setup.zsh [--garmin-email=EMAIL] [--garmin-password=PASSWORD]"
  return 1
fi

# Define colors for prettier output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Detect OS
OS_TYPE="macos"  # Default to macOS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  OS_TYPE="linux"
fi

# Parse command line arguments
USE_DOCKER=true
GARMIN_EMAIL_ARG=""
GARMIN_PASSWORD_ARG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-docker)
      USE_DOCKER=false
      shift
      ;;
    --linux)
      OS_TYPE="linux"
      shift
      ;;
    --macos)
      OS_TYPE="macos"
      shift
      ;;
    --garmin-email=*)
      GARMIN_EMAIL_ARG="${1#*=}"
      shift
      ;;
    --garmin-password=*)
      GARMIN_PASSWORD_ARG="${1#*=}"
      shift
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo -e "${YELLOW}Usage: source ./setup.zsh [--no-docker] [--linux|--macos] [--garmin-email=EMAIL] [--garmin-password=PASSWORD]${NC}"
      return 1
      ;;
  esac
done

echo -e "${BLUE}📁 Switching to project directory...${NC}"
# Get the directory where this script is located
SCRIPT_DIR=$(cd "$(dirname "${(%):-%x}")" && pwd)
cd "$SCRIPT_DIR" || return 1

# Check for existing environment variables
if [ -f ".env" ]; then
  # Load existing environment variables silently
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip comments and empty lines
    if [[ ! "$line" =~ ^\s*# && -n "$line" ]]; then
      # Export the variable
      export "$line"
    fi
  done < .env
fi

# Override with command line arguments if provided
if [ -n "$GARMIN_EMAIL_ARG" ]; then
  GARMIN_EMAIL="$GARMIN_EMAIL_ARG"
fi

if [ -n "$GARMIN_PASSWORD_ARG" ]; then
  GARMIN_PASSWORD="$GARMIN_PASSWORD_ARG"
fi

# Check if Garmin credentials are provided
if [ -z "$GARMIN_EMAIL" ] || [ -z "$GARMIN_PASSWORD" ] || [ "$GARMIN_EMAIL" = "your_email@example.com" ] || [ "$GARMIN_PASSWORD" = "your_password" ]; then
  echo -e "${RED}❌ Garmin credentials are required!${NC}"
  echo -e "${YELLOW}Please provide your Garmin credentials using:${NC}"
  echo -e "${YELLOW}source ./setup.zsh --garmin-email=your@email.com --garmin-password=your_password${NC}"
  echo -e "${YELLOW}Or edit the .env file directly and run the script again.${NC}"
  return 1
fi

# Create or update .env file with all required variables
echo -e "${BLUE}📝 Creating/updating .env file...${NC}"
cat > .env << EOL
# Garmin Connect credentials
GARMIN_EMAIL=${GARMIN_EMAIL}
GARMIN_PASSWORD=${GARMIN_PASSWORD}

# Database configuration
TIMESCALE_DB_NAME=biometric_data
TIMESCALE_DB_USER=postgres
TIMESCALE_DB_PASSWORD=postgres
TIMESCALE_DB_HOST=timescaledb
TIMESCALE_DB_PORT=5432

POSTGRES_DB_NAME=analytics_data
POSTGRES_DB_USER=postgres
POSTGRES_DB_PASSWORD=postgres
POSTGRES_DB_HOST=postgres
POSTGRES_DB_PORT=5432

# Fetch settings
FETCH_INTERVAL_HOURS=1
DAYS_TO_FETCH=7
ANALYTICS_PROCESSING_INTERVAL=300

# For Docker deployment
COMPOSE_PROJECT_NAME=garmin-biometric-service
EOL

echo -e "${GREEN}🔐 Environment variables configured${NC}"

# Generate requirements.txt file
if [ ! -f "requirements.txt" ]; then
  echo -e "${BLUE}📝 Generating requirements.txt...${NC}"
  cat > requirements.txt << EOL
garminconnect==0.1.55
python-dotenv==1.0.0
psycopg2-binary==2.9.9
schedule==1.2.1
pandas==2.1.4
numpy==1.26.3
streamlit==1.32.0
plotly==5.18.0
sqlalchemy==2.0.27
scipy==1.12.0
EOL
fi

if [ "$USE_DOCKER" = true ]; then
  # Setup with Docker
  echo -e "${BLUE}🐳 Setting up with Docker...${NC}"
  
  # Check if Docker is installed
  if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}⚠️  Docker not found. Please install Docker Desktop:${NC}"
    
    if [ "$OS_TYPE" = "macos" ]; then
      echo -e "${YELLOW}Visit: https://www.docker.com/products/docker-desktop${NC}"
      echo -e "${YELLOW}After installing Docker Desktop, run this script again.${NC}"
    else
      echo -e "${YELLOW}For Ubuntu/Debian:${NC}"
      echo -e "${YELLOW}sudo apt-get update${NC}"
      echo -e "${YELLOW}sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin${NC}"
      echo -e "${YELLOW}sudo usermod -aG docker $USER${NC}"
      echo -e "${YELLOW}After installing, log out and back in, then run this script again.${NC}"
    fi
    
    # Create a flag file so we know docker was needed
    touch .docker_install_needed
    return 1
  fi
  
  # Check if docker-compose is installed
  if ! command -v docker-compose &> /dev/null; then
    if ! docker compose version &> /dev/null; then
      echo -e "${YELLOW}⚠️  Docker Compose not found. Please install Docker Compose:${NC}"
      
      if [ "$OS_TYPE" = "macos" ]; then
        echo -e "${YELLOW}Docker Compose should be included with Docker Desktop.${NC}"
        echo -e "${YELLOW}Please make sure Docker Desktop is properly installed.${NC}"
      else
        echo -e "${YELLOW}For Ubuntu/Debian:${NC}"
        echo -e "${YELLOW}sudo apt-get update${NC}"
        echo -e "${YELLOW}sudo apt-get install docker-compose-plugin${NC}"
      fi
      
      return 1
    else
      echo -e "${GREEN}✅ Docker Compose V2 found${NC}"
      DOCKER_COMPOSE_CMD="docker compose"
    fi
  else
    echo -e "${GREEN}✅ Docker Compose V1 found${NC}"
    DOCKER_COMPOSE_CMD="docker-compose"
  fi
  
  # Generate Dockerfile for the biometric data service
  if [ ! -f "Dockerfile.biometric" ]; then
    echo -e "${BLUE}📝 Creating Dockerfile for Biometric Service...${NC}"
    cat > Dockerfile.biometric << EOL
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY biometric_data_service.py .
COPY .env .
COPY wait-for-db.sh .
RUN chmod +x wait-for-db.sh

CMD ["./wait-for-db.sh", "timescaledb", "5432", "python", "biometric_data_service.py"]
EOL
  fi
  
  # Generate Dockerfile for the analytics service
  if [ ! -f "Dockerfile.analytics" ]; then
    echo -e "${BLUE}📝 Creating Dockerfile for Analytics Service...${NC}"
    cat > Dockerfile.analytics << EOL
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY biometric_data_analytics.py .
COPY .env .
COPY wait-for-db.sh .
RUN chmod +x wait-for-db.sh

CMD ["./wait-for-db.sh", "postgres", "5432", "python", "biometric_data_analytics.py"]
EOL
  fi
  
  # Generate Dockerfile for Streamlit dashboard
  if [ ! -f "Dockerfile.streamlit" ]; then
    echo -e "${BLUE}📝 Creating Dockerfile for Streamlit Dashboard...${NC}"
    cat > Dockerfile.streamlit << EOL
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard.py .
COPY .env .
COPY wait-for-db.sh .
RUN chmod +x wait-for-db.sh

EXPOSE 8501

CMD ["./wait-for-db.sh", "timescaledb", "5432", "streamlit", "run", "dashboard.py", "--server.address=0.0.0.0"]
EOL
  fi
  
  # Generate wait-for-db.sh script
  if [ ! -f "wait-for-db.sh" ]; then
    echo -e "${BLUE}📝 Creating database wait script...${NC}"
    cat > wait-for-db.sh << EOL
#!/bin/bash

# wait-for-db.sh
# Script to wait for database availability before starting a service

set -e

host="\$1"
port="\$2"
shift 2
cmd="\$@"

echo "Waiting for database at \$host:\$port to be ready..."

# Loop until we can connect to the database
until PGPASSWORD=\$POSTGRES_DB_PASSWORD psql -h "\$host" -U "\$POSTGRES_DB_USER" -p "\$port" -d "\$POSTGRES_DB_NAME" -c '\q'; do
  >&2 echo "Postgres is unavailable - sleeping for 1 second"
  sleep 1
done

>&2 echo "Postgres is up - executing command: \$cmd"
exec \$cmd
EOL
  fi
  
  # Generate docker-compose.yml
  if [ ! -f "docker-compose.yml" ]; then
    echo -e "${BLUE}📝 Creating docker-compose.yml...${NC}"
    cat > docker-compose.yml << EOL
version: '3.8'

services:
  timescaledb:
    image: timescale/timescaledb:latest-pg14
    environment:
      - POSTGRES_USER=\${TIMESCALE_DB_USER}
      - POSTGRES_PASSWORD=\${TIMESCALE_DB_PASSWORD}
      - POSTGRES_DB=\${TIMESCALE_DB_NAME}
    ports:
      - "\${TIMESCALE_DB_PORT}:5432"
    volumes:
      - timescale_data:/var/lib/postgresql/data
      - ./init-timescaledb.sql:/docker-entrypoint-initdb.d/init-timescaledb.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  postgres:
    image: postgres:14
    environment:
      - POSTGRES_USER=\${POSTGRES_DB_USER}
      - POSTGRES_PASSWORD=\${POSTGRES_DB_PASSWORD}
      - POSTGRES_DB=\${POSTGRES_DB_NAME}
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-postgres.sql:/docker-entrypoint-initdb.d/init-postgres.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  biometric_data_service:
    build:
      context: .
      dockerfile: Dockerfile.biometric
    environment:
      - TIMESCALE_DB_HOST=timescaledb
      - POSTGRES_DB_HOST=postgres
      - POSTGRES_DB_PORT=5432
      - GARMIN_EMAIL=\${GARMIN_EMAIL}
      - GARMIN_PASSWORD=\${GARMIN_PASSWORD}
      - FETCH_INTERVAL_HOURS=\${FETCH_INTERVAL_HOURS}
      - DAYS_TO_FETCH=\${DAYS_TO_FETCH}
    depends_on:
      timescaledb:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

  analytics_service:
    build:
      context: .
      dockerfile: Dockerfile.analytics
    environment:
      - TIMESCALE_DB_HOST=timescaledb
      - POSTGRES_DB_HOST=postgres
      - POSTGRES_DB_PORT=5432
      - ANALYTICS_PROCESSING_INTERVAL=\${ANALYTICS_PROCESSING_INTERVAL}
    depends_on:
      timescaledb:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

  streamlit:
    build:
      context: .
      dockerfile: Dockerfile.streamlit
    ports:
      - "8501:8501"
    environment:
      - TIMESCALE_DB_HOST=timescaledb
      - POSTGRES_DB_HOST=postgres
      - TIMESCALE_DB_PORT=\${TIMESCALE_DB_PORT}
      - POSTGRES_DB_PORT=5432
    depends_on:
      - timescaledb
      - postgres
      - biometric_data_service
      - analytics_service
    restart: unless-stopped

volumes:
  timescale_data:
  postgres_data:
EOL
  fi
  
  # Create init script for TimescaleDB
  if [ ! -f "init-timescaledb.sql" ]; then
    echo -e "${BLUE}📝 Creating initialization script for TimescaleDB...${NC}"
    cat > init-timescaledb.sql << EOL
-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create biometric_data table
CREATE TABLE IF NOT EXISTS biometric_data (
    id SERIAL,
    user_id INTEGER NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    data_type VARCHAR(50) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    value JSONB,
    raw_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, timestamp),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Create TimescaleDB hypertable
SELECT create_hypertable('biometric_data', 'timestamp', if_not_exists => TRUE);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_biometric_user_type_time 
ON biometric_data (user_id, data_type, timestamp DESC);
EOL
  fi
  
  # Create init script for PostgreSQL
  if [ ! -f "init-postgres.sql" ]; then
    echo -e "${BLUE}📝 Creating initialization script for PostgreSQL...${NC}"
    cat > init-postgres.sql << EOL
-- Analytics jobs queue
CREATE TABLE IF NOT EXISTS analytics_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- User analytics table
CREATE TABLE IF NOT EXISTS user_analytics (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    analytics_type VARCHAR(50) NOT NULL,
    time_range VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    metrics JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, analytics_type, time_range, start_date, end_date)
);

-- Analytics metrics metadata
CREATE TABLE IF NOT EXISTS analytics_metrics_metadata (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    unit VARCHAR(20),
    data_type VARCHAR(20) NOT NULL,
    visualization_type VARCHAR(20) DEFAULT 'line',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (metric_name)
);

-- Insert some initial metadata
INSERT INTO analytics_metrics_metadata 
(metric_name, display_name, description, unit, data_type, visualization_type)
VALUES 
('avg_steps', 'Average Steps', 'Average daily steps', 'steps', 'integer', 'line'),
('avg_heart_rate', 'Average Heart Rate', 'Average daily heart rate', 'bpm', 'float', 'line'),
('avg_stress', 'Average Stress Level', 'Average daily stress level', 'score', 'float', 'line'),
('avg_hrv', 'Average Heart Rate Variability', 'Average daily HRV', 'ms', 'float', 'line'),
('avg_rhr', 'Average Resting Heart Rate', 'Average resting heart rate', 'bpm', 'float', 'line'),
('avg_sleep_duration', 'Average Sleep Duration', 'Average sleep duration', 'hours', 'float', 'bar'),
('avg_body_battery', 'Average Body Battery', 'Average body battery level', 'score', 'float', 'line'),
('avg_spo2', 'Average Blood Oxygen', 'Average blood oxygen level', '%', 'float', 'line'),
('total_active_time', 'Total Active Time', 'Total active time', 'minutes', 'integer', 'bar'),
('recovery_score', 'Recovery Score', 'Calculated recovery score', 'score', 'float', 'gauge'),
('training_load', 'Training Load', 'Calculated training load', 'score', 'float', 'line'),
('fitness_trend', 'Fitness Trend', 'Fitness level trend', 'score', 'float', 'line')
ON CONFLICT (metric_name) DO NOTHING;
EOL
  fi
  
  # Check for running containers from our project and stop them if found
  echo -e "${BLUE}🔍 Checking for existing containers...${NC}"
  if ${DOCKER_COMPOSE_CMD} ps -q 2>/dev/null | grep -q .; then
    echo -e "${YELLOW}⚠️  Existing ${COMPOSE_PROJECT_NAME} containers found. Stopping them...${NC}"
    ${DOCKER_COMPOSE_CMD} down
    # Wait a moment for ports to be released
    sleep 3
  fi
  
  # Double-check if port 8501 is still in use by something else
  if lsof -i :8501 &>/dev/null; then
    echo -e "${YELLOW}⚠️  Port 8501 is still in use by another application!${NC}"
    echo -e "${YELLOW}This could be another instance of Streamlit or a different application.${NC}"
    echo -e "${BLUE}Would you like to force stop the process using port 8501? (y/n)${NC}"
    read -r force_stop
    
    if [[ "$force_stop" == "y" || "$force_stop" == "Y" ]]; then
      # Get PID of process using port 8501
      PORT_PID=$(lsof -ti:8501)
      if [[ -n "$PORT_PID" ]]; then
        echo -e "${BLUE}Stopping process with PID ${PORT_PID}...${NC}"
        kill -9 $PORT_PID
        sleep 2
      fi
    else
      echo -e "${RED}Setup aborted. Please free port 8501 and try again.${NC}"
      return 1
    fi
  fi
  
  # Start containers
  echo -e "${BLUE}Starting containers...${NC}"
  ${DOCKER_COMPOSE_CMD} up -d

  # Check if all containers are running
  sleep 5
  if ! docker ps --format '{{.Names}}' | grep -q 'streamlit'; then
    echo -e "${RED}❌ Streamlit container failed to start!${NC}"
    echo -e "${YELLOW}Checking logs for errors...${NC}"
    ${DOCKER_COMPOSE_CMD} logs streamlit
    echo -e "${RED}Setup failed. Please fix the errors above and try again.${NC}"
    return 1
  fi
  
  # Verify all services are healthy
  if ! docker ps --format '{{.Status}}' | grep -q 'healthy'; then
    echo -e "${YELLOW}⚠️  Waiting for services to become healthy...${NC}"
    for i in {1..30}; do
      sleep 2
      if docker ps --format '{{.Status}}' | grep -q 'healthy'; then
        break
      fi
      if [ $i -eq 30 ]; then
        echo -e "${RED}❌ Services did not reach healthy state in time.${NC}"
        echo -e "${YELLOW}Checking container logs...${NC}"
        ${DOCKER_COMPOSE_CMD} logs
        echo -e "${RED}Setup failed. Please check the logs above and try again.${NC}"
        return 1
      fi
    done
  fi
  
  echo -e "${GREEN}✅ Services started! Access the dashboard at: http://localhost:8501${NC}"
  echo -e "${BLUE}ℹ️  To check logs: ${DOCKER_COMPOSE_CMD} logs -f${NC}"
  echo -e "${BLUE}ℹ️  To stop services: ${DOCKER_COMPOSE_CMD} down${NC}"

else
  # Non-Docker setup (local installation)
  echo -e "${BLUE}🖥️  Setting up locally (without Docker)...${NC}"
  
  # Set up venv
  if [ ! -d "garmin-env" ]; then
    echo -e "${BLUE}🐍 Creating Python virtual environment...${NC}"
    python3 -m venv garmin-env || return 1
  fi
  
  # Activate venv
  source garmin-env/bin/activate
  echo -e "${GREEN}✅ Virtual environment activated: (garmin-env)${NC}"
  
  # Install dependencies
  if [ ! -f "requirements_installed.flag" ]; then
    echo -e "${BLUE}📦 Installing dependencies...${NC}"
    pip install --upgrade pip
    pip install -r requirements.txt
    touch requirements_installed.flag
  else
    echo -e "${GREEN}📦 Dependencies already installed${NC}"
  fi
  
  # Install and setup databases
  if [ "$OS_TYPE" = "macos" ]; then
    # macOS installation using Homebrew
    if ! command -v brew &> /dev/null; then
      echo -e "${YELLOW}⚠️  Homebrew not found. Please install Homebrew:${NC}"
      echo -e "${YELLOW}/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"${NC}"
      return 1
    fi
    
    # Install PostgreSQL
    if ! command -v postgres &> /dev/null; then
      echo -e "${BLUE}📦 Installing PostgreSQL...${NC}"
      brew install postgresql@14
      brew services start postgresql@14
    else
      echo -e "${GREEN}✅ PostgreSQL already installed${NC}"
    fi
    
    # Install TimescaleDB
    if ! brew list timescaledb &> /dev/null; then
      echo -e "${BLUE}📦 Installing TimescaleDB...${NC}"
      brew install timescaledb
      
      # Get PostgreSQL config file path
      PG_CONFIG_FILE=$(brew --prefix)/var/postgres/postgresql.conf
      
      # Check if TimescaleDB is already in config
      if ! grep -q "shared_preload_libraries = 'timescaledb'" "$PG_CONFIG_FILE"; then
        echo -e "${BLUE}🔧 Configuring TimescaleDB...${NC}"
        timescaledb-tune --quiet --yes --conf-path="$PG_CONFIG_FILE"
        brew services restart postgresql@14
      fi
    else
      echo -e "${GREEN}✅ TimescaleDB already installed${NC}"
    fi
    
  else
    # Linux installation
    echo -e "${BLUE}📦 Checking PostgreSQL and TimescaleDB...${NC}"
    
    if ! command -v psql &> /dev/null; then
      echo -e "${YELLOW}⚠️  PostgreSQL not found. Please install PostgreSQL and TimescaleDB:${NC}"
      echo -e "${YELLOW}For Ubuntu/Debian:${NC}"
      echo -e "${YELLOW}sudo apt-get update${NC}"
      echo -e "${YELLOW}sudo apt-get install -y postgresql postgresql-contrib${NC}"
      echo -e "${YELLOW}# Add TimescaleDB repository${NC}"
      echo -e "${YELLOW}sudo sh -c 'echo \"deb https://packagecloud.io/timescale/timescaledb/ubuntu/ \$(lsb_release -c -s) main\" > /etc/apt/sources.list.d/timescaledb.list'${NC}"
      echo -e "${YELLOW}wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | sudo apt-key add -${NC}"
      echo -e "${YELLOW}sudo apt-get update${NC}"
      echo -e "${YELLOW}sudo apt-get install -y timescaledb-2-postgresql-14${NC}"
      echo -e "${YELLOW}sudo timescaledb-tune --quiet --yes${NC}"
      echo -e "${YELLOW}sudo systemctl restart postgresql${NC}"
      return 1
    else
      echo -e "${GREEN}✅ PostgreSQL is installed${NC}"
      
      # Check for TimescaleDB
      if ! psql -U postgres -c "SELECT 'TimescaleDB is installed';" &> /dev/null; then
        echo -e "${YELLOW}⚠️  Cannot connect to PostgreSQL. Please ensure PostgreSQL is running:${NC}"
        echo -e "${YELLOW}sudo systemctl start postgresql${NC}"
        return 1
      fi
      
      if ! psql -U postgres -c "SELECT 'TimescaleDB is installed' FROM pg_extension WHERE extname = 'timescaledb';" | grep -q "TimescaleDB is installed"; then
        echo -e "${YELLOW}⚠️  TimescaleDB extension not found. Please install it:${NC}"
        echo -e "${YELLOW}sudo apt-get install -y timescaledb-2-postgresql-14${NC}"
        echo -e "${YELLOW}sudo timescaledb-tune --quiet --yes${NC}"
        echo -e "${YELLOW}sudo systemctl restart postgresql${NC}"
        return 1
      else
        echo -e "${GREEN}✅ TimescaleDB is installed${NC}"
      fi
    fi
  fi
  
  # Create databases and setup tables
  echo -e "${BLUE}🗃️  Setting up databases...${NC}"
  
  # Create biometric_data database
  if ! psql -U postgres -lqt | cut -d '|' -f1 | grep -qw biometric_data; then
    echo -e "${BLUE}Creating biometric_data database...${NC}"
    createdb -U postgres biometric_data
    
    # Apply TimescaleDB schema
    psql -U postgres -d biometric_data -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
    psql -U postgres -d biometric_data -f init-timescaledb.sql
  else
    echo -e "${GREEN}✅ biometric_data database already exists${NC}"
  fi
  
  # Create analytics_data database
  if ! psql -U postgres -lqt | cut -d '|' -f1 | grep -qw analytics_data; then
    echo -e "${BLUE}Creating analytics_data database...${NC}"
    createdb -U postgres analytics_data
    
    # Apply schema
    psql -U postgres -d analytics_data -f init-postgres.sql
  else
    echo -e "${GREEN}✅ analytics_data database already exists${NC}"
  fi
  
  echo -e "${GREEN}✅ Databases setup complete!${NC}"
  echo -e "${BLUE}🚀 Ready! You can now run:${NC}"
  echo -e "${BLUE}python biometric_data_service.py # In one terminal${NC}"
  echo -e "${BLUE}python biometric_data_analytics.py # In another terminal${NC}"
  echo -e "${BLUE}streamlit run dashboard.py # In a third terminal${NC}"
fi

echo -e "${GREEN}🎉 Setup completed successfully!${NC}"
