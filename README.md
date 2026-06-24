# novela VN Player

novela で作った小説を変換したノベルゲーム台本（`novela-game/1` バンドル）を再生する、
依存ゼロの軽量Webプレイヤー。**このリポジトリは novela とは独立**（別プレーン：novela は台本を吐く製造ライン、
こちらは動かすランタイム）。

## バンドルの取り決め

台本仕様は novela 側の `.claude/skills/game-export/SCHEMA.md`（`novela-game/1`）。
このプレイヤーはその仕様だけに依存する。

## 使い方

1. novela で台本を生成：
   ```bash
   cd /path/to/novela
   python3 scripts/game_export.py <work_id>      # → work/game/<work_id>/
   # game-export スキルで script.json を仕上げる（話者・bg・sprite・SDプロンプト）
   ```
2. バンドルを `bundle/` に置く（コピー or シンボリックリンク）：
   ```bash
   ln -s /path/to/novela/work/game/<work_id> bundle
   ```
3. ローカルサーバで開く（`file://` だと fetch がCORSで失敗するのでHTTP必須）：
   ```bash
   python3 -m http.server 8100
   # http://localhost:8100/ を開く
   ```
   別バンドルを指すには `?bundle=path/to/dir`。

## 画像

`bundle/assets/` の `bg_<id>.png` / `char_<id>_<expr>.png` / `cg_<id>.png` / `cover.jpg` を使う。
**画像が無くても動く**（背景=グラデ、立ち絵=シルエットのプレースホルダ）。
実画像は Stable Diffusion で `bundle/prompts/*.txt` から生成して `assets/` に入れる（後段の別タスク）。

## 操作

- テキストウィンドウ／Enter／Space／←：次へ
- 選択肢：クリックで分岐

## 構成

- `index.html` / `style.css` / `engine.js` のみ。ビルド不要。
