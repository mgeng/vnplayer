# novela VN Player + Generator

novela で作った小説を **ノベルゲーム(VN)化** して再生・配布する独立リポジトリ。
2つの役割を持つ：

1. **生成（シナリオ化＋画像）** … `tools/` ＋ `.claude/skills/game-export/`
   novela のプレーンテキスト export を `novela-game/1` 台本バンドルへ変換し、SDXL で画像生成。
2. **再生・配布** … `engine.js` / `index.html` / `style.css` / `build.py`
   依存ゼロの軽量Webプレイヤー。`build.py` で `file://` 自己完結バンドル（FANZA DL 向け）を作る。

**novela とは疎結合**：VN 側は `novels.db` を一切読まず、novela が
`novels_db.py export` で吐く**プレーンテキスト成果物**だけに依存する（DB スキーマは novela 内部に閉じる）。
詳細は [CLAUDE.md](CLAUDE.md)。

## バンドルの取り決め

台本仕様は `.claude/skills/game-export/SCHEMA.md`（`novela-game/1`）。エンジンはこの仕様だけに依存する。

## 使い方（dev）

1. novela 側でプレーンテキストを export：
   ```bash
   cd /path/to/novela
   python scripts/novels_db.py export <work_id>   # → work/manuscript/ep_*.md ほか
   ```
2. 台本バンドルへ変換（DB 非依存・入力はファイルのみ）：
   ```bash
   cd /path/to/vnplayer
   python3 tools/game_export.py <work_id> --input /path/to/novela/work
   # → work/game/<work_id>/  （game-export スキルで script.json を仕上げる）
   ```
3. 画像生成（GPU VM、コスト規律は CLAUDE.md 必読）：
   ```bash
   python3 tools/game_sdxl.py <work_id>
   ```
4. ローカルサーバで開く（`file://` だと fetch がCORSで失敗するのでHTTP必須）：
   ```bash
   ln -s /path/to/vnplayer/work/game/<work_id> bundle
   python3 -m http.server 8100   # http://localhost:8100/  別バンドルは ?bundle=path
   ```

## 配布（dist）

```bash
python3 build.py work/game/<work_id> --name <name>
# → dist/<name>/ （bundle.js に JSON inline）+ dist/<name>.zip。index.html ダブルクリックで起動。
```

## 画像

`bundle/assets/` の `bg_<id>.png` / `char_<id>_<expr>.png` / `cg_<id>.png` / `cover.jpg` を使う。
**画像が無くても動く**（背景=グラデ、立ち絵=シルエットのプレースホルダ）。
カバーは `tools/game_sdxl.py` 生成 or novela 配布カバーを `assets/cover.jpg` へ手動コピー。

## 操作

- テキストウィンドウ／Enter／Space／←：次へ
- 選択肢：クリックで分岐

## 構成

- `index.html` / `style.css` / `engine.js` … プレイヤー本体（ビルド不要）
- `build.py` … 配布バンドラ
- `tools/` … `game_export.py`（DB非依存の台本スキャフォルダ）/ `game_sdxl.py`（画像生成）/ `kanji_num.py`
- `.claude/skills/game-export/` … 変換スキル＋`SCHEMA.md`（契約）
- `assets/bgm/` … 共有BGMライブラリ（SUNO製）
