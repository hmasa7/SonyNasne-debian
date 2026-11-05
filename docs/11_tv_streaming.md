# 11. 地デジを受信して配信する(`nasne-recpt1`)

> **層**: 【CFW共通】 `nasne-recpt1`(旧・新どちらのカーネルでも同じ)。ビルド環境の記述(Docker の gcc 4.3.2)は【旧】の環境です。【新】では `scripts/build_tools.sh`(ホストの `mipsel-linux-gnu-gcc`)でもビルドできます([docs/22](22_new_kernel_612.md))。

Debian直起動のnasneで、**地デジをB-CASカードで復号し、元の画質のまま(MPEG-2 1440×1080 など)TSとして取り出す**ためのツールと使い方。
録画ソフト・プレーヤーから使える2つの形で提供している。

| 形 | 用途 |
|---|---|
| `nasne-recpt1 <ch> <秒数> <出力>` | `recpt1` 互換のコマンド。標準出力にTSを流せる。nasne上で実行する |
| `nasne-recpt1 --listen 8301`(HTTPサーバ、起動時サービス) | `http://<nasne>:8301/tuner/<ch>` でTSをHTTP配信。VLC、tvheadend、Kodi、ffmpeg、Jellyfin などのIPTV入力に使える |

⚠️ B-CASカードを使います。自分の機器・自分のカードで、私的な視聴・録画の範囲で使ってください。
(復号はnasne純正と同じく、nasne内のファームウェアがB-CASカードと直接やり取りして行います。カードのIDや鍵は取り出していません。)

## できること / 制限

| | |
|---|---|
| ✅ | 地デジ(ISDB-T)UHF 13〜62 の選局、B-CAS復号済みの**元画質TS**(MPEG-2映像、AAC音声、字幕・データ放送のPIDも含む)の取得。ビットレートは約15Mbps |
| ✅ | PAT(元のもの)・NIT / SDT / EIT / TOT などの**SI(番組表の元データ)**も混ぜて出力 |
| ✅ | HTTP配信、`/scan` によるサービス一覧、連続2分(約230MB)の受信で同期エラー・スクランブル残り無し(連続カウンタの乱れは番組表・データ放送のPIDで数回)。**Mirakurunから実際に使えることを確認**(スキャン・番組表・ストリーム) |
| ✅ | 終了時(秒数経過・シグナル・接続切断)にストリームを必ず閉じる。2つ目の要求にはチューナー使用中(exit 3 / HTTP 503)を返す |
| ⚠️ | **同時に1チャンネル・1サービスのみ**。1回の接続で出力されるのは選んだ1サービス(+全サービス分のSI)で、チャンネル全体(全サービス)のTSではない |
| ⚠️ | 既定では、チューナーは1系統として扱っている(地デジも衛星も同じロック)。**地デジと BS/CS の同時受信は、`--dual-tuner`(試験的。[下記](#地デジと-bscs-の同時受信試験的--dual-tuner))で有効にできる**が、電波のある環境での確認は未実施。**BS/CS110 は、他の人の実機で受信できたとの報告をもとに取り込んだもので、作者の環境(BS/CS の信号が来ない)では未検証**([docs/08](08_tuner_i2c.md)) |
| ⚠️ | **ワンセグは扱わない**。ワンセグ(PMTのPIDが0x1FC8、SDTのservice_typeが0xC0)に対して復号ストリームを開くと、ファームが応答しなくなり、受信側の処理がドライバ内で戻らなくなる(`SIGKILL` も効かず、`reboot -f` が必要)。一覧(`/scan`・M3U)には `(1seg)` として載せず、明示的に指定されても404を返す |
| ⚠️ | 開始まで約2〜4秒かかる(選局、ロック待ち、PAT/PMT取得、ストリーム確立) |
| ⚠️ | サービス名・番組表の文字(ARIB文字コード)はそのまま出力しているだけ。デコードは録画ソフト側 |

## 使い方

### 準備

```bash
# MIPS用にビルド(docs/05のDocker環境 nasne-kcc:gcc432)
mipsel-linux-gcc -nostdlib -static -fno-pic -mno-abicalls -mips32r2 -O2 -e __start -o nasne-recpt1 scripts/tools/nasne_recpt1.c
scp nasne-recpt1 root@<nasne>:/usr/local/sbin/
scp scripts/watchdog/nasne-recpt1-server root@<nasne>:/etc/init.d/
ssh root@<nasne> 'chmod +x /etc/init.d/nasne-recpt1-server; update-rc.d nasne-recpt1-server defaults 20; /etc/init.d/nasne-recpt1-server start'
```

前提: 公式ドライバ(`xcode4drv.ko`、`rc.xcode4`)が `/usr/local/sbin/` にあり、起動時にロードされている([docs/06](06_mcu_watchdog.md)のサービスが行う)こと。
B-CASカードがnasneに挿さっていること。ファームが止まっていれば、ツールが自動で `rc.xcode4` を実行してドライバを再読込する。

### コマンドライン(recpt1互換)

```bash
nasne-recpt1 [--sid <サービスID>] [-v] <UHFチャンネル 13〜62 | --freq MHz> <秒数 | -> <出力ファイル | ->
nasne-recpt1 27 60 /tmp/a.ts            # UHF 27 を60秒、ファイルへ
nasne-recpt1 27 - - | ffplay -           # 無期限、標準出力へ(止めるときはSIGTERM/Ctrl-C/パイプを閉じる)
nasne-recpt1 --sid 0x0401 27 10 -        # サービスを指定
nasne-recpt1 --scan                      # UHF 13〜62 をスキャンして、ロックしたチャンネルのサービス一覧を表示(--scan-sat: BS/CS のみ、--scan-all: 全部。PR #5)
```

`--b25` `--strip` `--device` `--lnb` など recpt1 のオプションは受け付けて無視する。

#### BS/CS110(報告をもとに取り込み。作者の環境では未検証)

チャンネルに `BS1`〜`BS23`(奇数)、`BS15_0` のような `<トランスポンダ>_<スロット>`、`CS2`〜`CS24`(偶数)が指定できる。
スロットや CS は、TSID(復調ICのレジスタ `0x8F`/`0x90` に書く。[docs/08](08_tuner_i2c.md))が決まるとスロット多重の中から目的の局が選ばれる。TSID は `--tsid 0xNNNN`(HTTP は `?tsid=0xNNNN`)でも直接指定できる。

```bash
nasne-recpt1 BS15_0 60 /tmp/a.ts           # BS15 のスロット0を60秒
nasne-recpt1 --sid 0x0067 BS1_0 10 -       # サービスも指定
curl 'http://<nasne>:8301/tuner/CS6?sid=0x....' | ffplay -
```

- BS の TSID 表は、放送事業者の追加や帯域再編で変わる(`nasne_recpt1.c` の `get_bs_tsid()`)。
- 1つのトランスポンダに多くのサービスが載るため、PAT/PMT の収集上限を 31 サービスにしてある。
- **`--scan` と `/scan` は、既定では地デジ(UHF 13〜62)だけ**。BS/CS は `--scan-sat`・`/scan?sat`(衛星のみ)、`--scan-all`・`/scan?all`(全部。BS は全トランスポンダ・全スロット、CS は ND2〜ND24。数分かかる)でスキャンする(PR #5。**作者の環境では信号が無く未検証**。投稿者の環境で、地デジ33・BS45・CS54 の計132サービスを収集して動作確認)。
- 衛星のときだけ、PSI ストリームから PMT を出力 TS へ混ぜる(地デジは復号済みのストリームに PMT が含まれていて、混ぜると二重になる)。

#### Mirakurun で BS/CS を使う

nasne は **1回に1サービスしか出力しない**ので、Mirakurun のチャンネルは「サービスごと」に1つ要り、サービスの指定(`?sid=0x…`)をコマンドに渡す必要がある。
**チャンネル名に `?sid=` を含める方式は、Mirakurun の API や TVTest で 404・不正な形式になる**ので、`commandVars` に分ける(上の `channels.yml` の説明)。`nasne_mirakurun_conf.py` がこの形式を自動で作る。

| 種類 | `nasne-recpt1` が受け付けるチャンネル | 例(Mirakurun のチャンネル名) |
|---|---|---|
| 地デジ | `13`〜`62`(あとに `_<任意>` が付いてもよい) | `27_56360` |
| BS | `BS<奇数1〜23>` または `BS<奇数>_<スロット>`(先頭の 0 は付けても付けなくてもよい。あとに `_<任意>` が付いてもよい)。**偶数は不可(400)** | `BS15_0_101` |
| CS110 | `CS<偶数2〜24>`(`CS02` も可。スロット・接尾辞は無視) | `CS2_257` |

**いちばん簡単な手順**(nasne 自身がスキャンする。PR #5 で追加。BS/CS の信号が来ている環境):

```bash
# nasne に BS/CS を含めてスキャンさせ(数分。チューナーを使うので録画中は避ける)、Mirakurun の設定を作る
python3 scripts/nasne_mirakurun_conf.py <nasne> --sat --scan -o mirakurun-conf
# → tuners.yml(types に GR・BS・CS)と channels.yml(サービスごと)ができる。Mirakurun を再起動
```

`/scan`(地デジのみ)、`/scan?sat`(衛星のみ)、`/scan?all`(全部)で、結果は `/playlist.m3u8` に出る(`group-title` は `UHF`・`BS`・`CS`)。**スキャンのたびに一覧(キャッシュ)は、スキャンした種類だけで置き換わる**(地デジだけをスキャンすると、BS/CS の一覧は消える)。
`tuners.yml` のコマンドは、既定で `node -e "require('http').get(…)"`(Mirakurun の公式イメージには **curl が入っていない**。node は入っている。実測)。curl を足したイメージを使うなら `--command curl`。

**Mirakurun 自身のチャンネルスキャンを使う場合**(代替):
- BS のスキャンの**既定のチャンネル名は `101`〜`256`** で、`nasne-recpt1` は受け付けない(400)。**`useSubCh=1`(`PUT /api/config/channels/scan?type=BS&useSubCh=1`)で `BS01_0`〜`BS23_3` の形式**になる。CS は既定で `CS2`〜`CS24`。Mirakurun は `useSubCh=false` のような文字列も真と読むので、値は `1` にするか、付けない。
- スキャンが書く項目は、`commandVars` が無く、チャンネル名が一意でなく、**衛星の項目は既定で `isDisabled: true`**。`python3 scripts/nasne_mirakurun_conf.py --fix-sat mirakurun-conf/channels.yml --enable` で、一意な名前(`BS01_0_101`・`CS2_257`)と `commandVars` に直し、有効にする(元は `.bak`。何度実行しても同じ結果)。同じディレクトリの `tuners.yml` のコマンドにも `<sid_query>` を足す。
- `tuners.yml` の `types` に BS・CS が入っていること(`--sat`)。

`nasne_mirakurun_conf.py` は **`channels.yml` を書き直す**。局が変わって作り直したら、Mirakurun のスキャンを使っていた場合は、そのあとで `--fix-sat` をやり直すこと。

終了コード: 0 正常 / 1 エラー(ロックしない・サービスが無い・ストリームが開けない) / 2 使い方 / 3 チューナー使用中。

### HTTP

```
GET /tuner/<UHF ch>[?sid=0xNNNN][&sec=N][&si=1]   復号済みTS(video/MP2T)。切断するとストリームを閉じる。sec を付けるとN秒で終了。
                                                  si=1 を付けると、SI(PAT・EIT など)だけを出す(B-CAS を使わない。番組表の取得用)
GET /<UHF ch>                              同上(短縮形)
GET /scan[?sat|?all]                        サービス一覧(テキスト。地デジのみ約80秒。?sat=衛星のみ、?all=全部で数分)。サービス名も出し、結果を保存する
GET /playlist.m3u8                         /scan の保存結果から作ったM3U(VLCなどでそのまま開ける)
GET /status                                idle または busy
```

使用中は `503 Service Unavailable`、信号なしは `404`。

```bash
curl http://<nasne>:8301/tuner/27 | ffplay -
curl -s http://<nasne>:8301/scan
# ch=27 freq=557142kHz sid=0x0400(tv) name="局名1" sid=0x0401(tv) name="局名2" sid=0x0408(1seg) name="局名携帯"
```

サービス名は SDT(ARIBの8単位符号)をUTF-8に直して出す。`(tv)` が地デジのテレビ、`(1seg)` がワンセグ、`(data)` がデータ放送。
`/scan` は結果を nasne 上の `/var/lib/nasne-recpt1/services.tsv` に保存する(最後まで走ったときだけ置き換える。**スキャンした種類だけで置き換わる**)。

**チューナーの連続選局**: `nasne-recpt1` は、前のセッションの終了から 300ms 以内に次のセッションを開くときだけ、差分を待つ(`/tmp/nasne-recpt1.lock` に終了時刻を書く。PR #5)。複数クライアントの頻繁な開閉で SoC(xcodedrv)が D 状態で固まる件の緩和策の、暫定値(`300ms` は仮。効果は作者の試験では評価できていない)。通常の選局は待たない。

### 録画ソフトとの連携

#### Mirakurun(動作確認済み)

Mirakurun 4.1(Node.js 22以上推奨)で、nasne のHTTP配信を「コマンド型チューナー」として使い、**チャンネルスキャン・サービス名の取得・ストリーム取得・番組表(EIT)の取得**まで動いた。
Mirakurun は別のPCで動かす(nasne上ではなく)。**EPGStation も動作確認済み**(下の「EPGStation」)。

`tuners.yml`:

```yaml
- name: nasne
  types:
    - GR
  command: node -e "require('http').get('http://<nasneのIP>:8301/tuner/<channel><sid_query>', res => res.pipe(process.stdout))"
  isDisabled: false
```

`channels.yml`(**サービスごとに1エントリ**。nasne は1回に1サービスしか出力しないため。`nasne_mirakurun_conf.py` が、これを自動で作る):

```yaml
- name: 局名
  type: GR
  channel: '27_1024'           # 一意な名前(物理チャンネル _ サービスID(10進))。`?` は使わない
  serviceId: 1024              # 0x0400 の10進数
  commandVars:                 # コマンドの <sid_query> に入る(Mirakurun の commandVars)
    sid_query: "?sid=0x0400"
    sid: "0x0400"
  isDisabled: false
- name: 局名2
  type: GR
  channel: '27_1025'
  serviceId: 1025
  commandVars:
    sid_query: "?sid=0x0401"
    sid: "0x0401"
  isDisabled: false
```

- コマンドは `.../tuner/<channel><sid_query>`。`nasne-recpt1` は、`27_1024` の `_` 以降(接尾辞)を無視して、物理チャンネル 27 を選局し、`?sid=` でサービスを選ぶ。
- **チャンネル名を `27?sid=0x0400` のように `?` を含めると、Mirakurun の API(`/api/channels/GR/27?sid=…`)が 404 になり、TVTest(BonDriver_Mirakurun)などでも不正な形式になる**(実測。PR #5 で報告)。そのため、サービス情報は `commandVars` に分ける。
- **名前をサービスごとに一意にする**理由: 同じ物理チャンネルのサービスが同じ名前だと、Mirakurun は「同じチャンネル」とみなして、2つ目のサービスの要求を、1つ目のストリームに相乗りさせる。nasne は1サービスしか出さないので、2つ目は**データが来ないまま切れる**(実測: 約15秒後に空で切断)。名前が違えば、チューナーが空くのを待って選局し直す(実測: 1つ目が終わったあと、続けて取得できた)。

サービスIDの調べ方: `curl http://<nasne>:8301/scan`(`sid=0x...(tv)` の一覧)。

確認した結果: Mirakurun が起動時にサービススキャンを行い、サービス名(ARIB文字を含む)・ネットワークID・サービスIDを取得した。
番組表は約1分の受信で数百件の番組が取れた。`/api/services/<id>/stream` からは、元画質(MPEG-2 1440×1080 + AAC + 字幕)のTSが取得できた。
Mirakurunのチャンネルスキャン(自動)は、チャンネル全体のTSを前提にするため、**サービスごとのチャンネル設定を手書きするのが確実**。

**出力する PAT・PMT と音声(PR #9 で整理、2026-10-22)**: `--sid`(HTTP では `?sid=`)を指定したときの TS は、SoC が作る**単一サービスの PAT**(NIT とそのサービスだけ)と、**CA 記述子を除去した PMT** だけを出します(衛星で元の PMT を混ぜていた処理は廃止。PMT の二重混入による CC エラーと、字幕が暗号化と誤認されて出ない症状が直った)。また、PMT に**音声 ES が複数**(二ヶ国語・解説音声など。最大4本)ある番組は、すべての音声を復号して出します(以前は主音声の1本だけで、副音声は PMT に載っているのにパケットが出なかった=KonomiTV で第2音声が `0 channels` になる原因)。

**受信の始まりの PAT・PMT の送り直し(`--start-pace`、2026-11-05)**:
> 層: 【CFW共通】

- **症状**: Mirakurun 経由で KonomiTV(0.14.1、QSVEncC)から CS を開くと、最初の 1 回だけ「入力ストリームの解析に失敗しました(ER-02H)」になり、KonomiTV が自動でやり直して 2 回目で映る。手元では CS の 3 回中 3 回。地デジ(20 回)と BS(14 回)では出なかった。
- **原因(実測で確認)**: Mirakurun(4.2.1)のサービス単位のフィルタは、PMT を解析し終わるまでに届いたパケットを、**PAT・PMT 自身も含めて**捨てる。解析は、受け取ったかたまりを処理した後に非同期で行われる。
  - nasne の出力は、映像の最初のシーケンスヘッダ(デコードを始められる位置)から始まる。しかし Mirakurun の出力の先頭には PAT・PMT が無く、次の周期の PAT が来るまで(261〜1860 パケット目)エンコーダはその映像を使えない。
  - そのため、デコードは次のシーケンスヘッダ(約 0.5 秒後)からになる。CS はそこまでのデータが多く、KonomiTV の最初の解析(`--input-probesize 1000K --input-analyze 0.7`)に収まらない。2 回目は解析の範囲を広げる(1500K / 0.9)ので映る。
  - Mirakurun の出力を保存したファイルを、KonomiTV と同じ `tsreadex` → QSVEncC の経路に通すと、CS は毎回失敗した。nasne から直接取ったファイルは成功した。
- **対策(`nasne-recpt1`、既定で有効)**:
  1. 最初の PAT を送ったあと、少し待つ(既定 60ms)。
  2. 最初の映像・音声の前で、もう一度待ってから PAT・PMT を送り直す。準備完了の前に届いた分は捨てられるので、さらに待ってもう一度送り、それから映像を送る。増える待ちは約 0.2 秒。
  3. PMT が 2 パケットにまたがり、2 つ目が映像より後に来る局(25ch。PMT 211 バイト)では、PMT がそろうまで(最大 0.5 秒)映像をためてから送る(実測では約 100 パケット、数 ms)。
  4. 送り直した PAT・PMT は CC を続きの番号にし、その後の元のパケットも同じだけずらす。同じ CC のままだと、25ch の PMT で CC エラーが 1 件出た。
  - `--start-pace 0` で以前の動き(待たない・送り直さない)に戻る。
- **検証(手元、Mirakurun 4.2.1 経由、毎回チューナーが空いた状態から選局)**:
  - Mirakurun の出力の先頭が PAT になり、3〜4 パケット目にシーケンスヘッダが来る。KonomiTV と同じ経路・同じ条件(1000K / 0.7)で、CS 161・55、BS 101・151、地デジ 24ch・25ch の延べ 17 回が、すべて最初の 1 回で解析に成功した。
  - nasne から直接取った TS(`ts_analyze.py`)では、PAT・PMT の CC エラーは 0。
  - 25ch のデータ放送の PID(0x511〜0x613)に 1 件ずつ出る CC エラーと、CS の EIT(0x12)の CC エラー(1〜5 件)は、**変更前の版でも同じように出る**(この変更とは無関係。原因は未調査)。
  - KonomiTV(0.14.1、QSVEncC)の画面で、CS が最初の 1 回で映ることを確認した(2 回とも ER-02H なし)。

**Docker で Mirakurun を動かすときは、`/app-config` と `/app-data` の両方を永続化してください**(`contrib/epgstation/docker-compose.yml` の `volumes` のとおり)。`/app-data` を永続化しないと、Mirakurun を再起動するたびに、全チャンネルのサービス検出(`Service.Add.Check.*` のジョブ)と番組表の取得をやり直します。nasne のチューナーは1系統なので、そのジョブが連続してチューナーを占有し、視聴や録画が `503 tuner busy` / `/status` が `busy` のまま、という状態が長く続きます(BS/CS を足してチャンネル数が増えるほど長くなる。Issue #6)。初回のスキャンは、BS/CS を含めて30分〜1時間かかることがあります。`nasne-recpt1` のストリーム子プロセスが `ps` で `D` 状態に見えるのは、受信中の通常の状態です。

Mirakurunのデコーダー(`decoder`)設定は不要(nasne が復号済みのTSを出す)。複数サービスの同時視聴は、チューナーが1系統なので不可(同じチャンネルの別サービスも不可)。

`tuners.yml` / `channels.yml` は `python3 scripts/nasne_mirakurun_conf.py <nasneのIP> --scan -o <設定ディレクトリ>` で nasne のサービス一覧から自動で作れます(手で書く必要はありません)。
**公式の Mirakurun の Docker イメージには curl が入っていません**。`curl` を足したイメージが要ります([contrib/epgstation](../contrib/epgstation/README.md))。

#### EPGStation(動作確認済み)

Mirakurun 4.1 + EPGStation 3.0(beta)を Docker で動かし、nasne をチューナーにして次を確認しました([contrib/epgstation](../contrib/epgstation/README.md) に compose と手順)。

- サービスの検出(20サービス、約3分)→ 全局の番組表の取得(約10分、数千件)→ EPGStation のチャンネル一覧・番組表に反映。
- 放送中の番組の予約 → 録画開始。約15Mbpsの元画質(MPEG-2 1440×1080 + AAC + 字幕)で約160秒を録画し、4797フレーム(29.97fps×160秒と一致)、先頭の数行以外にデコードエラーなし。
- これから始まる番組の予約 → 予約時刻の約15秒前にチューナーを開き、時刻どおりにファイルが作られて録画された。
- 録画中は番組表の取得(EPG収集)が止まり、録画が優先される。チューナーは1系統なので、裏番組の同時録画はできない。

確認済み(2026-10): 約4日の連続運用(EPGStation の予約録画12本)、tvheadend。未確認: 録画後のエンコード。

**nasne 2 台で 4 本の同時録画(2026-11-05)**:
> 層: 【CFW共通】(旧カーネル、`--dual-tuner --shared-generic`、GPL 版ドライバ `fw_secondary=23`)

- Mirakurun(4.2.1)に、2 台の nasne を地デジ用・衛星用の 4 チューナーとして登録し、EPGStation(3.0.0-beta4)で**地デジ 2 本・BS 2 本を同時に録画できた**。ファイルは 4 本とも増え続け(約 12〜20Mbps)、2 台とも GENERIC の作り直し・出力の停止・`Mips Failed` は 0 件、負荷は約 1.2。
- **Mirakurun のチューナーの構成(数や、地デジ・BS・CS の割り当て)を変えたら、EPGStation を再起動する**。EPGStation は、起動したときに読んだチューナーの構成で予約の重なりを計算する。地デジ・BS・CS 兼用の 2 チューナーの構成で起動したまま、地デジ用・衛星用の 4 チューナーに分けたら、地デジを 2 本録画している間は BS の予約が `program is conflict` で拒まれた(Mirakurun には BS の要求が来ず、BS のチューナーは空いていた)。EPGStation の再起動で直った。録画中に再起動すると、その録画は止まるので、録画の無い時間に行う。

#### VLC(プレイリスト再生)

先に `curl http://<nasne>:8301/scan` を1回実行して(約80秒)、サービス一覧を保存する。あとは

```bash
vlc http://<nasne>:8301/playlist.m3u8
```

で、局名つきのプレイリストが開く(**VLCで再生できることを確認済み**)。M3Uは `#EXTINF:-1 group-title="UHF27",局名` の形で、各エントリの URL は
`http://<アクセスしたアドレス>:8301/tuner/27?sid=0x....`(リクエストの `Host:` ヘッダのアドレスを使う)。
チューナーは1系統なので、**同時に再生できるのは1チャンネルだけ**。プレイリストを次の項目へ送ると、直前の接続が閉じ終わる前に次を開いて `503` になることがあるが、少し待てば再生できる。

#### ffmpeg / Kodi / Jellyfin など

`http://<nasne>:8301/tuner/<ch>?sid=0x....` を再生/IPTVチャンネルとして登録する。mpv・ffmpeg で、URL を直接再生できることを確認した。
- **Jellyfin**: M3U を「ライブTV」のチューナーに追加すると、**20チャンネルを取り込める**(確認済み)。ただしライブ視聴は**確認できていない**(再生前の `ffprobe` が終わらない、プローブと本再生が別の接続でチューナーを開くため2本目が503になる)。詳しくは [contrib/tvheadend](../contrib/tvheadend/README.md)。
- **Kodi**: tvheadend の HTSP(`pvr.hts`)経由を勧める。IPTV Simple Client で M3U を直接読ませるのは未確認。
- ほかの IPTV クライアントも、**チューナーは1系統**なので、同時に複数のチャンネルは開けない。

#### tvheadend(動作確認済み)

IPTV 自動ネットワークに `playlist.m3u8` を登録すると、20サービスを検出でき、手動のDVR予約で録画できました(約14.4Mbps)。手順・注意は [contrib/tvheadend](../contrib/tvheadend/README.md)(`--ulimit nofile`、`max_streams=1`、アイドルスキャンの停止など)。

## 地デジと BS/CS の同時受信(試験的、`--dual-tuner`)

nasne は、地デジ用と衛星用で、復調 IC の系統(I2C 0x10 と 0x11)も RF チューナーも別々です。既定の `nasne-recpt1` は、安全側に、地デジも衛星も**同じ1つのロック**で直列化していますが、`--dual-tuner` を付けると、**地デジ用と衛星用のロックに分け、地デジ1番組と BS/CS 1番組を同時に使える**ようになります(同じ系統の2番組は同時にできません)。

**有効にする**(nasne 上で):
```
echo NASNE_RECPT1_DUAL=1 > /etc/default/nasne-recpt1
/etc/init.d/nasne-recpt1-server restart
curl 'http://<nasne>:8301/status?detail'     # terrestrial=idle satellite=idle のように、系統ごとに出る
```
元に戻すには、`/etc/default/nasne-recpt1` を消して `restart` します。

**Mirakurun**: 地デジ用(`GR`)と衛星用(`BS`・`CS`)の**2つのチューナー**として登録します。`python3 scripts/nasne_mirakurun_conf.py <nasne> --scan --dual` で、`tuners.yml` を2つのチューナー(`nasne-gr`・`nasne-sat`)で作れます。

**互換性**: `--dual-tuner` のときも、どれかの系統が使われている間は、従来のロック(`/tmp/nasne-recpt1.lock`)を共有ロックで持つので、`nasne-ledd`(REC LED)・`nasne-waked`(自動オフ)・`/status` は、従来どおり「どれかが使用中」を検知します。ファームが止まっていてドライバを再読み込みする場面では、もう一方の系統が使用中なら再読み込みしません(配信が切れるため)。

**確認したこと**(電波が無い環境。CECH-ZNR2J):
- 地デジの配信中に、衛星の選局(ロックしない)を繰り返しても、地デジの TS は乱れない(CC エラー 0、デコードエラー 0)。
- 地デジの配信中に、ファームウェアは、衛星入力の2本目の PSI ストリームと、2本目の B-CAS 用ストリームも開ける。
- 通常モード(既定)は、従来どおり直列(地デジの配信中の衛星の要求は、10秒待って 503)。

**他の人の実機での確認**(CUHJ-15004、公式 v2.57、Issue #12): 地デジ(NHK 総合)と BS(BS 朝日)を**同時に約60秒**受信して、それぞれ約115MB を取得。TS の同期エラー・TEI・不正な AFC は 0、映像・音声(BS は ARIB 字幕も)を ffprobe で認識。受信後は `terrestrial=idle satellite=idle` に戻る。
- **既知の問題**: 地デジと BS の受信を**ほぼ同時に開始**すると、まれに片方で `B-CAS ACTIVATE失敗`(`rv=2`)になり、その接続が HTTP 500、もう片方も途中で止まる(2秒ずらせば、毎回成功)。B-CAS カードは1枚で、ACTIVATE が系統をまたいで共有されることが関係していそうなので、**B-CAS ストリームを開いてから `OPEN_SECUREDTS` までを、プロセス間で直列にし、ACTIVATE の失敗は最大3回まで再試行する**ようにした(`/tmp/nasne-recpt1-bcas.lock`)。この修正で解消するかは、手元(電波なし)では確認できていないので、同時開始での結果を教えてください。
- **ほぼ同時に開始した場合の BS の立ち上がり**(monutetsu さん、CUHJ-15004、Issue #12): BS 単独は、最初の映像・音声のパケットまで約 0.7〜1.1 秒(10 回、平均約 0.9 秒)。地デジとほぼ同時に開始すると、**後に着いたほうが 1.6〜3.0 秒**に伸びる。10 回中 3 回は `B-CAS ACTIVATE失敗 rv=2` →再試行で成功(立ち上がりが約 4.5 秒)。原因は、先に始めたセッションの最初の ECM の処理で B-CAS カードが忙しい間に、後のセッションが ACTIVATE すると `rv=2`(カードがビジー)で失敗し、その**再試行の連射が、先着側の最初の ECM の応答まで遅らせて、両方の立ち上がりが遅れる**(共倒れ。monutetsu さんの解析)ため。ACTIVATE の待ち時間を 2→6 秒に延ばしても、10 回中 2 回は失敗が残った(待ち時間の不足ではなかった)。そこで、**先着側が最初の映像・音声を出す(=鍵を得る)まで B-CAS ロックを持ち続け(最大4秒)、再試行の間隔も広げた(500・1000・1500・2000ms)**。**欠落ではなく、立ち上がりの遅れ**で、再試行は成功する。通常の視聴・録画(4 秒で打ち切らない)では問題なし。開始を2秒ずらすと遅れは出ない。Mirakurun のチューナーの起動の待ち時間には、余裕を持たせるとよい。
- **同時の録画・視聴の確認**(monutetsu さん): EPGStation で地デジと BS を同時に**予約録画**(60秒、約121MB と約144MB)して、Mirakurun の監視で `drop=0`・エラー0、録画後は `terrestrial=idle satellite=idle`。**CS を視聴・復号している最中に地デジを同時に受信**しても、両方 drop 0(B-CAS 1枚で2サービスの同時復号を確認)。
- **Mirakurun の運用の Tip**: `server.yml` に **`jobMaxRunning: 1`** を設定しておくと、バックグラウンドの番組表の巡回(EPG)が、地デジと衛星で同時に走って、両方のチューナーを塞ぐのを防げる。
- **`2b0bcd8`(先着が最初の映像・音声を出すまで B-CAS ロックを保持+再試行の間隔を広げる)の再測定**(monutetsu さん、ほぼ同時 4 秒×10): `ACTIVATE失敗` **0 回**(以前は 2〜3 回)、共倒れ **0 回**、先着 10/10 で 0.6〜1.1 秒(平均約 0.9 秒)、後着は 8/10 が 4 秒以内(1.5〜3.0 秒。残り 2 回も ACTIVATE は一発で成功していて、4 秒の打ち切りの直前だっただけ)。後着は、先着のロックの保持(約 1.2 秒)のぶん、約 1 秒遅れる。
- **定常の視聴同士**(GR+CS): 完全に成功(それぞれ約 290 万・530 万パケット、drop=0)。
- **視聴中の裏の番組表(EPG)巡回に注意**: 片方の系統で視聴・録画している最中に、もう一方の系統で、Mirakurun が番組表のために次々とチャンネルを開閉すると、そのたびに B-CAS の ACTIVATE が走って、視聴中のストリームが一瞬カクつく(B-CAS の復号エンジンが共有されているため)ことがある。**番組表(EIT)は暗号化されていない**ので、番組表の取得には、**`?si=1`**(SI だけを出す。B-CAS を使わない)を付けるのが安全。Mirakurun のチューナーのコマンド(ラッパー)で、番組表の取得のジョブ(優先度 -1)のときだけ `&si=1` を付ける、または、視聴・録画中は番組表の巡回を待機する(monutetsu さんの方法)。
- **片方のセッションが終了するとき、動いている他方が止まる問題**(monutetsu さん、CECH-ZNR2J、実電波): CS の予約録画の最中に地デジを約 20 秒視聴して、地デジ側だけを切断すると、**その瞬間に CS の録画の出力が止まる**(`出力が止まった`、約 20 秒後)。カーネルのログに `Boxster, [txc_write_input_done] ... INPUT_DONE: Mips Failed` が出て、そのハンドルは、終了した側が閉じた **B-CAS の GENERIC ストリーム(ioctl 0x2f)**と一致。過去に `出力が止まった` が出た 3 回とも、別のセッションが GENERIC を閉じた直後だった。**対処**(`--dual-tuner` のとき): 終了するセッションは、クライアントには配信の終了を伝え、系統のロックも手放す(次の要求は受け付けられる)が、**ドライバの fd と GENERIC ストリームは持ったまま、ほかのセッションがなくなるまで待って(最大 4 時間)から、閉じる**(ログ: `generic stream: 他のセッションが動いているので、閉じるのを待つ` → `閉じる 待ち時間(ms)`)。**手元(電波なし)では、待機の動作(共有ロックを保持した状態での待機と、終了後に閉じること、クライアントが待たされないこと)だけを確認**。実際に他方の出力が止まらなくなるかは、報告者の環境の確認待ち。
  - **追記(クライアント切断で待機が効いていなかった不具合の修正)**: クライアントの切断(SIGPIPE)でも待機が飛ばされて即座に閉じていたため、切断を含めて待つように修正した(SIGINT/SIGTERM のときだけ待たずに終了)。また、Mirakurun の再試行などで待機中のプロセスが溜まらないよう、待機できるのは同時に 4 つまでにした。
- **B-CAS ACTIVATE の競合への対処後の、ほぼ同時の開始**(tanaka-su951 さん、15 回): ACTIVATE の失敗は 0 回(ロックの待ちは約 300〜550ms)。30 秒×5 回は毎回、映像・音声が取れた。
- **未確認**: 長時間(数時間)の安定性、Mirakurun/EPGStation 経由の同時の予約録画、2サービスの B-CAS 復号を長時間続けたときの挙動。**試した結果を教えてください**([Issue #12](https://github.com/mar1mo-41414/SonyNasne-debian/issues/12) か、検証レポート)。

### 局の組み合わせで、後から開いた系統の復号が始まらない(Issue #14)

> 層: 【CFW共通】(測定は【旧】CECH-ZNR2J。電波あり)

`--dual-tuner` で地デジと衛星を同時に使うとき、**特定の局の組み合わせだけ**、後から開いた系統の映像・音声が出ない。`OPEN_SECUREDTS` までは成功し、先の系統を閉じると 0.5〜1 秒で出始める。先の系統は正常。**組み合わせで決まり、毎回再現する**(以前「まれに」と書いていたのは誤り)。`--shared-generic` の有無に関係しない。

**検証済み**(地デジ 16 秒の途中で衛星 8 秒、またはその逆。映像の PID のパケット数で判定):

| 先 → 後 | 先 | 後 |
|---|---|---|
| 地デジ 25ch → BS15(NHK BS) | ○ | ×(0) |
| BS15 → 地デジ 25ch | ○ | ×(0) |
| 地デジ 24ch → BS15 | ○ | ○ |
| BS15 → 地デジ 24ch | ○ | ○ |
| 地デジ 27ch → BS15 | ○ | ○ |
| 地デジ 25ch → BS09 | ○ | ○ |

Issue #14(monutetsu さん)の報告: BS01(BS朝日)を先に開くと、地デジ 25・22・21・23・20ch は×、27・26・24ch は○。地デジ 25ch を先に開いて BS01 を後にすると、両方○。

**各局の PID**(PSI ストリームの元の PMT。`nasne-recpt1 -v` の表示。復号後の TS の PMT からは CA 記述子が除かれているので、そちらでは ECM は見えない):

| 局 | 映像 | 音声 | PCR | ECM |
|---|---|---|---|---|
| 地デジ 24ch | 0x111 | 0x112 | 0x100 | 0x060 |
| 地デジ 25ch | 0x111 | 0x112 | 0x100 | 0x101 |
| 地デジ 27ch | 0x100 | 0x110, 0x111 | 0x1ff | 0x901 |
| BS15(NHK BS) | 0x100 | 0x110 | 0x1ff | 0x060 |
| BS09・BS01 | 0x140 | 0x141 | 0x111 | 0x121 |

**検証済み(GENERIC を 1 本にした表)**: GENERIC を保持役の 1 本だけにして(`--hold-generic` / `--use-generic`。GENERIC の本数や開閉の影響を除くため)、地デジ 8 局 × BS 2 局 × 両方の順(32 通り)を試した。

| 地デジ | BS15(NHK BS)と | BS01(BS朝日)と |
|---|---|---|
| 24・26・27ch | ○(両方の順) | ○(両方の順) |
| 16(MX)・21・22・23・25ch | ×(両方の順) | ×(両方の順) |

- **○か×かは、地デジの局だけで決まる。** BS の局にも、開く順番にも、GENERIC の本数にもよらない。×のとき、後から開いた系統の復号ストリームは**何も出さない**(PAT・PMT も出ない)。先の系統を閉じると出始める。
- Issue #14 の「地デジ 25ch → BS01 は○」は、手元では再現しなかった(×)。以前の「地デジ 25ch → BS09 ○」は、GENERIC を系統ごとに開く方式での 1 回の観測で、GENERIC 1 本の表では BS09 は試していない。
- GENERIC 1 本の表では、32 回とも固まらなかった。系統ごとに GENERIC を開閉する方式で同じ表を取ったときは、途中でドライバが D 状態のまま固まり、**`reboot -f` でも再起動せず、電源の抜き差しが必要だった**(PWR が赤のまま)。

**原因ではないと確かめたもの**(同じ値で○と×の両方があるか、変えても結果が変わらない):

- TS の静的な性質: PMT・PCR・ECM・映像・音声の PID(例: 24ch と 21ch はこれらが同じで○と×)、ES の数、PAT のサービス数、TS の PID の数、PMT の長さ、ECM の見出し(全局 `group=0x1e`・`wk=0x01`)と間隔(約 98ms)、鍵の切り替わり、映像の形式(全局 1440×1080、MP@HL)、コピー制御の記述子、番組単位のアクセス制御(0xF6)の記述子、CAT。(**訂正**: ES 単位の CA・0xF6 記述子は、下のとおり原因に関係していた。)
- `OPEN_SECUREDTS` に渡す値(後の系統だけ変えた): ECM の PID、`output_port`、音声なし、出力バッファ・要求の大きさを半分、`xcode_key_index`・`ltsid`・`program_index` を 1。`program_number` は実際の番組と照合されるので、変えると良い局も×になる(原因とは別)。
- PSI ストリームの読み残し(後・先・両方で、空になるまで読んでも同じ)。
- ファームの dmesg への出力(○でも×でも `ReceiveStream rv=6` だけで、差が無い)。

**仕組み(実行中のファームのメモリを読んで確認。[docs/25 の 3.7](25_media_engine_firmware.md))**: 復号ストリームの PID の登録に使うチャンネルは 2 系統で合わせて 22 個。○の局の 1 本は 11 個使う。データ放送の ES は普通は全部で 1 チャンネルだが、**ES 単位の CA 記述子(ECM の PID が `0x1fff`)と 0xF6 が付いたデータ放送の ES は別のチャンネルになり**、その局は 12 個使う。×の地デジ局(16・21・22・23・25ch)はどれもこれに当たり、○の局(24・26・27ch)は当たらない(字幕にだけ付いているか、無い)。BS/CS には無い。11 + 12 = 23 > 22 で、後の系統の登録が足りなくなる。

**上限の正体**: 22 は、ファームの中のチャンネルのオブジェクトのプール(secondary)の個数で、ファームの定数。1 セッションは PSI ストリーム 1・復号ストリーム 7・B-CAS 側 3 の 11 個を使い、○の組でも 2 系統で 22/22 のちょうど満杯([docs/25 の 3.9](25_media_engine_firmware.md))。PSI ストリームは復号ストリームの入力なので閉じられない(閉じると何も出ない)。

**対策(検証済み、CECH-ZNR2J・CECH-ZNR1J 各 1 台、旧カーネル)**: GPL ソースからビルドしたドライバで、復号した直後のファームの secondary を 23 個にすると(`scripts/xc4drv_2629/`、`insmod xcode4drv.ko fw_secondary=23`)、**上の 32 通りがすべて○**になった(D 状態なし、CC エラー 0)。CECH-ZNR1J(公式ドライバ `xcode4drv.ko` の md5 が CECH-ZNR2J と同じ。SoC・メモリ・SPI の区画も同じ)では、×だった 25・16・21ch と BS の組み合わせ 6 通り(両方の順)で、後から開いた系統も映り、映像・音声の CC エラーは 0(`--shared-generic` あり)。さらに、**2 台を Mirakurun(4.2.1)に地デジ用・衛星用の 4 チューナーとして登録し、KonomiTV(0.14.1)で地デジ 2 本・BS 2 本を同時に視聴できた**(うち 1 台は ×だった 25ch + BS)。その間、2 台とも GENERIC の作り直し・出力の停止・`Mips Failed` は 0 件、負荷は約 2。詳細と未確認の点は [docs/25 の 3.10](25_media_engine_firmware.md)。

起動時にこのドライバを使う設定(旧カーネル。公式の `rc.xcode4` を、ドライバを選ぶ `scripts/watchdog/rc.xcode4-select` に置き換える。nasne-mcu-wd・nasne-mcu-hb・nasne-recpt1 の再読込は、どれも `rc.xcode4` を呼ぶ):

```bash
sh scripts/xc4drv_2629/build.sh                       # PC で → gpl_src/build/xcode4drv.ko
scp gpl_src/build/xcode4drv.ko root@$NASNE_IP:/usr/local/sbin/xcode4drv-gpl.ko
scp scripts/watchdog/rc.xcode4-select root@$NASNE_IP:/usr/local/sbin/rc.xcode4.new
# nasne 上
cd /usr/local/sbin && [ -f rc.xcode4.orig ] || cp -p rc.xcode4 rc.xcode4.orig
chmod 755 rc.xcode4.new && mv rc.xcode4.new rc.xcode4
printf 'XCODE4DRV_KO=/usr/local/sbin/xcode4drv-gpl.ko\nXCODE4DRV_ARGS="fw_secondary=23"\n' > /etc/default/xcode4drv
```

- 公式に戻すには `/etc/default/xcode4drv` を消して再起動する(公式の `xcode4drv.ko` は置き換えない)。
- GPL 版を読み込む途中で固まってウォッチドッグでリセットされた場合は、次の起動から自動で公式を使う(`/var/lib/nasne/xcode4drv.failed` ができる。消すと GPL 版に戻る)。
- 検証済み(1 台): 再起動で GPL 版が読み込まれ、ウォッチドッグの停止・PWR LED・受信サーバが動くこと、本番の受信サーバ(8301)経由で BS15 と地デジ 25ch の同時受信(CC エラー 0)。

**ホスト側の設定では直らなかった**: `program_mode_flags`(`DISABLE_DATA_PIDS`)、`remux_flags`(`REMUX_PARTIAL_TS_NO_DSMCC`)、`component_tag_selection` などをホストから変えても、データ放送の ES は登録され、×のままだった([docs/25 の 3.8](25_media_engine_firmware.md))。

**回避策(`--giveup-no-av <ms>`)**: `--dual-tuner` のとき、もう一方の系統が使用中で、指定した時間までに最初の映像・音声が来なければ、そのセッションを打ち切る(ログ「同時受信で映像・音声が出ないため打ち切る(Issue #14)」)。映らないまま待たされたり、固まったりするのを避け、チューナーを早く解放する。録画ソフトが別のチューナーへ移れるかはソフトしだい(Mirakurun での動作は未確認)。

```bash
echo NASNE_RECPT1_GIVEUP_MS=6000 >> /etc/default/nasne-recpt1 && /etc/init.d/nasne-recpt1-server restart
```

- 検証済み: GENERIC 1 本で、BS15 の受信中に地デジ 25ch(×)を `--giveup-no-av 4000`・`6000` で開くと、打ち切られた(ログで確認。打ち切りまでの時間は測っていない)。地デジ 24ch(○)を `6000` で開いたときは打ち切られず、最後まで受信できた。
- 通常の立ち上がりは 0.6〜1.8 秒なので、4〜6 秒なら正常な受信を打ち切ることはない見込み。

## 仕組み

詳細: [docs/12](12_ts_and_bcas_decrypt.md)。要約:

1. 復調IC/チューナーをI2Cで選局([docs/08](08_tuner_i2c.md))。
2. TSパススルーストリーム(PSI)で全PIDを受け、PAT/PMTからサービスの映像・音声・PCR・ECMのPIDを得る。
3. B-CASストリームを開いて活性化し、`OPEN_SECUREDTS`(純正と同じ設定で、映像はパススルー=変換なし)を開く。ファームがB-CASで復号し、TS化して出力する。
4. 出力(192バイトのタイムスタンプ付きTS)の先頭4バイトを外す。ファームが作り直すPAT(選んだ1サービス分だけ)は捨てて、PSIストリームの**元のPAT**(NITのPIDを含む。録画ソフトがNITの場所を知るために必要)と、SI(PID 0x10〜0x14、0x23、0x24、0x26〜0x28)を混ぜて出力する。

### 選局から最初の映像までの時間の内訳

> 層: 【CFW共通】(測定は【旧】2.6.29 + Debian 7。`nasne-recpt1` は同じなので【新】でも同じ見込みだが、未測定)

`--listen` のときのログ(`/var/log/nasne-recpt1.log`)の節目の差から求めた。単位は ms。
- B-CAS の 3 行(GENERIC を開く・ACTIVATE・ACTIVATED の待ち)以外: 過去のログの中央値(地デジ 2,453 回・衛星 1,078 回。CECH-ZNR2J と CECH-ZNR1J の各 1 台)。
- B-CAS の 3 行: ログを細かくした試作での測定(CECH-ZNR2J の 1 台、地デジ 1 局、5〜10 回)。

| 段階 | ログの区間 | 地デジ | 衛星 | 備考 |
|---|---|---|---|---|
| チューナーの確保 | `session start` → `tuner acquired` | 151 | 65 | 直前のセッションの終了から 300ms 以内なら、その残りを待つ(p90 が約 440ms になるのはこれ) |
| 選局のロック+PSI ストリーム | `tuner acquired` → `psi stream opened` | 294 | 286 | ロックの確認は 100ms(衛星 50ms)おき |
| PAT/PMT の収集 | → `discover sel` | 約 250〜300 | 約 145 | `?sid=` を付けると、その PMT が揃った時点で終わる |
| B-CAS の GENERIC を開く(0x2e) | `open_streams begin` → `bcas generic opened` | 1 | | |
| **B-CAS の ACTIVATE(0x13)** | → `bcas activate sent` | **419** | | **毎回ほぼ一定**(417〜419)。続けて開いても毎回かかる |
| ACTIVATED イベントの待ち(0x14) | → `bcas activated event tries` | 80 | | 1 回目で取れる。待たずに進めても復号は正常だった(5 回)が、短縮は 80ms だけなので採用しない |
| OPEN_SECUREDTS | → `open_streams SECUREDTS rv` | 42 | 42 | |
| 最初の映像・音声のパケット | `streaming begin` → `first A/V packet` | 約 920 | 約 1,010 | ECM の到着とカードの応答。600〜1,800 とばらつく。コードからは変えられない |
| **合計** | | **約 2,250** | **約 2,150** | |

- ACTIVATE の 419ms は、ファーム側の処理(カードの初期化と推測。ドライバのソースでは未確認)。短縮するなら、ACTIVATE の回数を減らす(GENERIC ストリームを閉じずに次のセッションで使い回す)しかない。

#### GENERIC ストリームの使い回し(試験)

> 層: 【CFW共通】(測定は【旧】CECH-ZNR2J 1 台、地デジのみ)

ACTIVATE 済みの GENERIC ストリームを閉じずに、復号ストリーム(OPEN_SECUREDTS)と PSI ストリームだけを閉じて、選局からやり直す試験用のモードをコマンドラインに足した(本番の `--listen` には効かない):

```bash
# 1 回目は通常どおり、その後 4 回は GENERIC を使い回す(各 6 秒)
nasne-recpt1 --reuse-test 4 --sid 0x<sid> <ch> 6 /tmp/x.ts
# 2 回目以降、別のチャンネルと交互にする(同じ帯域どうしに限る)
nasne-recpt1 --reuse-test 4 --sid 0x<sid> --reuse-alt <ch2> --reuse-alt-sid 0x<sid2> <ch> 6 /tmp/x.ts
```

**検証済み**(地デジ 2 局、各 5 回): 使い回した回は、`open_streams begin` → `SECUREDTS` が **542ms → 42ms**(ACTIVATE とイベント待ちが無くなる)。**別の局に替えても**鍵が取れて復号された(映像・音声のスクランブル 0、TEI 0)。最初の映像・音声までの時間(約 760〜1,060ms)は通常と同じ。警告・エラーなし、終了後に D 状態のプロセスなし。

**別のプロセスからの利用**(`--hold-generic` が GENERIC を開いて ACTIVATE し、ハンドルを表示して SIGTERM まで持つ。`--use-generic <h0>,<h1>` はそのハンドルで受信し、自分では ACTIVATE も GENERIC の開閉もしない):

```bash
nasne-recpt1 --hold-generic 2>/tmp/hold.log &          # → "generic c22bbb78,00000000"
nasne-recpt1 --use-generic c22bbb78,00000000 --sid 0x<sid> <ch> 6 /tmp/x.ts
```

- **検証済み**: 別のプロセス(別の fd)から、ACTIVATE 済みのハンドルで復号できた(地デジ 2 局。最初の映像まで 853・980ms、スクランブル 0)。
- **検証済み**: その間に**別のセッションが自分の GENERIC を開いて ACTIVATE し、閉じる**と、保持している GENERIC では**復号されなくなった**(OPEN_SECUREDTS は成功するが、映像・音声のパケットが 1 つも出ない。2 回中 2 回)。
- **検証済み(原因の切り分け)**: 2 つ目の GENERIC を開いて **ACTIVATE しても、1 つ目のハンドルでの復号は続く**(2 つ目のハンドルでも復号できる)。**2 つ目の GENERIC を閉じた(0x2f)とたんに、1 つ目でも復号されなくなる**。つまり、**どれか 1 つの GENERIC を閉じると、カードの活性化が全部の GENERIC で失われる**。`--dual-tuner` の「片方が終わると他方が止まる」(上の Issue #12 の項)と同じ現象とみられる。
- 保持役が GENERIC を閉じても、別の GENERIC で受信中の本番のセッションは止まらなかった(約 10 秒の観察。`Mips Failed` なし)。
- したがって本番に入れるなら、**GENERIC を nasne 全体で 1 つにして全セッションで共有する**(スキャンなども含めて、ほかに GENERIC を開かせない)作りが要る。活性化が失われたとき(数秒たっても映像・音声が出ない)に ACTIVATE し直す仕組みも要る。

- **検証済み(衛星)**: `--reuse-test` で BS 2 局(BS15_1・BS01_0)を交互に 4 回。使い回した 3 回とも ACTIVATE なしで復号(スクランブル 0、最初の映像まで 607〜884ms)。
- **検証済み(地デジと BS で 1 つの GENERIC を共有)**: 1 つの保持役のハンドルで、地デジ(20 秒)と BS(8 秒)を `--dual-tuner` で同時に受信し、両方とも復号できた(スクランブル 0、CC エラー 0、TEI 0)。**BS を先に終えても、地デジは最後まで止まらなかった**(BS 側は GENERIC を閉じないため)。

GENERIC を 1 つにして閉じずに共有する作りにすれば、①選局が約 500ms 速くなる ②片方の終了で他方が止まる問題 ③同時開始の ACTIVATE の取り合い(`rv=2`)が、まとめて無くなる見込み(②③は推測。本番の作りでの確認が要る)。

#### `--shared-generic`(試験的)

> 層: 【CFW共通】(測定は【旧】CECH-ZNR2J 1 台。地デジ 2 局と BS 2 局)

> **2026-11-04 に実運用で問題が出て、いったん止めた**(地デジ 25ch の視聴中に NHK BS を開くと映らず、回復の仕組みが「共有の GENERIC が壊れた」と誤って判断して作り直しを続けた)。原因は Issue #14(局の組み合わせ)で、**GPL 版ドライバの `fw_secondary=23` で直した**(上)。あわせて**回復の判断を直した**(2026-11-05): 作り直す前に、もう一方の系統が同じ GENERIC で今映っているかを確かめ、映っていれば作り直さない(下)。

`--listen` に付けると、GENERIC を nasne 全体で 1 つにして、閉じずに全セッションで共有する。既定は従来どおり(セッションごとに GENERIC を開いて ACTIVATE し、閉じる)。

```bash
nasne-recpt1 --listen 8301 --shared-generic                # 2 系統なら --dual-tuner も
# サービス(scripts/watchdog/nasne-recpt1-server)で有効にする
echo NASNE_RECPT1_SHARED=1 >> /etc/default/nasne-recpt1 && /etc/init.d/nasne-recpt1-server restart
```

- 親が、起動時(と各接続の前)に自分の fd で GENERIC を開いて ACTIVATE し、fd ごと持ち続ける。ハンドル・親の PID・世代を `/tmp/nasne-recpt1-generic` に書く。
- 子は親の fd を閉じて(ドライバを入れ直せるように)、そのファイルのハンドルで復号ストリームだけを開く。ACTIVATE も GENERIC の開閉もしない。
- **共有のサーバが動いていれば、`--shared-generic` を付けていない起動(コマンドライン、別ポートのサーバ)も共有のハンドルを使う**(自分の GENERIC を閉じて、共有のものを壊さないため)。共有のサーバが無いときは従来どおり。
- **回復**: 3 秒たっても映像・音声が出なければ(だれかが GENERIC を閉じて活性化が失われた)、子が `/tmp/nasne-recpt1-generic.bad` を作って親に SIGUSR1 を送る。親は GENERIC を作り直し(閉じて開き直して ACTIVATE)、子は新しいハンドルで復号ストリームを開き直す。ハンドルの値は使い回されることがあるので、世代で見分ける。ファームが止まっていれば、親は fd を閉じて、子にドライバを入れ直させる。

**検証済み**(電波あり、`--dual-tuner --shared-generic`、別ポートの試作。本番は止めずに Mirakurun 側で無効にして実施):

| 試験 | 結果 |
|---|---|
| 続けて選局(地デジ 2 局・BS 2 局、6 回) | B-CAS の処理は毎回 42ms(ACTIVATE は親の起動時の 1 回だけ)。最初の映像まで 707〜1,128ms |
| 地デジ 20 秒の受信中に BS 8 秒 | 両方とも復号。BS の終了後も地デジは最後まで止まらない |
| 別のプロセスに GENERIC を開閉させて活性化を壊してから選局 | 3 秒後に作り直しを頼み、復号ストリームを開き直して回復(最初の映像まで約 4.9 秒)。新しいハンドルは古いものと同じ値だった |
| 受信中のクライアント切断(SIGPIPE)・SIGTERM | どちらの後も、次の選局は 42ms のまま(共有の GENERIC は壊れない) |

受信した TS 12 本すべてで、スクランブル 0・CC エラー 0・TEI 0。カーネルの `Mips Failed` 0。

**回復の判断(2026-11-05)**: 映像・音声が流れている間、各セッションは 1 秒おきに「時刻と共有の GENERIC の世代」を `/tmp/nasne-recpt1-av-T`(衛星は `-S`)に書く。3 秒たっても映らないセッションは、もう一方の系統が同じ世代で 2 秒以内に映っていれば、GENERIC は壊れていない(電波・契約・局の組み合わせなど別の原因)と判断し、作り直さない(ログ「もう一方の系統は同じ GENERIC で映っているので、作り直さない」)。作り直すと GENERIC を閉じるので、映っている他方まで止めてしまうため。

**検証済み**(2026-11-05、CECH-ZNR2J 1 台、旧カーネル、GPL 版ドライバ `fw_secondary=23`、別ポートの試作のあと本番):

| 試験 | 結果 |
|---|---|
| 続けて選局(地デジ 5 局・BS 2 局、8 回) | B-CAS の処理は毎回 42〜43ms。選局から最初の映像まで 1,209〜2,491ms(中央値 約 1,750ms。共有しない場合は約 2,250ms) |
| 地デジ 24ch を受信中に、契約していない CS(CS2 の 0x128)を開く | CS は映らず、「作り直さない」と判断。地デジは 20 秒最後まで止まらない(CC エラー 0) |
| 別のプロセスに GENERIC を開閉させて活性化を壊してから選局(他方は未使用) | 作り直しを頼んで回復(最初の映像まで約 4.6 秒) |
| 受信中のクライアント切断(SIGPIPE)のあと選局 | B-CAS の処理は 43ms のまま |
| 本番(8301)・Mirakurun 経由で地デジ 25ch と NHK BS の同時受信 | 両方とも CC の不連続 0・スクランブル 0。最初の映像まで 598・832ms |

- Mirakurun が衛星のチューナーで番組表を取得している間は、視聴の要求に 503 を返した(優先度を上げても譲らず、`isAvailable: false`。数分で取得が終わると空いた)。nasne 側は正常に受信していた。Mirakurun の動きで、`--shared-generic` とは関係しないとみられる(未確認)。

**未確認**: ①何時間も開いたままにしたあとも鍵が取れるか(長時間の運用) ②実運用(Mirakurun/EPGStation からの頻繁な開閉、番組表の巡回)での安定性 ③ドライバの入れ直し(ファームの停止)からの回復の実際の動作 ④【新】6.12 での動作。

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `ロックしなかった` | アンテナ・チャンネル番号を確認。`--scan` でロックするチャンネルを調べる(チャンネル番号は物理チャンネル。共同受信設備では再送信のチャンネルが一般的な配置と異なることがある) |
| `チューナー使用中` / HTTP 503 | 別のセッションが動いている(**最大10秒は待ってから**503を返す)。`/status` で確認 |
| 画が出ない・スクランブルが残る | B-CASカードが挿さっているか、活性化できているか。`-v` でPIDを確認 |
| `/status` が `busy` のまま戻らない。状態ページに「チューナーのプロセスが固まっている」と出る | `nasne-recpt1` のプロセスが D 状態(ドライバの中で戻らない)になっている。**D 状態は正常な受信中にも現れる**ので、目印は「D のまま CPU 時間(`/proc/<pid>/stat` の utime+stime)が進まない」こと。**電源の入れ直しでしか復旧しない**(`reboot` は効く)。複数クライアントの頻繁な開閉で、まれに起きる |
| nasne全体が応答しない(pingは通るがssh不可) | ストリームを開いたまま強制終了した場合などに起こり得る。電源ケーブルを抜き差しする(`kill -9` を避ける。通常の終了(SIGTERM・接続切断)では起こらない) |
