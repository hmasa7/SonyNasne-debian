#!/usr/bin/env python3
"""nasne の長時間の負荷試験。Mirakurun を通して、地デジと BS/CS をランダムに同時受信し続け、結果を JSON Lines で残す。

受信したデータは保存しない(その場で TS の同期と PID ごとの CC を調べて捨てる)。
HDD の温度を各 nasne の状態ページ(nasne-statusd、ポート 8302)から読み、上限を超えたら止め、下がったら再開する。

  python3 nasne_loadtest.py --status http://<nasne1>:8302 --status http://<nasne2>:8302 --mode zap --hours 24
  python3 nasne_loadtest.py ... --mode long --dwell 3600

--mode zap : 既定 40 秒ごとに局を変える(選局と B-CAS・I2C に負荷)
--mode long: 既定 1 時間ずつ受信する(長時間の安定性)
優先度 0 で受信するので、録画(EPGStation は既定で 2)には譲る。同じ優先度の視聴とは取り合いになる。
"""
import argparse, json, random, socket, threading, time, urllib.request
from datetime import datetime


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def nasne_status(url):
    """状態ページから HDD の温度などを読む。応答しないとき(MCU の I2C が止まった兆候)は reachable=False"""
    try:
        s = get_json(url.rstrip("/") + "/status.json", 15)
        h = s.get("hdd") or {}
        m = s.get("mcu") or {}
        return {"url": url, "reachable": True, "temp": h.get("temperature_c"), "ok": s.get("ok"),
                "warnings": s.get("warnings"), "mcu": m.get("available")}
    except Exception as e:
        return {"url": url, "reachable": False, "error": str(e)[:80]}


def services(mirakurun):
    gr, sat = [], []
    for s in get_json(mirakurun + "/api/services", 30):
        ch = s.get("channel") or {}
        if s.get("type") != 1:          # テレビのサービスだけ(ワンセグ・データ・ラジオを除く)
            continue
        (gr if ch.get("type") == "GR" else sat if ch.get("type") in ("BS", "CS") else []).append(
            {"id": s["id"], "name": s.get("name", ""), "type": ch.get("type"), "channel": ch.get("channel")})
    return gr, sat


def pick(pool, n):
    """物理チャンネルが重ならないように n 個選ぶ"""
    out, used = [], set()
    for s in random.sample(pool, len(pool)):
        if s["channel"] in used:
            continue
        out.append(s); used.add(s["channel"])
        if len(out) == n:
            break
    return out


def receive(mirakurun, svc, dwell, res):
    """1 本受信して、最初のデータまでの時間・量・同期外れ・PID ごとの CC エラーを数える"""
    r = {"t": now(), "id": svc["id"], "name": svc["name"], "type": svc["type"], "channel": svc["channel"]}
    t0 = time.time()
    req = urllib.request.Request(f"{mirakurun}/api/services/{svc['id']}/stream", headers={"X-Mirakurun-Priority": "0"})
    nbytes, sync_lost, first = 0, 0, None
    cc, ccerr, npk = {}, {}, {}
    pmt_pid, pmt_buf, av = None, b"", None     # PAT → PMT から映像・音声の PID を取る(nasne-recpt1 は最初に PAT・PMT を送る)
    rest = b""
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            r["http"] = f.status
            while time.time() - t0 < dwell:
                chunk = f.read(188 * 512)
                if not chunk:
                    r["ended_early"] = round(time.time() - t0, 1)
                    break
                if first is None:
                    first = time.time() - t0
                nbytes += len(chunk)
                buf = rest + chunk
                n = len(buf) // 188 * 188
                for i in range(0, n, 188):
                    if buf[i] != 0x47:
                        sync_lost += 1
                        continue
                    b1, b3 = buf[i + 1], buf[i + 3]
                    pid = ((b1 & 0x1f) << 8) | buf[i + 2]
                    if pid == 0x1fff or not (b3 & 0x10):      # ヌルと、ペイロードの無いパケットは CC を見ない
                        continue
                    npk[pid] = npk.get(pid, 0) + 1
                    if av is None and (pid == 0 or pid == pmt_pid):
                        off = i + 4 + ((1 + buf[i + 4]) if b3 & 0x20 else 0)
                        pay = buf[off:i + 188]
                        if b1 & 0x40:
                            pay = pay[1 + pay[0]:] if pay else b""
                            if pid == 0 and len(pay) >= 12:
                                end = 3 + (((pay[1] & 0x0f) << 8) | pay[2]) - 4
                                for k in range(8, min(end, len(pay) - 3), 4):
                                    if pay[k] | pay[k + 1]:
                                        pmt_pid = ((pay[k + 2] & 0x1f) << 8) | pay[k + 3]
                                        break
                            elif pid == pmt_pid:
                                pmt_buf = pay
                        elif pid == pmt_pid and pmt_buf:
                            pmt_buf += pay
                        if pid == pmt_pid and len(pmt_buf) >= 12 and len(pmt_buf) >= 3 + (((pmt_buf[1] & 0x0f) << 8) | pmt_buf[2]):
                            end = 3 + (((pmt_buf[1] & 0x0f) << 8) | pmt_buf[2]) - 4
                            k = 12 + (((pmt_buf[10] & 0x0f) << 8) | pmt_buf[11])
                            av = []
                            while k + 5 <= end:
                                st, es = pmt_buf[k], ((pmt_buf[k + 1] & 0x1f) << 8) | pmt_buf[k + 2]
                                if st in (0x01, 0x02, 0x1b, 0x24, 0x03, 0x04, 0x0f, 0x11):     # 映像(MPEG-2/H.264/H.265)・音声(MPEG/AAC)
                                    av.append(es)
                                k += 5 + (((pmt_buf[k + 3] & 0x0f) << 8) | pmt_buf[k + 4])
                    c = b3 & 0x0f
                    p = cc.get(pid)
                    if p is not None and c != p and c != (p + 1) & 0x0f:
                        ccerr[pid] = ccerr.get(pid, 0) + 1
                    cc[pid] = c
                rest = buf[n:]
    except urllib.error.HTTPError as e:
        r["http"] = e.code
    except (socket.timeout, Exception) as e:
        r["error"] = str(e)[:80]
    r["first_s"] = round(first, 2) if first is not None else None
    r["secs"] = round(time.time() - t0, 1)
    r["mbytes"] = round(nbytes / 1e6, 1)
    r["sync_lost"] = sync_lost
    r["cc_err"] = {f"0x{k:04x}": v for k, v in sorted(ccerr.items())}
    r["cc_err_total"] = sum(ccerr.values())
    if not av:      # PMT が読めなかったときは、パケット数のいちばん多い PID(映像)だけを見る
        av = sorted(npk, key=npk.get, reverse=True)[:1]
        r["av_from_pmt"] = False
    r["av_pids"] = [f"0x{k:04x}" for k in av]
    r["cc_err_av"] = sum(ccerr.get(k, 0) for k in av)
    res.append(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mirakurun", default="http://localhost:40772")
    ap.add_argument("--status", action="append", default=[], help="nasne の状態ページ(複数可)。温度の見張りに使う")
    ap.add_argument("--mode", choices=["zap", "long"], default="zap")
    ap.add_argument("--dwell", type=int, help="1 回の受信の秒数(既定 zap 40、long 3600)")
    ap.add_argument("--gr", type=int, default=2, help="同時に開く地デジの本数")
    ap.add_argument("--sat", type=int, default=2, help="同時に開く BS/CS の本数")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--temp-max", type=int, default=62, help="この温度(℃)以上の nasne があれば止める")
    ap.add_argument("--temp-resume", type=int, default=58, help="すべてこの温度以下になったら再開する")
    ap.add_argument("--rest", type=int, default=5, help="1 回ごとの休み(秒)")
    ap.add_argument("--log", default=f"nasne_loadtest_{datetime.now():%Y%m%d_%H%M}.jsonl")
    a = ap.parse_args()
    dwell = a.dwell or (40 if a.mode == "zap" else 3600)
    gr, sat = services(a.mirakurun)
    print(f"{now()} 開始: 地デジ {len(gr)} サービス、BS/CS {len(sat)} サービス、{a.mode} {dwell} 秒、地デジ {a.gr} + 衛星 {a.sat} 本、記録 {a.log}", flush=True)
    end = time.time() + a.hours * 3600
    rnd, hour_t, hour = 0, time.time(), []
    with open(a.log, "a") as log:
        def w(o):
            log.write(json.dumps(o, ensure_ascii=False) + "\n"); log.flush()
        while time.time() < end:
            sts = [nasne_status(u) for u in a.status]
            w({"t": now(), "kind": "status", "nasne": sts})
            hot = [s for s in sts if s.get("temp") is not None and s["temp"] >= a.temp_max]
            if hot:
                print(f"{now()} 温度が上限 {a.temp_max}℃ 以上: {[(s['url'], s['temp']) for s in hot]}。{a.temp_resume}℃ 以下になるまで止める", flush=True)
                w({"t": now(), "kind": "pause", "hot": hot})
                while time.time() < end:
                    time.sleep(60)
                    sts = [nasne_status(u) for u in a.status]
                    w({"t": now(), "kind": "status", "nasne": sts})
                    if all(s.get("temp") is None or s["temp"] <= a.temp_resume for s in sts):
                        print(f"{now()} 再開: {[(s['url'], s.get('temp')) for s in sts]}", flush=True)
                        w({"t": now(), "kind": "resume"})
                        break
                continue
            for s in sts:
                if not s["reachable"]:
                    print(f"{now()} 状態ページが応答しない: {s['url']}({s.get('error')})。MCU の I2C の止まりの可能性", flush=True)
            rnd += 1
            chosen = pick(gr, a.gr) + pick(sat, a.sat)
            res, th = [], []
            for s in chosen:
                t = threading.Thread(target=receive, args=(a.mirakurun, s, dwell, res))
                t.start(); th.append(t)
                time.sleep(0.5)
            for t in th:
                t.join()
            for r in res:
                r["round"] = rnd; r["kind"] = "stream"; w(r)
                bad = r.get("http") != 200 or r.get("first_s") is None or r["sync_lost"] or r.get("error") or r.get("ended_early")
                if bad:
                    print(f"{now()} 異常: {r['type']} {r['name']} http={r.get('http')} first={r.get('first_s')} {r.get('error', '')} ended_early={r.get('ended_early')}", flush=True)
            hour += res
            if time.time() - hour_t >= 3600:
                ok = [r for r in hour if r.get("http") == 200 and r.get("first_s") is not None]
                fs = sorted(r["first_s"] for r in ok)
                temps = [s.get("temp") for s in sts]
                print(f"{now()} 1 時間の集計: {len(hour)} 本、映った {len(ok)}、失敗 {len(hour) - len(ok)}、"
                      f"最初のデータまで中央値 {fs[len(fs) // 2] if fs else '-'} 秒、CC エラー(映像・音声){sum(r['cc_err_av'] for r in hour)} / 全体 {sum(r['cc_err_total'] for r in hour)}、温度 {temps}", flush=True)
                hour_t, hour = time.time(), []
            time.sleep(a.rest)
    print(f"{now()} 終了", flush=True)


if __name__ == "__main__":
    main()
