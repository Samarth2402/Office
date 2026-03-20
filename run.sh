#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt
echo "Starting iSoftrend Business Management System..."
python3 app.py
