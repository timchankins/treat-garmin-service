#!/bin/bash
# Run the mock data generator service

# Print header
echo "==================================================="
echo "Garmin Biometric Service - Mock Data Generator"
echo "==================================================="
echo
echo "This script will generate mock biometric data to test the system."
echo "It's useful when the Garmin API is returning empty data or for development testing."
echo

# Check if docker-compose exists
if command -v docker-compose &> /dev/null; then
    # Docker mode
    echo "Running mock data generator service via Docker..."
    docker-compose up -d mockdata
    echo
    echo "Waiting for mock data generation to complete..."
    docker-compose logs -f mockdata
else
    # Local mode
    echo "Running mock data generator directly..."
    if [ -f "generate_mock_data.py" ]; then
        python generate_mock_data.py
    else
        echo "Error: generate_mock_data.py not found!"
        exit 1
    fi
fi

echo
echo "==================================================="
echo "Mock data generation complete!"
echo "You can now check the dashboard at http://localhost:8501"
echo "==================================================="