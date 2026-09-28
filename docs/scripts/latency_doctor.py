#!/usr/bin/env python3
"""newapi 耗时定位一键诊断脚本 — 配套 docs/LATENCY_DIAGNOSIS_GUIDE.md

自动执行手册 §3~§7 的方法：DNS/链路判定 → 分段计时 → 直连源站对照 → SSE 节奏分析 → 分段判定，
定位"响应慢"发生在 接入层(CDN/WAF) / 中转站 / 上游渠道 哪一段。

路径定义（本脚本所有输出均按此标注）:
  路径A（经接入链路）: 按 DNS 正常解析连接（域名 → CNAME → CDN/WAF → 中转站），
                      即用户真实访问路径。每个实验默认都跑路径A。
  路径B（直连源站）  : 用 curl --resolve <域名>:<端口>:<--origin-ip> 在本地覆盖 DNS，
                      TCP 直连 --origin-ip（SNI/Host 仍为原域名，证书校验不受影响）。
                      仅在提供 --origin-ip 时测试，无 --origin-ip 时不存在路径B。
                      ⚠ 注意: --resolve 只改变客户端的连接目标，不改变目标机器上的服务。
                      若该 IP 上的服务入口仍是 CDN/网关组件（如 UCDN 回源接入层），
                      路径B 测到的是该组件而非源站本身。验证方法: curl -v 看
                      "Connected to ... (IP)" 确认连接目标；看响应头是否仍有 CDN 特征
                      （Server/via 含 cdn 字样、CDN 风格错误页）。

链路判定为动态获取: 每次运行实时解析 DNS 还原 CNAME 链（socket.gethostbyname_ex），
提供 --origin-ip 时进一步比对"解析 IP 是否等于源站 IP"来确认中间层是否存在，
不依赖任何写死的域名或 IP。

用法:
  python3 latency_doctor.py --base-url https://api.example.com --key sk-xxx --model gpt-4o-mini
  # 启用接入层对照（推荐，源站 IP 在 CDN 控制台可见）:
  python3 latency_doctor.py ... --origin-ip 1.2.3.4

依赖: python3 (>=3.8) 与 curl。
"""

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

CURL_TIME_FMT = "%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}"

# 判定阈值（依据手册 §5/§6 与实战案例基线）
ACCESS_CONTRIB_WARN = 0.2   # 接入层贡献 >200ms 记为引入延迟
RELAY_APP_WARN = 0.15       # 中转站应用处理 >150ms 记为异常
UPSTREAM_TTFT_WARN = 2.0    # 上游首 token >2s 偏慢
UPSTREAM_TTFT_BAD = 5.0     # >5s 严重
GEN_GAP_WARN = 0.5          # 流式 chunk 间隔 >0.5s 视为卡顿


def warn(msg):
    print(f"\033[33m{msg}\033[0m", file=sys.stderr)


class Sample:
    def __init__(self, code, dns, tcp, tls, ttfb, total):
        self.code, self.dns, self.tcp, self.tls, self.ttfb, self.total = (
            int(code), float(dns), float(tcp), float(tls), float(ttfb), float(total))


class CurlError(Exception):
    pass


def dns_chain(host):
    """解析 DNS 并还原 CNAME 链。返回 (链路字符串, 是否存在中间别名, IP 列表)。"""
    try:
        canonical, aliases, ips = socket.gethostbyname_ex(host)
    except OSError as e:
        warn(f"DNS 解析失败: {e}")
        return host, False, []
    hops = [host] + [a for a in aliases if a != host]
    if canonical and canonical != host and canonical not in hops:
        hops.append(canonical)
    ip_str = ""
    if ips:
        ip_str = ", ".join(ips[:3]) + (f" 等{len(ips)}个IP" if len(ips) > 3 else "")
        hops.append(ip_str)
    has_cname = len(hops) > (2 if ips else 1)
    return " → ".join(hops), has_cname, ips


def curl_timing(url, key, body=None, timeout=30, resolve=None):
    """执行一次请求，返回 (Sample, body_text)。Sample 含分段计时。"""
    fd, path = tempfile.mkstemp(prefix="latency_doctor_")
    os.close(fd)
    try:
        args = ["curl", "-sS", "--max-time", str(timeout), "-w", CURL_TIME_FMT,
                "-H", f"Authorization: Bearer {key}"]
        if resolve:
            args += ["--resolve", resolve]
        if body is not None:
            args += ["-H", "Content-Type: application/json", "-d", body]
        args += ["-o", path, url]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise CurlError(f"curl 失败: {proc.stderr.strip()}")
        parts = proc.stdout.split()
        if len(parts) != 6:
            raise CurlError(f"curl 输出异常: {proc.stdout!r}")
        with open(path, "rb") as f:
            body_text = f.read(65536).decode("utf-8", "replace")
        return Sample(*parts), body_text
    finally:
        os.unlink(path)


def curl_stream(url, key, body, timeout=60, resolve=None):
    """流式请求，逐行记录 SSE chunk 到达时间。

    返回 (events, raw_tail)：events 为 [(相对秒, "data:...")]（不含 [DONE]）；
    无 events 时 raw_tail 携带原始输出前 300 字符用于排错。
    """
    args = ["curl", "-sS", "-N", "--max-time", str(timeout),
            "-H", f"Authorization: Bearer {key}",
            "-H", "Content-Type: application/json", "-d", body]
    if resolve:
        args += ["--resolve", resolve]
    args += [url]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    events, raw = [], []
    t0 = time.time()
    try:
        for line in proc.stdout:
            line = line.strip()
            raw.append(line)
            if line.startswith("data:") and "[DONE]" not in line:
                events.append((time.time() - t0, line))
    finally:
        proc.wait(timeout=10)
    err = "" if events else "\n".join(raw)[:300]
    return events, err


def med(xs):
    return statistics.median(xs) if xs else float("nan")


def med_ok(results, attr):
    """仅统计 http 200 样本的中位数（504 等网关错误不代表正常服务耗时）。"""
    return med([getattr(s, attr) for s, _ in results if s.code == 200])


def fetch_models(base, key, timeout, resolve=None):
    """拉取并返回排序后的模型列表；失败直接退出。"""
    s, body = curl_timing(base + "/v1/models", key, resolve=resolve, timeout=timeout)
    if s.code != 200:
        sys.exit(f"/v1/models 返回 http {s.code}，请检查 key 或网络。响应: {body[:200]}")
    try:
        return sorted(m["id"] for m in json.loads(body).get("data", []))
    except Exception:
        sys.exit(f"无法解析 /v1/models 响应: {body[:200]}")


def pick_model(base, key, model, resolve, timeout):
    """校验模型可用，模型不存在时列出可选并确认。返回模型列表。"""
    names = fetch_models(base, key, timeout, resolve)
    if model not in names:
        head = ", ".join(names[:15]) if names else "(空)"
        warn(f"模型 {model!r} 不在可用列表（共 {len(names)} 个）。前若干个: {head}")
        try:
            if input("仍继续测试? [y/N] ").strip().lower() != "y":
                sys.exit(1)
        except EOFError:
            sys.exit(1)
    return names


def fmt_stream_stats(d):
    """流式摘要字符串：首 chunk / chunk 数 / 速率 / gap 中位。"""
    span = d["last"] - d["first"]
    rate = d["n"] / span if span > 0 else float("nan")
    gap_med = med(d["gaps"]) if d["gaps"] else float("nan")
    return f"首 chunk {d['first']:.2f}s | {d['n']} chunks | ~{rate:.1f} chunks/s | gap 中位 {gap_med:.2f}s"


def stream_probe(url, key, sbody, timeout, resolve, tag):
    """跑一次流式探测并打印单行摘要，返回统计 dict 或 None。"""
    events, err = curl_stream(url, key, sbody, timeout=timeout, resolve=resolve)
    if err:
        warn(f"  流式失败或无数据[{tag}]: {err}")
        return None
    if not events:
        warn(f"  流式无输出[{tag}]")
        return None
    gaps = [round(b - a, 3) for (a, _), (b, _) in zip(events, events[1:])]
    d = {"first": events[0][0], "last": events[-1][0], "n": len(events), "gaps": gaps}
    print(f"  chunks={d['n']} 首chunk={d['first']:.2f}s 末chunk={d['last']:.2f}s")
    return d


def run_set(label, times, fn, tag):
    """跑一组采样并打印单行结果，返回样本列表 [(Sample, body)]。tag 为路径标识 A/B。"""
    results = []
    for i in range(1, times + 1):
        try:
            s, body = fn()
        except CurlError as e:
            warn(f"  {label} run{i}[{tag}]: {e}")
            continue
        results.append((s, body))
        extra = f" err={body[:120]}" if s.code >= 400 and body else ""
        print(f"  run{i}[{tag}]: tls={s.tls:.3f}s ttfb={s.ttfb:.3f}s total={s.total:.3f}s http={s.code}{extra}")
    return results


def main():
    ap = argparse.ArgumentParser(description="newapi 耗时定位诊断（配套 docs/LATENCY_DIAGNOSIS_GUIDE.md）")
    ap.add_argument("--base-url", required=True, help="如 https://api.example.com")
    ap.add_argument("--key", default="", help="测试令牌；不传则读环境变量 NEWAPI_KEY")
    ap.add_argument("--model", default="", help="用于 chat 测试的模型（建议选用户反馈的那个）；--list-models 时可省略")
    ap.add_argument("--origin-ip", default="", help="源站 IP，提供后启用直连源站对照（路径B）")
    ap.add_argument("--runs", type=int, default=3, help="每个非流式实验的采样次数（默认 3）")
    ap.add_argument("--max-tokens", type=int, default=16, help="chat 非流式输出上限（默认 16）")
    ap.add_argument("--prompt", default="hi", help="chat 测试 prompt（默认 hi）")
    ap.add_argument("--timeout", type=int, default=60, help="单请求超时秒数（默认 60）")
    ap.add_argument("--skip-stream", action="store_true", help="跳过流式测试")
    ap.add_argument("--list-models", action="store_true", help="仅列出中转站可用模型后退出，不跑诊断")
    args = ap.parse_args()

    key = args.key or os.environ.get("NEWAPI_KEY", "")
    if not key:
        sys.exit("缺少 --key 或环境变量 NEWAPI_KEY")

    u = urlparse(args.base_url)
    host, port = u.hostname, u.port or 443
    resolve = f"{host}:{port}:{args.origin_ip}" if args.origin_ip else ""
    base = f"{u.scheme}://{host}" + (f":{port}" if port != 443 else "")
    chat_body = json.dumps({"model": args.model, "messages": [{"role": "user", "content": args.prompt}],
                            "max_tokens": args.max_tokens})

    if args.list_models:
        names = fetch_models(base, key, args.timeout, resolve)
        print(f"{base} 可用模型 {len(names)} 个:")
        width = max((len(n) for n in names), default=0) + 2
        cols = max(1, 76 // width)
        for i in range(0, len(names), cols):
            print("  " + "".join(f"{n:<{width}}" for n in names[i:i + cols]))
        sys.exit(0)

    if not args.model:
        sys.exit("缺少 --model（诊断需指定模型；仅查看模型列表用 --list-models）")

    chain, has_cname, ips = dns_chain(host)
    print(f"== newapi 耗时诊断 ==  目标: {base}  模型: {args.model}  采样: {args.runs} 次/实验")
    print(f"DNS 解析 : {chain}")
    if args.origin_ip:
        if args.origin_ip in ips:
            print("链路判定 : DNS → 中转站（解析 IP 即源站，无中间层）")
        else:
            print(f"链路判定 : DNS → CDN/WAF → 中转站（解析 IP ≠ 源站 {args.origin_ip}，确认存在中间层）")
        print(f"路径A = 经接入链路: 按DNS正常解析连接（用户真实路径，含接入层）")
        print(f"路径B = 直连源站: --resolve 强制连接 {args.origin_ip}（剥离接入层，仅提供 --origin-ip 时测试）")
    else:
        if has_cname:
            print("链路判定 : DNS → CDN/WAF → 中转站（检测到 CNAME 链，存在 CDN/代理）")
        else:
            print("链路判定 : DNS → 中转站（未见 CNAME；若 CDN 以 A 记录方式接入则无法据此识别）")
        print("未提供 --origin-ip: 以下全部实验走用户真实路径，接入层与中转站无法拆分")
    print()

    names = pick_model(base, key, args.model, resolve, args.timeout)
    print(f"可用模型: {len(names)} 个（--list-models 查看全部）")
    print()

    # ---- 实验 1: 轻量接口 status ----
    print("[1] 轻量接口 /api/status — 路径A（无上游，反映接入+中转）")
    st_dom = run_set("status", args.runs,
                     lambda: curl_timing(base + "/api/status", key, timeout=args.timeout), tag="A")
    st_direct = []
    if args.origin_ip:
        print("[1b] 轻量接口 /api/status — 路径B（无上游，反映中转站本身）")
        st_direct = run_set("status-direct", args.runs,
                            lambda: curl_timing(base + "/api/status", key, timeout=args.timeout,
                                                resolve=resolve), tag="B")

    # ---- 实验 2: chat 非流式 ----
    print(f"[2] chat 非流式（{args.max_tokens} tokens 上限）— 路径A（用户真实总耗时）")
    chat_a = run_set("chat-A", args.runs,
                     lambda: curl_timing(base + "/v1/chat/completions", key, body=chat_body,
                                         timeout=args.timeout), tag="A")
    chat_b = []
    if args.origin_ip:
        print("[2b] chat 非流式 — 路径B（剥离接入层，纯上游）")
        chat_b = run_set("chat-B", args.runs,
                         lambda: curl_timing(base + "/v1/chat/completions", key, body=chat_body,
                                             timeout=args.timeout, resolve=resolve), tag="B")

    # ---- 实验 3: chat 流式（路径A 检测缓冲/卡顿；路径B 看纯上游流式）----
    stream_a = stream_b = None
    if not args.skip_stream:
        sbody = json.dumps({"model": args.model, "messages": [{"role": "user", "content": args.prompt}],
                            "max_tokens": 80, "stream": True})
        print("[3] chat 流式（SSE chunk 节奏分析）— 路径A（缓冲/卡顿检测，用户真实路径）")
        stream_a = stream_probe(base + "/v1/chat/completions", key, sbody, args.timeout * 2, None, "A")
        if args.origin_ip:
            print("[3b] chat 流式 — 路径B（剥离接入层，纯上游流式）")
            stream_b = stream_probe(base + "/v1/chat/completions", key, sbody, args.timeout * 2,
                                    resolve, "B")
    print()

    # ---- 端到端耗时与分段账本 ----
    print("=" * 62)
    print("端到端耗时（用户视角，中位数，仅计成功样本）")
    if chat_a:
        n = sum(1 for s, _ in chat_a if s.code == 200)
        extra = "" if n == len(chat_a) else f" ({n}/{len(chat_a)} 成功)"
        print(f"  路径A · 非流式 : 首字节 {med_ok(chat_a, 'ttfb'):.3f}s | 总耗时 {med_ok(chat_a, 'total'):.3f}s{extra}")
    if stream_a:
        print(f"  路径A · 流式   : 首 chunk {stream_a['first']:.2f}s | 总耗时(收尾) {stream_a['last']:.2f}s")
    if chat_b:
        n = sum(1 for s, _ in chat_b if s.code == 200)
        extra = "" if n == len(chat_b) else f" ({n}/{len(chat_b)} 成功)"
        print(f"  路径B · 非流式 : 首字节 {med_ok(chat_b, 'ttfb'):.3f}s | 总耗时 {med_ok(chat_b, 'total'):.3f}s{extra}")
        print(f"  路径B · 流式   : 首 chunk {stream_b['first']:.2f}s | 总耗时(收尾) {stream_b['last']:.2f}s"
              if stream_b else "  路径B · 流式   : 未测或失败")
        print(f"  对比           : 路径A 比路径B 慢 {med_ok(chat_a, 'total') - med_ok(chat_b, 'total'):+.3f}s（非流式，接入层引入，含建连/TLS 差异）"
              + (f"；流式首 chunk 慢 {stream_a['first'] - stream_b['first']:+.2f}s" if stream_a and stream_b else ""))

    print()
    print("分段账本（中位数）")
    verdicts = []
    st_dom_app = med([s.ttfb - s.tls for s, _ in st_dom if s.code == 200])

    if st_direct:
        dom_total = med_ok(st_dom, "total")
        dir_total = med_ok(st_direct, "total")
        access = dom_total - dir_total
        relay_app = med([s.ttfb - s.tls for s, _ in st_direct if s.code == 200])
        print(f"  接入层(CDN/WAF)贡献 : {access:+.3f}s  = 路径A {dom_total:.3f}s − 路径B {dir_total:.3f}s")
        print(f"  中转站处理          : {relay_app:.3f}s  (路径B 直连实测)")
        if access > ACCESS_CONTRIB_WARN:
            verdicts.append(("接入层(CDN/WAF)慢", f"每请求引入 {access:.2f}s，建议 API 域名绕过 CDN（手册 §8.1）", True))
        else:
            verdicts.append(("接入层", f"贡献 {max(access, 0):.2f}s，可接受", False))
        if relay_app > RELAY_APP_WARN:
            verdicts.append(("中转站自身慢", f"应用处理 {relay_app:.2f}s >{RELAY_APP_WARN}s，查 DB/Redis/负载（手册 §5.4）", True))
        else:
            verdicts.append(("中转站", f"应用处理 {relay_app * 1000:.0f}ms，正常", False))
        chat_src, upstream_note = chat_b, ""
    else:
        relay_app = st_dom_app
        print(f"  接入层+中转站合计   : {st_dom_app:.3f}s  (路径A，两者无法拆分；--origin-ip 可定位)")
        if st_dom_app > ACCESS_CONTRIB_WARN:
            verdicts.append(("接入链路+中转站合计偏高", f"{st_dom_app:.2f}s（无法区分是 CDN 还是中转站），加 --origin-ip 直连复测定位", True))
        else:
            verdicts.append(("接入链路+中转站", f"合计 {st_dom_app:.2f}s，可接受", False))
        chat_src, upstream_note = chat_a, "(含接入开销)"

    if chat_src:
        chat_app = med([s.ttfb - s.tls for s, _ in chat_src if s.code == 200])
        upstream = chat_app - relay_app
        gen = med([s.total - s.ttfb for s, _ in chat_src if s.code == 200])
        if st_direct:
            print(f"  上游首 token        : {upstream:.3f}s  (路径B 直连实测: chat 应用等待 {chat_app:.3f}s − 中转 {relay_app:.3f}s)")
        else:
            print(f"  上游首 token(近似)  : {upstream:.3f}s  (路径A: 含接入层开销，仅作参考)")
        print(f"  非流式生成传输      : {gen:.3f}s")
        if upstream > UPSTREAM_TTFT_BAD:
            verdicts.append((f"上游首 token 严重慢{upstream_note}", f"{upstream:.2f}s >{UPSTREAM_TTFT_BAD}s，测速对比渠道并降权/换供应商（手册 §6/§8.3）", True))
        elif upstream > UPSTREAM_TTFT_WARN:
            verdicts.append((f"上游首 token 偏慢{upstream_note}", f"{upstream:.2f}s >{UPSTREAM_TTFT_WARN}s，做渠道测速对比（手册 §6）", True))
        else:
            verdicts.append(("上游", f"首 token {upstream:.2f}s，正常", False))

    if stream_a:
        print(f"  流式(A)             : 路径A 经接入链路 | {fmt_stream_stats(stream_a)}")
        big_gaps = [g for g in stream_a["gaps"] if g > GEN_GAP_WARN]
        if big_gaps:
            verdicts.append(("流式存在卡顿", f"{len(big_gaps)} 次 gap>{GEN_GAP_WARN}s（最大 {max(big_gaps):.2f}s），可能缓冲/上游抖动（手册 §4.2）", True))
        else:
            verdicts.append(("流式", "chunk 到达均匀，透传正常", False))
    if stream_b:
        print(f"  流式(B)             : 路径B 直连源站   | {fmt_stream_stats(stream_b)}")

    print("-" * 62)
    print("结论")
    slow = [v for v in verdicts if v[2]]
    for name, detail, bad in verdicts:
        mark = "\033[31m⚠\033[0m" if bad else "\033[32m✓\033[0m"
        print(f"  {mark} {name}: {detail}")
    if not slow:
        print("  各段均在参考阈值内。若用户仍反馈慢，让用户侧抓分段计时（手册 §7 模式 6）。")
    print("\n详细判据与优化方案见 docs/LATENCY_DIAGNOSIS_GUIDE.md")
    sys.exit(1 if slow else 0)


if __name__ == "__main__":
    main()
