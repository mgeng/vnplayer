---
name: game-export
description: novela で完成した小説1作品（プレーンテキスト export）をノベルゲーム（VN）の台本バンドルへ変換する。シーン分割・話者割当・背景/立ち絵の演出指定を行い、画像は SDXL 用プロンプトとして書き出す。実画像生成と再生はこの vnplayer repo が担う。game, ノベルゲーム, vn, 台本, 変換, ゲーム化
allowed-tools: Bash, Read, Edit, Write
---

novela の小説を **1作品ずつ** ノベルゲーム台本バンドルへ変換するスキル（vnplayer repo 所属）。
バンドル仕様は [SCHEMA.md](SCHEMA.md) が唯一の取り決め。

**疎結合の前提**: このスキルは `novels.db` を**一切読まない**。novela が
`novels_db.py export <work_id>` で吐く **プレーンテキスト成果物**（`manuscript/ep_*.md` ＋
`metadata/kdp_metadata.json` ＋ `config.json`）だけを入力に取る。DB スキーマは novela 内部に閉じ、
VN 側はファイル契約にのみ依存する。

設計の前提:
- novela = 小説生成 + プレーンテキスト export。VN 化（シナリオ化・画像・再生・配布）は vnplayer。
- 画像は **SDXL（Illustrious XL / mangen）** 前提。このスキルは `prompts/*.txt` を書き、
  実生成は `tools/game_sdxl.py` が担う（VM コスト規律は [CLAUDE.md](../../../CLAUDE.md) 参照）。
- バンドルは `work/game/<work_id>/`（git-ignore のスクラッチ）に置く。勝手にコミットしない。

## 手順

### 0. novela 側でプレーンテキストを export（前提）

```bash
cd /path/to/novela
python scripts/novels_db.py export <work_id>
# → novela 側 work/manuscript/ep_*.md, work/metadata/kdp_metadata.json, work/config.json
```

### 1. 下ごしらえ（機械処理・DB 非依存）

```bash
cd /path/to/vnplayer
python3 tools/game_export.py <work_id> --input /path/to/novela/work
# --input 既定は $NOVELA_EXPORT または ../novela/work
# → work/game/<work_id>/ に meta.json / script.json / cast.json / prompts/ / assets/
```

スキャフォルダがやること:
- 各 `ep_*.md` → 1 scene（先頭の日記見出しを `heading` に）。タイトルページ等の前付け話は自動スキップ。
- 本文を行へ分解し、地の文=`speaker:null` / 行頭が `「『` のセリフ=`speaker:"?"` に素朴分類。
- `meta.json` を `kdp_metadata.json`（＋ `config.json` フォールバック）から起こす。
- **カバーは出力しない**（DB 非依存化のため）。タイトル画面のカバーは VN 側で用意する
  （`tools/game_sdxl.py` で生成 or novela 配布カバーを `assets/cover.jpg` へ手動コピー）。

### 2. 台本の仕上げ（Claude がオーサリング）— ここが本体

`work/game/<work_id>/script.json` を **Read して文脈を読み**、[SCHEMA.md](SCHEMA.md) に沿って詰める:

1. **話者割当**: `speaker:"?"` を全て解消。地の文の文脈（「歩美は……言った」等）で話者を確定し、
   cast.json の `name` に一致させる。一人称の語り手のセリフも忘れず割当。
2. **cast.json を起こす**: 登場人物を列挙し `id`/`role`/`expressions`/`desc_for_sd`（立ち絵プロンプト素体）を記入。
   入力に `characters/*.json` があれば流用、無ければ本文から起こす。
3. **背景 `bg`**: scene ごとに背景IDを決める（場面が変わる長い scene は scene を分割してよい）。
4. **立ち絵 `sprite`**: 主要セリフに表情付き立ち絵IDを当てる（崩れ・絶頂など緩急を表情で出す）。
5. **選択肢（任意）**: NTR/マゾ等の分岐点に `choice` を挿し、分岐先 scene を `scenes` に足す。
   まずは分岐なしの一本道でも可（最小検証を優先）。
6. **横書き対応**: 横組み表示なので、必要なら `tools/kanji_num.py` で日付/話数/カウンタの漢数字→アラビア変換
   （慣用語は保持する安全版）。

仕上げの際は官能 craft 方針（概念でなく身体の具体、緩急、崩れ）を踏襲。
台本ではテンポを意識し、長い地の文は適度に行を分けて「送り」のリズムを作る。

### 3. SDプロンプト書き出し → 画像生成

`prompts/` に SCHEMA.md の書式で `bg_*.txt` / `char_*_<expr>.txt` / `cg_*.txt` を作る。
- 本体は**英語**、`anime style` を明示、`negative` に `text, watermark, lowres, bad anatomy` 等。
- アダルトCGは作品のキー場面に絞って `cg_*` を用意（全場面に作らない）。

実画像は `tools/game_sdxl.py <work_id>` で生成（**GPU VM コスト規律は CLAUDE.md 必読**：
prep を全部済ませてから vm-up→一括生成→即 vm-down）。

### 4. 検証

```bash
python3 tools/game_export.py --help     # 仕様確認
# script.json の不変条件チェック（話者の "?" 残り・goto の実在）
python3 - <<'PY'
import json
d=json.load(open("work/game/<work_id>/script.json"))
ids={s["id"] for s in d["scenes"]}
assert d["start"] in ids, "start が不正"
q=[l for s in d["scenes"] for l in s["lines"] if l.get("speaker")=="?"]
g=[(l) for s in d["scenes"] for l in s["lines"] if l.get("type")=="choice" for o in l["options"] if o["goto"] not in ids]
print("未割当セリフ:",len(q)," 不正goto:",len(g))
PY
```

未割当セリフ 0 / 不正goto 0 になれば台本は完成。あとは `python3 -m http.server` で再生確認し、
`python3 build.py work/game/<work_id>` で配布バンドル化する
（プレースホルダ画像でも通しプレイ可能 = SCHEMA.md の不変条件3）。

## やらないこと

- `novels.db` を読む / 書く。入力は novela の export 成果物（プレーンテキスト）だけ。
- カバー画像の DB 取得。VN 側で用意する。
