"""接口压测基线。

为什么需要：README 里写着「128 并发 QPS 257、P50 483ms」这类数字，
但如果没有能复跑的脚本，这些数字对读者（和半年后的自己）就只是传说。
连接池调参的效果尤其需要可复现——池容量与等待超时改了之后，
到底是变好还是只是当时那台机器手气好，只能靠同一个脚本再跑一遍来判断。

这个脚本刻意只做一件事：对**一个只读接口**发固定并发的请求，
报告吞吐、延迟分位和状态码分布，并把影响结果的环境变量一起打印出来。
不做渐进加压、不做混合场景——那些会让数字更好看，但也更难复现。

用法：
    # 先起服务（另一个终端）
    uvicorn main:app --port 8000

    python scripts/bench_api.py                          # 默认 128 并发 × 每并发 10 次
    python scripts/bench_api.py --concurrency 400        # 超出池容量，看降级是否为 503
    python scripts/bench_api.py --path /health           # 换接口
    python scripts/bench_api.py --json results.json      # 存结果供对比

读数说明：
- QPS 用总请求数 / 墙钟耗时，包含失败请求。失败也占用了服务端资源，
  把它们排除掉会高估容量。
- 分位数用 statistics.quantiles，对**所有**完成的请求算，不区分成败。
  同时单列成功请求的分位，因为快速失败的 503 会把整体分位拉好看。
- 503 单独统计：过载返回 503 + Retry-After 是预期行为，不是错误。
  把它和 5xx 混在一起会看不出降级是否按设计生效。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx


def _percentile(values: list[float], pct: float) -> float:
    """第 pct 百分位（毫秒）。样本不足时退回最大值，不假装有分位。"""
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = min(int(len(ordered) * pct / 100), len(ordered) - 1)
    return ordered[idx]


async def _one(client: httpx.AsyncClient, path: str, sem: asyncio.Semaphore,
               results: list[tuple[int, float]]) -> None:
    async with sem:
        started = time.perf_counter()
        try:
            resp = await client.get(path)
            status = resp.status_code
        except Exception:  # noqa: BLE001 — 连不上/超时也算一次失败样本
            status = 0
        results.append((status, (time.perf_counter() - started) * 1000))


async def run(base_url: str, path: str, concurrency: int, per_worker: int,
              timeout: float) -> dict:
    total = concurrency * per_worker
    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[int, float]] = []

    limits = httpx.Limits(max_connections=concurrency,
                          max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, limits=limits,
                                 timeout=timeout) as client:
        wall_start = time.perf_counter()
        await asyncio.gather(*[
            _one(client, path, sem, results) for _ in range(total)
        ])
        wall = time.perf_counter() - wall_start

    statuses = Counter(s for s, _ in results)
    all_lat = [ms for _, ms in results]
    ok_lat = [ms for s, ms in results if 200 <= s < 300]

    return {
        "target": f"{base_url}{path}",
        "concurrency": concurrency,
        "requests": total,
        "wall_seconds": round(wall, 3),
        "qps": round(total / wall, 1) if wall > 0 else None,
        "status_counts": dict(sorted(statuses.items())),
        "success": sum(c for s, c in statuses.items() if 200 <= s < 300),
        "overloaded_503": statuses.get(503, 0),
        "errors": sum(c for s, c in statuses.items() if s == 0 or s >= 500 and s != 503),
        "latency_ms_all": {
            "p50": round(_percentile(all_lat, 50), 1),
            "p95": round(_percentile(all_lat, 95), 1),
            "p99": round(_percentile(all_lat, 99), 1),
            "max": round(max(all_lat), 1) if all_lat else None,
        },
        "latency_ms_success_only": {
            "p50": round(_percentile(ok_lat, 50), 1),
            "p95": round(_percentile(ok_lat, 95), 1),
            "mean": round(statistics.fmean(ok_lat), 1) if ok_lat else None,
        } if ok_lat else None,
    }


def _environment() -> dict:
    """把会影响结果的配置一起记下来。换台机器跑出别的数字是正常的，
    但至少要能看出是哪些条件不同。

    注意：连接池这几项读的是**本进程**的环境变量，不是服务端的。
    脚本是通过 HTTP 打进去的，拿不到对端的配置。所以只有在
    「服务端用同一份 .env 启动」时这几个值才代表被压的那个服务——
    打印出来是为了让读数字的人能核对这个前提，不是断言服务端就是这样。
    """
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "client_env_db_pool_size": os.getenv("DB_POOL_SIZE", "20（database.py 默认）"),
        "client_env_db_max_overflow": os.getenv("DB_MAX_OVERFLOW", "30（database.py 默认）"),
        "client_env_db_pool_timeout": os.getenv("DB_POOL_TIMEOUT", "5（database.py 默认）"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--path", default="/jobs?limit=20")
    ap.add_argument("--concurrency", type=int, default=128)
    ap.add_argument("--per-worker", type=int, default=10,
                    help="每个并发槽发多少次，总请求 = concurrency × per-worker")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--json", dest="json_out", help="把结果写到这个文件")
    args = ap.parse_args()

    env = _environment()
    print(f"目标      {args.base_url}{args.path}")
    print(f"并发      {args.concurrency}（总请求 {args.concurrency * args.per_worker}）")
    print(f"连接池    size={env['client_env_db_pool_size']} "
          f"overflow={env['client_env_db_max_overflow']} "
          f"timeout={env['client_env_db_pool_timeout']}"
          "（本机环境变量，需与服务端启动时一致才作数）")
    print(f"环境      Python {env['python']} · {env['cpu_count']} CPU · {env['platform']}")
    print("-" * 64)

    result = asyncio.run(run(args.base_url, args.path, args.concurrency,
                             args.per_worker, args.timeout))
    result["environment"] = env
    result["measured_at"] = time.strftime("%Y-%m-%d %H:%M:%S%z")

    print(f"耗时      {result['wall_seconds']}s")
    print(f"QPS       {result['qps']}（含失败请求）")
    print(f"状态码    {result['status_counts']}")
    print(f"成功      {result['success']} / {result['requests']}")
    if result["overloaded_503"]:
        print(f"过载 503  {result['overloaded_503']}（预期的降级，不计入错误）")
    if result["errors"]:
        print(f"错误      {result['errors']}（连接失败或 5xx）")
    lat = result["latency_ms_all"]
    print(f"延迟(全部) P50 {lat['p50']}ms · P95 {lat['p95']}ms · "
          f"P99 {lat['p99']}ms · max {lat['max']}ms")
    if result["latency_ms_success_only"]:
        ok = result["latency_ms_success_only"]
        print(f"延迟(成功) P50 {ok['p50']}ms · P95 {ok['p95']}ms · 均值 {ok['mean']}ms")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json_out}")


if __name__ == "__main__":
    main()
