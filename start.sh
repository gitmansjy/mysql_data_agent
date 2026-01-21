#!/usr/bin/env bash
set -e

# 默认端口，可由平台通过 $PORT 覆盖
: "${PORT:=8501}"

# 运行 Streamlit 应用
streamlit run streamlit_chat.py --server.port $PORT --server.address 0.0.0.0
