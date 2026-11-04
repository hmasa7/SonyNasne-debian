# 25. メディアエンジンのファーム(ARC)の解析

> **層**: 【固定】 メディアエンジン(SoC 内の ARC コア)で動くファームと、ドライバ(`xcode4drv`)との取り決め。公式・旧・新のどれも、同じファームを使います。

`xcode4drv.ko` は、読み込み時にメディアエンジンへファームを送って起動します([docs/07](07_driver_ioctl_bcas.md))。地デジ・BS/CS の B-CAS 復号や、TS の分離・多重化は、このファームの中で行われ、Linux 側からは ioctl で指示するだけです。2 系統の同時受信で局の組み合わせによって後発の復号が始まらない問題([Issue #14](https://github.com/mar1mo-41414/SonyNasne-debian/issues/14)、[docs/11](11_tv_streaming.md))を調べるために、ファームを取り出して逆アセンブルしました。この文書は、その手順と、分かったことの記録です。

**ファームは Sony のバイナリなので、リポジトリには入れません。** 取り出したものは `gpl_src/`(`.gitignore` 済み)に置きます。

## 1. ファームの入手と形式

SIE が GPL で公開しているドライバのソース(`AVDriver7GSP47.zip`。[scripts/fetch_gpl_sources.sh](../scripts/fetch_gpl_sources.sh) が取得する)の中の `XC4_AVDriver_Src_20140709.tar.bz2` に、ファームが C の配列として入っています(`Kernel_Src/kdrv/drv/`)。

| ファイル | 中身 |
|---|---|
| `firmware.c` | メインの ARC のファーム(**平文**、約 6.2MB) |
| `fmsecond.c` | 2 つ目の ARC のファーム(平文、約 2.8MB。音声などの処理) |
| `fmencryptedoutput.c`・`fmencryptedoutputsecond.c` | 上の 2 つの暗号化版 |
| `kernel_image.c` | 汎用の Linux カーネルの uImage(「Mips Linux Kernel」)。今回の解析とは無関係 |

- 配布されている `xcode4drv.ko` に実際に入っているのは**暗号化版**(`fwoutput_data` 0x5eda90 バイト、`fwoutput_second_data` 0x2a4b60 バイト)で、`firmware_data` は 1 バイトの空の配列です。復号はチップの側で行われるとみられます。
- 平文の版(0x5eda84 バイト、0x2a4b5c バイト)は、暗号化版より 12 バイト・4 バイト短いだけなので、**同じファームの平文**と考えています(暗号化版を復号して確かめたわけではありません)。
- nasne の実機の `xcode4drv.ko` は、公開版と md5 が違います(公式ファームに入っている版)。ファームの版が完全に同じかは確認していません。

## 2. 逆アセンブルの手順

ARC700(ARCompact、リトルエンディアン)です。先頭は割り込みベクタ(`j <アドレス>` の並び)です。

```bash
sudo apt install binutils-arc-linux-gnu          # ARC 用の objdump・as(ホストに入れる)
sh scripts/fetch_gpl_sources.sh                  # gpl_src/ に AVDriver7GSP47.zip(sha256 を確認)
# zip と tar.bz2 を展開(unzip・bzip2 が無ければ Python の zipfile・tarfile で)
mkdir -p gpl_src/fw && cd gpl_src/fw
python3 -I ../../scripts/arcfw/extract_fw.py <展開先>/Kernel_Src/kdrv/drv .
sh ../../scripts/arcfw/mkelf.sh firmware.bin fw.o
python3 -I ../../scripts/arcfw/dis.py 0x24a7e4 0x24b560     # 範囲はファイル内のオフセット。表示は実アドレス
python3 -I ../../scripts/arcfw/fieldmap.py                   # cmd_open_stream の欄の名前とオフセットの対応表
```

- **生のバイナリのままでは objdump が命令として読まない**(`-b binary -m ARC700` でも `.word` になる)。アセンブラの `.incbin` で ELF に包むと読める(`mkelf.sh`)。
- **ファームは実アドレス `0x100000` に置かれる。** ファーム内の文字列を指す即値(limm)を集め、「即値 − 文字列の位置」が一致する値を数えて決めた(復号ストリーム関係の 5 つの文字列がすべて `0x100000` で一致)。ベクタの飛び先(`0x113c20` など)とも合う。
- ARC の 32 ビット命令と即値(limm)は、16 ビットずつ上位から並ぶ(各 16 ビットはリトルエンディアン)。
- `0x690000` 台はファーム自身のデータ領域(RAM)で、レジスタではない(ファームの大きさから `0x100000`〜`0x6eda84` がファームの範囲)。

## 3. 分かったこと

### 3.1 ストリームを開くコマンドの欄(`cmd_open_stream`)

ファームには、受け取ったコマンドの欄を名前付きで全部表示するデバッグ関数(文字列「`*********pcmd_open_stream************`」)があります。その中で「表示する名前」と「読み出すオフセット」が並んでいるので、`fieldmap.py` で欄の名前とオフセットの対応表(195 個)が作れます。復号ストリーム関係の一部:

| ファームのコマンド内のオフセット | 欄 |
|---|---|
| `+0x90` | `src` |
| `+0x87c` / `+0x880` | `ecm_pid` / `emm_pid` |
| `+0x884` | `xcode_key_index` |
| `+0x888` | `input_encrypt_mode`(B-CAS は 1) |
| `+0x88c` | `output_encrypt_mode` |
| `+0x890` / `+0x894` | `program_index` / `ltsid` |
| `+0x898` | `program_number` |
| `+0x89c` | `ca_pmt_command_pid` |
| `+0x8a0` | `securedts_mode` |

ユーザー側の ioctl のバッファ(`OPEN_SECUREDTS`)での位置は、[docs/12](12_ts_and_bcas_decrypt.md) の表を参照。並びは同じです。

### 3.2 復号ストリームを開く処理

- 復号ストリームは PSI ストリームを入力にするので、ファーム側の処理は `strm_open_host_data_passthru`(実アドレス `0x34a7e4`)と考えて読んだ。**ただし、実行中のメモリでは、この関数と `strm_open_host`(`0x340838`)の入口で数える回数の変数(`0x69a934`・`0x69a930`)が 0 のままだった**(3.6)。この関数が実際には使われていないのか、変数が外から見えないコア専用のメモリにあるのかは、決められていない。以下の記述は、この関数が使われる場合のもの。
- この中に、DRM の制御部(`drmctrl`)のインスタンスにストリームを結び付ける処理(`0x261b7c`)がある。インスタンスは **6 個の固定の表**(`0x69735c`、16 バイト × 6)に入っていて、空きが無いとエラー 353「`drmctrl_open max num`」になる(`0x261520`)。
- **ただし、この結び付けを使うのは `output_encrypt_mode` が 3、または `input_encrypt_mode` が 4(暗号化・復号の DRM)のときだけ**で、B-CAS(`input_encrypt_mode` = 1、`output_encrypt_mode` = 0。`nasne-recpt1` も公式も同じ)はここを通らない。したがって、**この 6 個の表は B-CAS の 2 系統同時受信には関係しない**(一度そう推測したが、誤りだった)。
- 結び付けに失敗しても、ファームはデバッグ表示(「`drmctrl_open_secured_strm ret:%x`」)をするだけで、**ストリームを開くこと自体は成功させる**。「開くのは成功(`rv=1`)するのに、何も出力されない」という Issue #14 の症状と同じ形の作り。
- TS の分離(tsdemux)は、ストリームごとに別のタスクとして起動される(文字列「`(pso->tsdemux_task_which_mips == VK_SYSTEM_ARC || pso->tsdemux_task_which_mips == VK_AUDIO_ARC)? uist_tsdemux_fsm : sg.uist_tsdemux_fsm`」は、タスクを作るときの名前)。タスクの入口は実行時に決まる表から取る。

### 3.3 B-CAS カード

- ドライバはファームに `XC3ControlBCAS = 1` を渡していて、**B-CAS カードはファームが直接制御する**(ドライバの `sc.c` は、ホストから任意のカード命令を送るための別の経路)。ECM をカードに渡して鍵を得るやり取りは、Linux 側からは見えない。
- メインのファームには、カードを扱う文字列が無い。
- **B-CAS の命令の雛形**(CLA `0x90`、INS が初期化 `0x30`・ECM `0x34`・EMM `0x36`)は、**どちらの ARC のファームにも、実機の `xcode4drv.ko` にも無い**。見つかったのは、nasne では使われていない `kernel_image`(ViXS の参考実装の Linux カーネル。実機の ko でも `kernel_image_data` は 1 バイトの空)の中だけ。
- **どちらの ARC のファームも、チップのカード制御部(SCC、`XC_SCC0_*`)のレジスタを、定数のアドレスでは使っていない**(3.6 のベースアドレスで探した)。カードの処理がどこにあるかは未解明。

### 3.4 鍵の置き場(KEYSTORE)

- ファームには鍵の置き場があり、ホストからの命令 `CMD2_SDEV_RESERVE_KEYSTORE_SLOT`(0x114)・`CMD2_SDEV_SET_KEYSTORE_KEY`(0x113)がある。ヘッダでは、置き場の番号の範囲は 0〜127(各 64 ビット)。
- 0x114 は、ストリームのハンドル(カーネル内のポインタ)を**検証せずに参照する**。自分で開いた復号ストリームのハンドルで試したが、スロット数(1・2・4)、番号のヒント(0・64・0xffffffff)、ハンドルの種類(復号・PSI・GENERIC)の 27 通りすべてで受け付けられなかった(`rv=2`。結果の番号も書き戻されない)。B-CAS の復号ストリームの置き場を、ホストから数える方法は見つかっていない。
- `OPEN_SECUREDTS` の応答の `numOfDecrypter`(割り当てた復号器の数)は、Linux 版のドライバではユーザー側に書き戻されない(`#ifdef W2K` の中だけ)。

### 3.5 ハードウェア

- 汎用の暗号 DMA(DES・AES など。`XC_DMA_DIRECT_*`)は A・B の 2 チャンネル。鍵の置き場の番号を指定するレジスタ(`XC_DMA_DIRECT_CRYPT_INDICES_A/B`)がある。B-CAS(MULTI2)の解除にこれを使っているかは未確認。
- TS の分離部(TSD)のチャンネルは 16 本(`XC_TSD_CHANNEL_CTRL`)。
- **ARC から見たレジスタ群のベースアドレスは `0xf0010000`**(ファームの即値 `0xf001a890`〜`0xf001a898` が `XC_PROC2_DMA_DCCM`・`_FB`・`_CONFIG`(オフセット `0xa890`〜)と一致)。ファームが使う区画の多く(`+0x1200`〜`+0x1f00`、`+0x7000`〜`+0x7700`、`+0x8000`〜`+0x8300`、`+0xc500` など)は `viper.h` に定義が無い。
- `viper.h` に `XC_PROC2_DMA_DCCM` があるので、各 ARC コアは専用のデータ用メモリ(DCCM)を持つとみられる。

### 3.6 実行中のメモリを Linux から読む(読むだけ)

- **メディアエンジンのメモリは、物理アドレスとファームのアドレスが同じ(恒等写像)**。実機の `/dev/mem` の物理アドレス `0x3debb4` に、ファームの文字列「`Error - drmctrl_open max num %d`」がそのまま見える(docs/01 のとおり、物理 `0x00000000`〜`0x0fffffff` はメディアエンジンのメモリで、Linux は使っていない)。

```bash
dd if=/dev/mem bs=1 skip=$((0x3debb4)) count=32 2>/dev/null | od -c          # ファームの文字列が見える
dd if=/dev/mem bs=65536 skip=16 count=96 2>/dev/null > me_code.bin             # 0x100000〜 を読む
```

- **実機で動いているファームのコードは、GPL 版の `firmware.c` と同じ**(`0x110000`〜`0x4d0000` あたりは 4KB 単位で完全に一致。違うのは先頭の一部と、実行中に書き換わるデータ領域)。逆アセンブルの結果は、そのまま実機に当てはまる。
- データ領域も読める。BS15 を受信中に 2 本目を開くと、`0x690000` 台で 6,593 語が変わった(バッファなど)。
- **ただし、ファームの変数の一部は 0 のまま**で、外の DRAM からは見えていないとみられる(ストリームを開く処理の回数・エラーの番号の変数。各コアの DCCM に置かれている可能性。推測)。
- 読むだけなら、実機への影響は見られなかった(D 状態・`Mips Failed` なし)。**書き込みはしないこと**(ファームを壊す。書き込みの試験はしていない)。MIPS 側のキャッシュを通して読むので、古い値が見える可能性はある(AGENTS.md §9 のキャッシュの注意)。

## 4. 未解明

- Issue #14 の、局の組み合わせで後発の復号が始まらない原因。B-CAS の復号の本体(ECM をカードに渡し、返った鍵を復号器に入れる処理)は、ストリームを開く処理の中には無く、tsdemux のタスク(入口は実行時に決まる)か、2 つ目のファームの中にあるとみられる。ここを追うのが次の手順。
