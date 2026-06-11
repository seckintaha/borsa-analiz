#!/bin/bash
cd /Users/tahaseckin/Documents/borsa-analiz
exec .venv/bin/streamlit run app/panel.py --server.headless true >> raporlar/streamlit.log 2>&1
