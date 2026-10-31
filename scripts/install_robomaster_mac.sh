#!/usr/bin/env bash
# 在 Apple Silicon Mac 上安装官方 RoboMaster SDK（Python 3.8）
#
# 背景：DJI 只发布 Linux/Windows wheel；包内唯一的编译模块 libmedia_codec 是
# Linux x86_64 视频解码器（闭源）。本脚本安装其纯 Python 部分（底盘/机械臂/
# 机械爪/云台/灯光控制），并打三个补丁：
#   1. media.py: libmedia_codec / cv2 的 import 加容错
#   2. media.py: 解码器改为按需创建，start_video/audio_stream 无解码器时明确报错
#      （否则 initialize 阶段创建相机模块就会崩，连机器人控制都不可用）
#   3. conn.py:  连接类型比较 is 改 ==（SDK bug：命令行传入的 'sta' 与
#      内部常量不是同一对象，request_connection 三个分支全部落空）
# 限制：官方 SDK 的 camera.start_video_stream 在 macOS 不可用（解码器闭源）。
# 真机连接（2026-10-20 验证通过）：sta 组网，固件 01.01.1150。
# 用法：bash scripts/install_robomaster_mac.sh [venv路径]   # 默认 ./ep38
set -euo pipefail

VENV="${1:-ep38}"
PY="$VENV/bin/python"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -x "$PY" ] || { echo "错误：找不到 $PY，先 uv venv --python 3.8 $VENV"; exit 1; }

echo "==> 下载 robomaster 0.1.1.68 cp38 manylinux wheel"
URL=$(python3 -c "import urllib.request,json; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/robomaster/json')); print([f['url'] for f in d['urls'] if 'cp38-cp38-manylinux' in f['filename']][0])")
curl -sL -o "$WORK/rm.whl" "$URL"

echo "==> 解包并打补丁"
unzip -q "$WORK/rm.whl" -d "$WORK/x"
python3 - "$WORK/x" <<'EOF'
import sys, os

def patch(path, reps):
    s = open(path).read()
    for old, new in reps:
        assert old in s, '未找到: %r' % old[:60]
        s = s.replace(old, new, 1)
    open(path, 'w').write(s)
    print('  已补丁:', os.path.basename(path))

base = sys.argv[1]
patch(os.path.join(base, 'robomaster', 'media.py'), [
    ("import libmedia_codec\n",
     "try:\n    import libmedia_codec\nexcept (ImportError, OSError):\n"
     "    libmedia_codec = None  # macOS 无此 Linux 专用视频解码器\n"),
    ("import cv2\n",
     "try:\n    import cv2\nexcept ImportError:\n"
     "    cv2 = None  # 仅视频显示用，可缺\n"),
    ("        self._video_decoder = libmedia_codec.H264Decoder()\n",
     "        self._video_decoder = libmedia_codec.H264Decoder() if libmedia_codec else None\n"),
    ("        self._audio_decoder = libmedia_codec.OpusDecoder()\n",
     "        self._audio_decoder = libmedia_codec.OpusDecoder() if libmedia_codec else None\n"),
    ('    def start_video_stream(self, display=True, addr=None, ip_proto="tcp"):\n        try:\n',
     '    def start_video_stream(self, display=True, addr=None, ip_proto="tcp"):\n'
     '        if self._video_decoder is None:\n'
     '            logger.error("LiveView: libmedia_codec 不可用（macOS），SDK 视频流不可用")\n'
     '            return False\n'
     '        try:\n'),
    ('    def start_audio_stream(self, addr=None, ip_proto="tcp"):\n        try:\n',
     '    def start_audio_stream(self, addr=None, ip_proto="tcp"):\n'
     '        if self._audio_decoder is None:\n'
     '            logger.error("LiveView: libmedia_codec 不可用（macOS），音频流不可用")\n'
     '            return False\n'
     '        try:\n'),
])
patch(os.path.join(base, 'robomaster', 'robotic_arm.py'), [
    ("        self._pos_x, self._pos_y = struct.unpack('<II', buf[1:])",
     "        self._pos_x, self._pos_y = struct.unpack('<ii', buf[1:])  # 有符号解码：y 可为负"),
])
patch(os.path.join(base, 'robomaster', 'conn.py'), [
    ("if conn_type is CONNECTION_WIFI_AP:", "if conn_type == CONNECTION_WIFI_AP:"),
    ("elif conn_type is CONNECTION_WIFI_STA:", "elif conn_type == CONNECTION_WIFI_STA:"),
    ("elif conn_type is CONNECTION_USB_RNDIS:", "elif conn_type == CONNECTION_USB_RNDIS:"),
])
EOF

echo "==> 安装到 $VENV"
SP="$($PY -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
cp -R "$WORK/x/robomaster" "$WORK/x/multi_robomaster" "$WORK/x/robomaster-0.1.1.68.dist-info" "$SP/"

echo "==> 安装依赖（netifaces 需源码编译，约几分钟）"
uv pip install --python "$PY" "numpy>=1.18" "netaddr>=0.8" "netifaces>=0.10" "myqr>=2.3"

echo "==> 验证"
"$PY" -c "from robomaster import robot, chassis, robotic_arm, gripper, led, gimbal; robot.Robot(); print('✅ robomaster SDK 安装成功')"
