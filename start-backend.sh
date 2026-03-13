#!/bin/bash

cd backend

# Check if venv exists
if [ ! -d "../.venv" ]; then
    echo "ERROR: Virtual environment not found. Run: python -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found. Please copy .env.example to .env and configure it."
    exit 1
fi

echo "Starting FastAPI backend..."
source ../.venv/bin/activate

# Create data directory if it doesn't exist
mkdir -p data

# Run from backend directory so Python can find the app module
python -m app.main
