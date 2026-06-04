#!/bin/bash
# 等待 Xvfb 显示服务就绪后再启动 fluxbox
# 解决 depends_on 只检查进程状态、不检查 socket 就绪的竞态问题

DISPLAY_NUM="${1:-99}"
SOCKET="/tmp/.X11-unix/X${DISPLAY_NUM}"
MAX_WAIT=15

for i in $(seq 1 $MAX_WAIT); do
    if [ -S "$SOCKET" ]; then
        exec /usr/bin/fluxbox
    fi
    sleep 1
done

echo "[start_fluxbox] ERROR: Xvfb socket $SOCKET not ready after ${MAX_WAIT}s" >&2
exit 1
