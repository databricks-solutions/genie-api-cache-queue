#!/bin/bash

cd frontend

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "ERROR: Node modules not found. Run ./setup.sh first."
    exit 1
fi

echo "Starting React frontend..."
npm run dev
