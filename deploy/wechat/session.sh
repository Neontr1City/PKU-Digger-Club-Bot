#!/usr/bin/env bash
set -euo pipefail
umask 077
ulimit -c 0
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.local/share"
chmod 700 "$XDG_RUNTIME_DIR"
printf '%s' "$DBUS_SESSION_BUS_ADDRESS" > "$XDG_RUNTIME_DIR/session-bus"
children=()
cleanup() {
    trap - EXIT TERM INT
    if ((${#children[@]})); then
        kill "${children[@]}" 2>/dev/null || true
        # A display process can ignore TERM after its X server disappears.
        # Bound cleanup so a dead client never leaves a seemingly live container.
        for attempt in {1..30}; do
            alive=0
            for pid in "${children[@]}"; do
                if kill -0 "$pid" 2>/dev/null; then alive=1; fi
            done
            if ((alive == 0)); then break; fi
            sleep 0.1
        done
        kill -KILL "${children[@]}" 2>/dev/null || true
        wait "${children[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT TERM INT
Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp -ac &
children+=("$!")
for attempt in {1..50}; do
    if xdpyinfo >/dev/null 2>&1; then break; fi
    sleep 0.1
done
xdpyinfo >/dev/null
openbox >/tmp/openbox.log 2>&1 &
children+=("$!")
# No public ports: the only external path must pass the site's admin auth.
x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -forever -shared \
    -nopw -noxdamage -quiet >/tmp/x11vnc.log 2>&1 &
children+=("$!")
websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
children+=("$!")
if [[ "${WECHAT_DEBUG:-0}" == 1 ]]; then
    # Optional diagnostic image only; logs stay private and contain no core dump.
    gdb --batch --return-child-result \
        -ex 'set pagination off' -ex 'set debuginfod enabled off' \
        -ex 'set disable-randomization off' \
        -ex 'set print frame-arguments none' -ex 'set print entry-values no' \
        -ex 'handle SIGPIPE nostop noprint pass' \
        -ex run -ex 'bt 16' --args /usr/bin/wechat >/tmp/wechat-debug.log 2>&1 &
else
    /usr/bin/wechat >/tmp/wechat.log 2>&1 &
fi
children+=("$!")
if [[ -f "$HOME/bot-outbox/config.json" ]]; then
    OMP_THREAD_LIMIT=1 python3 /usr/local/bin/wechat-sender.py >/tmp/bot-sender.log 2>&1 &
    children+=("$!")
fi
status=0
wait -n -p finished_pid "${children[@]}" || status=$?
printf 'Desktop process %s exited with status %s; stopping session.\n' \
    "${finished_pid:-unknown}" "$status" >&2
for metric in pids.current pids.peak pids.events memory.events; do
    if [[ -r "/sys/fs/cgroup/$metric" ]]; then
        printf '%s: ' "$metric" >&2
        cat "/sys/fs/cgroup/$metric" >&2
    fi
done
exit "$status"
