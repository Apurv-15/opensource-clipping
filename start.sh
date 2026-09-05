#!/usr/bin/env bash
set -e

# ANSI Color Codes
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
BOLD="\033[1m"
NC="\033[0m"

# Project Root Directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BOLD}${CYAN}====================================================${NC}"
echo -e "${BOLD}${CYAN}   🎬 OpenSource Clipping Studio — Setup & Run     ${NC}"
echo -e "${BOLD}${CYAN}====================================================${NC}"

# Ensure Homebrew path is on PATH (Apple Silicon & Intel macOS)
if [ -d "/opt/homebrew/bin" ]; then
    export PATH="/opt/homebrew/bin:$PATH"
elif [ -d "/usr/local/bin" ]; then
    export PATH="/usr/local/bin:$PATH"
fi

# 1. Verify FFmpeg & Aria2
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VER=$(ffmpeg -version 2>/dev/null | head -n 1 | awk '{print $3}')
    echo -e "${GREEN}[✓] FFmpeg installed:${NC} v${FFMPEG_VER}"
else
    echo -e "${YELLOW}[!] FFmpeg not found on PATH. Installing via Homebrew...${NC}"
    if command -v brew &> /dev/null; then
        brew install ffmpeg
    else
        echo -e "${YELLOW}[!] Warning: Homebrew not found. Please install ffmpeg manually.${NC}"
    fi
fi

if command -v aria2c &> /dev/null; then
    echo -e "${GREEN}[✓] Aria2 accelerator installed:${NC} $(aria2c --version | head -n 1 | awk '{print $3}')"
else
    echo -e "${YELLOW}[!] Aria2 not found. Installing via Homebrew for 5x download acceleration...${NC}"
    if command -v brew &> /dev/null; then
        brew install aria2
    fi
fi

# 2. Check & Initialize .env
if [ ! -f ".env" ]; then
    echo -e "${BLUE}[+] Creating .env from template...${NC}"
    cp .env.sample .env
fi

# 3. Check & Initialize Python Virtual Environment
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/python3" ]; then
    echo -e "${BLUE}[+] Creating Python virtual environment in .venv ...${NC}"
    python3 -m venv .venv
    echo -e "${BLUE}[+] Installing Python dependencies...${NC}"
    .venv/bin/pip install --upgrade pip --quiet
    .venv/bin/pip install -r requirements.txt --quiet
else
    echo -e "${GREEN}[✓] Python virtual environment ready:${NC} $(.venv/bin/python3 --version 2>&1)"
fi

# 4. Check & Initialize Frontend Node.js Dependencies
if [ ! -d "web/dashboard/node_modules" ]; then
    echo -e "${BLUE}[+] web/dashboard/node_modules missing. Installing npm packages...${NC}"
    npm --prefix web/dashboard install
else
    echo -e "${GREEN}[✓] Dashboard frontend dependencies ready${NC}"
fi

# 5. Ensure Working Directories Exist
mkdir -p outputs uploads custom_fonts assets/bgm assets/images

# Check if running in direct CLI mode
if [ "$1" == "--cli" ]; then
    shift
    echo -e "${BOLD}${GREEN}====================================================${NC}"
    echo -e "${BOLD}${GREEN}  🚀 Running OpenSource Clipping CLI Pipeline       ${NC}"
    echo -e "${BOLD}${GREEN}====================================================${NC}\n"
    exec .venv/bin/python main.py "$@"
fi

# 6. Clean up Stale Ports (Port 8000 for FastAPI & 5173 for Vite Dashboard)
for PORT in 8000 5173; do
    PIDS=$(lsof -t -i:$PORT 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo -e "${YELLOW}[+] Freeing port $PORT (terminating PID: $PIDS)...${NC}"
        kill -9 $PIDS 2>/dev/null || true
    fi
done

# 7. Trap Clean Exit
cleanup() {
    echo -e "\n${YELLOW}[!] Stopping all OpenSource Clipping services...${NC}"
    if [ -n "$BACKEND_PID" ]; then kill -TERM "$BACKEND_PID" 2>/dev/null || true; fi
    if [ -n "$FRONTEND_PID" ]; then kill -TERM "$FRONTEND_PID" 2>/dev/null || true; fi
    exit 0
}
trap cleanup SIGINT SIGTERM

# 8. Start Backend Service (FastAPI)
echo -e "${BLUE}[+] Launching FastAPI Backend on http://127.0.0.1:8000 ...${NC}"
.venv/bin/uvicorn web.api.app:app --host 127.0.0.1 --port 8000 --reload > outputs/backend.log 2>&1 &
BACKEND_PID=$!

# 9. Start Frontend Dashboard (Vite)
echo -e "${BLUE}[+] Launching Web Studio Dashboard on http://127.0.0.1:5173 ...${NC}"
npm --prefix web/dashboard run dev -- --host 127.0.0.1 --port 5173 > /dev/null 2>&1 &
FRONTEND_PID=$!

sleep 1.5

echo -e "\n${BOLD}${GREEN}====================================================${NC}"
echo -e "${BOLD}${GREEN}  🚀 Web Studio:  http://127.0.0.1:5173             ${NC}"
echo -e "${BOLD}${GREEN}  📡 API Docs:    http://127.0.0.1:8000/docs        ${NC}"
echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "${CYAN}Tip: To run CLI directly, use:${NC} ./start.sh --cli --url <YOUTUBE_URL>"
echo -e "${CYAN}Press Ctrl+C to stop all services anytime.${NC}\n"

# Wait for background processes
wait $BACKEND_PID $FRONTEND_PID
