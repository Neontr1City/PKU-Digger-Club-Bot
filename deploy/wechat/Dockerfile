FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl fonts-noto-cjk fonts-noto-color-emoji \
    xvfb openbox x11vnc novnc websockify xdotool xclip x11-utils \
    dbus-x11 at-spi2-core python3-pyatspi \
    libnss3 libgbm1 libasound2t64 libxss1 libatomic1 libxdamage1 \
    libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-xkb1 libxcb-cursor0 libgtk-3-0t64 \
    libatk-bridge2.0-0t64 libcups2t64 libxcomposite1 libxrandr2 \
    libxfixes3 libxtst6 libxshmfence1 libdrm2 \
    && rm -rf /var/lib/apt/lists/*

# Fixed to the official package fetched on 2026-09-28; fail if the URL changes.
ARG WECHAT_SHA256=b7d0f8d53e9f648bc2c77a6096a04100d008f2d9f0d3988a2a4859b5992aca0a
RUN curl --fail --location --retry 2 \
      https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb \
      -o /tmp/wechat.deb \
    && echo "$WECHAT_SHA256  /tmp/wechat.deb" | sha256sum -c - \
    && dpkg -i /tmp/wechat.deb \
    && rm /tmp/wechat.deb

# Dynamically loaded graphics/audio libraries; ldd alone does not detect these.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libegl1 libegl-mesa0 libpulse0 \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-pil scrot tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
COPY sender.py /usr/local/bin/wechat-sender.py

RUN useradd --uid 10001 --create-home --home-dir /home/wechat wechat
COPY session.sh /usr/local/bin/wechat-session
RUN chmod 755 /usr/local/bin/wechat-session
USER 10001:10001
ENV HOME=/home/wechat DISPLAY=:99 LANG=C.UTF-8 \
    XDG_RUNTIME_DIR=/tmp/runtime-wechat QT_ACCESSIBILITY=1 \
    QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 LIBGL_ALWAYS_SOFTWARE=1
ENTRYPOINT ["dbus-run-session", "--", "/usr/local/bin/wechat-session"]
