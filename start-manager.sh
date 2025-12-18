#!/bin/bash
set -e

echo "🔄 Pulling latest code from GitHub..."
git pull origin main

echo "🚀 Starting manager bot..."
pm2 start bot.py --name manager