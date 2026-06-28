"""Run the AILO backend server. Usage: py -3.12 run.py"""
import sys
import io
import uvicorn

# Force UTF-8 stdout/stderr on Windows so print() never throws UnicodeEncodeError
# when video titles, queries, or tracebacks contain non-cp1252 characters.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
        log_level="info",
    )
