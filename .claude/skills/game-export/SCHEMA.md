# ゲーム台本バンドル仕様 `novela-game/1`

novela が書き出し、別repoのVNプレイヤー（軽量自作Webエンジン）が読む**唯一の取り決め**。
エンジンとバンドルはこのスキーマだけで結合する。互換を壊す変更は `schema` のバージョンを上げる。

## ディレクトリ構成

```
game/<work_id>/
  meta.json        # 作品メタ（タイトル画面・奥付用）
  script.json      # 本体。scene と line の列
  cast.json        # 話者→立ち絵IDと表情の対応
  prompts/         # Stable Diffusion 用プロンプト（画像生成は後段・別タスク）
    bg_<id>.txt
    char_<id>_<expr>.txt
    cg_<id>.txt
  assets/          # 画像実体。未生成でもエンジンはプレースホルダで動く
    cover.jpg      # スキャフォルダが covers テーブルから自動書き出し
    bg_<id>.png    # 後段でSD生成物を投入
    char_<id>_<expr>.png
    cg_<id>.png
```

## `meta.json`

```json
{
  "work_id": "boku-dake-no-mazo-tsuma",
  "title": "僕だけのマゾ妻",
  "subtitle": "…",
  "author": "虚蝉丸",
  "publisher": "黒蜜出版",
  "series_name": null,
  "keywords": ["人妻", "…"],
  "schema": "novela-game/1"
}
```

## `script.json`

```json
{
  "work_id": "…",
  "title": "…",
  "start": "ep02",              // 最初に再生する scene id
  "scenes": [ Scene, … ]
}
```

### Scene

```json
{
  "id": "ep02",                 // 一意。choice の goto はこの id を指す
  "heading": "第一話　二〇二六年四月九日（木）　曇りのち雨",
  "bg": "bedroom_night",        // prompts/bg_bedroom_night.txt と対応。null可
  "bgm": "daily-warm-morning-guitar", // 曲ID（拡張子なし）。null または省略で現在の曲を維持。
  "chapter": "第一話　…",        // 任意。あれば scene 開始時に中央へ転換カードを出す。
                                //   話の冒頭シーンにだけ付ける（同話を分割した従シーンには付けない）。
  "lines": [ Line, … ],
  "next": "ep03"                // 任意。末尾で自動遷移する scene id。
                                //   省略時は scenes 配列の次要素へ。choice があれば choice 優先。
}
```

### Line（3種。`type` で判別。`type` 省略時は narration/dialogue を speaker で判定）

- **地の文** `narration`
  ```json
  { "speaker": null, "text": "今日の朝は少し肌寒くて、…" }
  ```
- **セリフ** `dialogue`
  ```json
  { "speaker": "歩美", "sprite": "ayumi_blush", "text": "「たっくん……あのね、お願いがあるの」" }
  ```
  - `speaker` は cast.json の `name` と一致させる。`"?"` は**未割当（要修正）**。
  - `sprite` は `cast.json` の表情ID（`char_<id>_<expr>` の `<expr>` 部分込みの解決済みID）。null可。
  - `text` の鉤括弧 `「」` は残す（エンジンがそのまま横書き表示）。
- **イベントCG（1枚絵）** — 任意。どの line にも付けられる追加フィールド `cg`（後方互換の任意拡張）。
  ```json
  { "speaker": null, "cg": "ep02_climax", "text": "視界いっぱいに……" }
  ```
  - `cg` が**非空文字列** → `assets/cg_<id>.png` を背景・立ち絵の上に全画面表示（その間、立ち絵と顔窓は隠れる）。
  - `cg` が `""`（空文字列）→ CGをクリアし、背景＋立ち絵の表示へ戻す。
  - `cg` **キー自体が無い** → 現在のCG状態を維持（立ち絵の不変条件と同じ思想）。
  - scene が切り替わると、エンジンはCGを**自動でクリア**する（各 scene はCGなしで開始）。
- **選択肢** `choice`
  ```json
  { "type": "choice", "prompt": "どうする？",
    "options": [ {"text": "受け入れる", "goto": "ep03"},
                 {"text": "ためらう",   "goto": "ep02b"} ] }
  ```
  - `goto` は実在 scene id を指すこと。分岐先 scene も `scenes` に追加する。

## `cast.json`

```json
{
  "characters": [
    { "name": "歩美", "id": "ayumi", "role": "heroine",
      "expressions": ["normal", "blush", "tearful", "ecstasy"],
      "desc_for_sd": "20代後半の人妻、黒髪ロング、…（立ち絵プロンプトの素体）" },
    { "name": "僕", "id": "boku", "role": "protagonist", "expressions": ["normal"],
      "desc_for_sd": "…" }
  ]
}
```
一人称の語り手（`僕`）は立ち絵を出さない運用も可（`expressions: []`）。

## `prompts/*.txt`

SD（Stable Diffusion）用。1ファイル1プロンプト。先頭にメタ、本体は英語。

```
# id: bg_bedroom_night
# kind: bg            (bg | char | cg)
# size: 1344x768      (bg=横長 / char=縦長 768x1344 / cg=作品に合わせる)
# model: <SDモデル名は後段で指定>
positive: anime style, dimly lit bedroom at night, …
negative: lowres, bad anatomy, text, watermark, …
```

立ち絵は表情ごとに `char_<id>_<expr>.txt`。`positive` は cast の `desc_for_sd` を素体に、表情差分を足す。

## BGM 解決規則

- `scene.bgm` には**曲ID**（拡張子なし）を入れる。例: `"digital-dreamscape"`
- エンジンはバンドルの `assets/` ではなく、**エンジン共有の `vnplayer/assets/bgm/<id>.mp3`** を参照する。
- BGMはムード汎用の共有ライブラリとして扱い、バンドルには含めない。
- `bgm` が `null` または省略された場合、エンジンは**現在の曲を維持**する（立ち絵の不変条件と同じ思想）。
- シーン遷移で曲が変わる場合、エンジンはクロスフェード（約800ms）で切り替える。同じ曲IDが続く場合は途切れさせない。
- 音源ファイルが欠損していてもエラーで止めない。

## 不変条件（エンジンが前提にする）

1. `start` と全 `goto` は実在 scene id。
2. `dialogue` の `speaker` は cast の `name` に存在（`"?"` を残さない）。
3. `bg`/`sprite` が指す画像が `assets/` に無ければ、エンジンはプレースホルダ表示（背景=単色、立ち絵=シルエット）で継続する。**欠損は致命ではない。**
4. `bgm` が指す音源ファイルが `vnplayer/assets/bgm/` に無ければ、エンジンは音なしで継続する。**BGM欠損は致命ではない。**
5. line の `cg` が指す `assets/cg_<id>.png` が無ければ、エンジンはCGを張らず背景・立ち絵のまま継続する。**CG欠損は致命ではない。**
