#!/bin/bash
cd /Users/tahaseckin/Documents/borsa-analiz
exec .venv/bin/python -m automation.bot >> raporlar/bot.log 2>&1
