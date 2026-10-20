#!/usr/bin/env python3
"""EP 真机连接测试（ep_selfcheck.py 的第一步：连接 + 读基本信息）

用法（在 ~/ep-project 目录下）:

  路由器组网（推荐：手机热点当路由器，Mac 全程有网）:
    ep38/bin/python conn_test.py sta --ssid 手机热点名 --password 热点密码
    流程: 生成二维码 → 中控拨路由器档位开机 → 按连接按键 → 机器人相机扫屏幕上的码

  Wi-Fi 直连（此模式 Mac 会断网）:
    先让 Mac 连上 RMEP-XXXXXX（初始密码 12341234），再跑:
    ep38/bin/python conn_test.py ap
"""
import argparse
import subprocess
import sys
import time

from robomaster import robot


def read_battery(ep, wait=1.5):
    """EP 的电量是订阅推送式接口，订阅 1Hz 等 1.5 秒拿到一个值"""
    result = {}

    def on_battery(percent):
        result["pct"] = percent

    ep.battery.sub_battery_info(freq=1, callback=on_battery)
    time.sleep(wait)
    ep.battery.unsub_battery_info()
    return result.get("pct")


def sta_qrcode(ssid, password):
    from robomaster.conn import ConnectionHelper
    from MyQR import myqr

    helper = ConnectionHelper()
    payload = helper.build_qrcode_string(ssid=ssid, password=password)
    png = "ep_sta_qrcode.png"
    myqr.run(words=payload, level="H", save_name=png)
    subprocess.run(["open", png])
    print("二维码已生成并在「预览」中打开: %s（放大铺满屏幕，亮度调高）" % png)
    print("接下来:")
    print("  1. 中控拨到【路由器模式】档位，开机")
    print("  2. 按一下中控上的【连接按键】")
    print("  3. 机器人相机对准屏幕二维码（20-30cm），等提示音")
    print("等待机器人入网（最长 6 分钟，Ctrl+C 取消）...")
    ok = helper.wait_for_connection()
    if not ok:
        sys.exit("❌ 机器人一直没入网。检查: 热点频段（扫不上就切 2.4GHz/最大兼容性）、SSID/密码、是否先按了连接键再扫码")
    print("✅ 机器人已加入 Wi-Fi")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["ap", "sta"], nargs="?", default="ap")
    parser.add_argument("--ssid", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--skip-qrcode", action="store_true",
                        help="机器人已在当前 Wi-Fi 内（之前扫过码），直接连接")
    args = parser.parse_args()

    if args.mode == "sta" and not args.skip_qrcode:
        if not args.ssid:
            sys.exit("用法: ep38/bin/python conn_test.py sta --ssid 手机热点名 --password 热点密码\n"
                     "机器人已入网时: ep38/bin/python conn_test.py sta --skip-qrcode")
        sta_qrcode(args.ssid, args.password)

    print("正在连接机器人（conn_type=%s）..." % args.mode)
    ep = robot.Robot()
    try:
        ep.initialize(conn_type=args.mode)
        print("✅ 机器人连接成功")
        print("   固件版本:", ep.get_version())
        print("   机器人 SN:", ep.get_sn())
        print("   电量: %s %%" % read_battery(ep))
        print("\n连接测试通过，这三个值记进 docs/ep_repair.md")
        print("下一步: 确认周围安全后，再把底盘/机械臂/机械爪自检逐项加进 ep_selfcheck.py")
    except Exception as e:
        print("❌ 连接失败: %r" % e)
        print("排查清单:")
        print("  1. 中控模式开关: 直连测=【直连档】，组网测=【路由器档】")
        print("  2. Mac 的 Wi-Fi: 直连=连 RMEP-XXXXXX（12341234）；组网=和机器人同一个热点")
        print("  3. 中控天线竖直；机器人和 Mac 距离 1-2 米内")
        print("  4. 直连密码忘了: 长按连接按键 5 秒重置")
        raise
    finally:
        ep.close()


if __name__ == "__main__":
    main()
