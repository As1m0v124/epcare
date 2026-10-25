#!/usr/bin/env python3
"""多线程分块下载器（v2：每块内部重试+续传，全部完成才合并）。

用法:
  python scripts/fast_download.py URL OUT_PATH --size BYTES [--conn 4] [--proxy ...]

- 每块写到 OUT_PATH.partN，块内失败自动重试10次（续传）；
- 所有块完整后才合并成 OUT_PATH 并删除分块；任何块不完整则不合并、保留分块供下次续传；
- --size 0 时尝试自动探测（HEAD）。
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests


def head_size(url, proxy):
    r = requests.head(url, allow_redirects=True, timeout=30,
                     proxies={"http": proxy, "https": proxy} if proxy else None)
    return int(r.headers.get("content-length", 0))


def chunk_download(url, path, start, end, idx, proxy):
    part = f"{path}.part{idx}"
    total = end - start + 1
    for attempt in range(10):
        pos = os.path.getsize(part) if os.path.exists(part) else 0
        if pos >= total:
            return True
        headers = {"Range": f"bytes={start + pos}-{end}"}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60,
                              proxies={"http": proxy, "https": proxy} if proxy else None) as r:
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                with open(part, "ab") as f:
                    for b in r.iter_content(1024 * 256):
                        f.write(b)
        except Exception as e:
            print(f"  [块{idx}] 第{attempt+1}次中断: {type(e).__name__}，已下 {os.path.getsize(part) if os.path.exists(part) else 0}/{total}")
            time.sleep(min(2 * (attempt + 1), 15))
    pos = os.path.getsize(part) if os.path.exists(part) else 0
    return pos >= total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--size", type=int, default=0)
    ap.add_argument("--conn", type=int, default=4)
    ap.add_argument("--proxy", default="")
    args = ap.parse_args()

    total = args.size or head_size(args.url, args.proxy)
    if total <= 0:
        sys.exit("无法确定文件大小，请用 --size 指定")
    print(f"{os.path.basename(args.out)}: {total/1e6:.1f} MB, {args.conn} 块")

    step = total // args.conn
    ranges = [(i * step, total - 1 if i == args.conn - 1 else (i + 1) * step - 1)
              for i in range(args.conn)]
    t0 = time.time()
    with ThreadPoolExecutor(args.conn) as pool:
        futs = [pool.submit(chunk_download, args.url, args.out, s, e, i, args.proxy)
                for i, (s, e) in enumerate(ranges)]
        ok = all(f.result() for f in futs)

    if not ok:
        sys.exit("❌ 有分块未完成，已保留 .part 文件，重跑同一命令可续传")

    with open(args.out, "wb") as out:
        for i in range(args.conn):
            part = f"{args.out}.part{i}"
            out.write(open(part, "rb").read())
            os.remove(part)
    sz = os.path.getsize(args.out)
    el = time.time() - t0
    print(f"完成: {sz/1e6:.1f} MB, {el:.0f}s ({sz/1e6/max(el,1):.2f} MB/s)")
    if sz != total:
        sys.exit(f"❌ 大小不符: {sz} != {total}")


if __name__ == "__main__":
    main()
