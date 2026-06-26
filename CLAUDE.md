# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`vnplayer` は novela の小説を **ノベルゲーム(VN)化** して再生・配布する独立リポジトリ。
2つの役割を1リポジトリに統合している：

1. **生成（シナリオ化＋画像）** — `tools/` ＋ `.claude/skills/game-export/`
2. **再生・配布** — `engine.js` / `index.html` / `style.css` / `build.py`（依存ゼロの軽量Web、ビルド不要）

FANZA 同人 DL 販売向け。配布はサーバレス（`file://`）：`build.py` が JSON を `bundle.js` に inline 化し
`dist/<name>/` ＋ ZIP に自己完結化、`index.html` ダブルクリックで起動。

## novela との境界（疎結合）

最重要原則：**VN 側は novela の `novels.db` を一切読まない。**
直接 DB を読むと `episodes.episode_number` 等のスキーマが VN プロジェクトに漏れ、結合度が上がる。
そこで novela は **プレーンテキスト export** だけを公開インターフェースとして提供し、VN 側はその
**ファイル成果物にのみ依存**する。

- 連携の流れ：
  1. novela: `python scripts/novels_db.py export <work_id>`
     → `work/manuscript/ep_*.md` ＋ `work/metadata/kdp_metadata.json` ＋ `work/config.json`
  2. vnplayer: `python3 tools/game_export.py <work_id> --input /path/to/novela/work`
     → `work/game/<work_id>/` に台本バンドル（`script.json`/`meta.json`/`cast.json`/`prompts/`/`assets/`）
- バンドル契約 = `.claude/skills/game-export/SCHEMA.md`（`novela-game/1`）。**vnplayer がオーナー**。
  破壊変更は schema バージョンを上げる。エンジンはこの仕様だけに依存。

## パイプライン

1. **シナリオ化スキャフォルダ** `tools/game_export.py`（DB非依存）— ep_*.md → scene 分割・地の文/会話分類・話者プレースホルダ。
2. **台本オーサリング** `.claude/skills/game-export/`（Claude）— 話者割当・bg/sprite/cg 演出・SDプロンプト・選択肢分岐。
3. **画像生成** `tools/game_sdxl.py` — 背景/立ち絵/顔(8表情)/イベントCG を SDXL で本生成。
4. **横書き整形** `tools/kanji_num.py` — 横組み向け 漢数字→アラビア（日付/話数/カウンタ限定の安全版、慣用語は保持）。
5. **再生** `python3 -m http.server` → `?bundle=...`。画像/BGM 欠損時はプレースホルダ/無音で動く。
6. **配布** `python3 build.py work/game/<work_id> --name <name>` → `dist/<name>/` ＋ ZIP。

カバー：DB 非依存化で `game_export.py` はカバーを出力しない。タイトル画面のカバーは `game_sdxl.py`
生成 or novela 配布カバーを `assets/cover.jpg` へ手動コピー。

## 画像生成 = ローカル SDXL（Illustrious XL / mangen）

汎用 SDXL 層（プロンプト→PNG、白背景の透過 keying、QUALITY/NEG プリセット、mangen API/VM 規律）は
**ルート共通スキル `~/.claude/skills/sdxl-image/`**（private repo `mgeng/sdxl-image`）に集約済み。
`tools/game_sdxl.py` はその CLI（`sdxl.py gen` / `sdxl.py key`）を **subprocess で shell out** し、
作品固有層だけを持つ：キャラのアンカータグ＋固定 seed、表情/背景/CG カタログ、VNエンジン解決名での出力。

- キャラ一貫性 = 固定アンカー（例 `AYUMI`、泣きぼくろ等の識別特徴）＋固定 seed。outfit を分離し CG は nude 可。
- **CG は solo-POV**（語り手は一人称・画面外）＝2キャラ drift を避ける。立ち絵/顔は白背景生成→keying で透過、CG は全画面。
- Grok と違いモデレーション制約なし。1枚 ~9–10s。
- API は `http://localhost:8188`（SSH ポートフォワード経由）。`MANGEN_API` で差し替え可。
  2ステップ方式 `POST /generate` → `GET /img/<filename>`（仕様書の `/generate/raw` は現状404）。
- **既知サーババグ**：result cache が `(seed, size)` キーで prompt を無視 → 同seed/同size の表情差分が1枚に潰れる。
  回避＝表情ごとに unique seed（一貫性はアンカーで担保）。CG は各々別 seed なので影響なし。

### ⚠️ GPU VM コスト規律（最重要・生成前に必読）

mangen SDXL API は **ローカルではなく GCP GPU VM `mangen-gpu`**（project `sunlit-inn-480805-k9`）上で動き、
**RUNNING 中は課金され続ける**。VN トラック全体の支配的コスト。VM を希少・高価・時間制限つき資源として扱う：

- 制御コマンドは `~/bin`：**`vm-status`**（0=RUNNING/1=存在非起動/2=不在）、**`vm-up`**（起動。不在なら `spin-up.sh`。
  API ポートは開かない）、**`vm-down`**（= VM＋ブートディスク削除＝課金停止。image は残る）、`vm-connect`（SSH）。
- API（:8188）到達は **SSH ポートフォワードのみ**（`gcloud compute ssh … -- -L 8188:localhost:8188`）。
  `vm-up` 単体ではトンネルは張られない → 自分でバックグラウンドトンネルを起動する。
- **課金最小ワークフロー**：prep（エンジン/CG層コード・プロンプト・`script.json` 編集・keying ロジック）は
  **VM ダウン中に全部済ませる** → `vm-up` ＋トンネル → 全生成を **1バッチ**で（GPU は直列・~9–10s/枚、並列呼び出しでも速くならない）
  → 終わったら **即 `vm-down`**。統合・検証・思考の間は VM を上げない。不安なら `vm-status` で確認して落とす。
- 透過 keying は **vm-down 後にローカルで** `sdxl.py key`（`gen` は keying しない）。

## VN エンジン（再生）

- 横書き表示・背景（`assets/bg_<id>.png`）・全身立ち絵（`assets/char_<id>_<expr>.png`）・
  左下フェイスウィンドウ（`assets/face_<id>.png`）・イベントCG（`assets/cg_<id>.png`、story/H ピークの1枚絵）。
  line の `cg` フィールドで設定、`""` でクリア、scene 転換で自動クリア。CG 表示中は立ち絵＋フェイス窓を隠す。
- BGM は SUNO 製、共有 `assets/bgm/<id>.mp3`（800ms クロスフェード、🔊ミュート）。`build.py` が参照分だけ同梱。
- 画像/BGM 欠損時はプレースホルダ/無音で動く（SCHEMA.md 不変条件）。
- エピソード転換カードは `scene.chapter`。

## 環境

- Python 3、Node 不要（ビルドステップなし）。`tools/game_sdxl.py` は `~/.claude/skills/sdxl-image/sdxl.py` を呼ぶ。
- API キー類は `~/.env`（`XAI_API_KEY` 等）。ハードコード禁止。
- **FANZA 用の局部モザイクは別の販売前仕上げ工程**で、ジェネレータは行わない。

## Conventions & guardrails

- ブランチは `master` のみ。コミット/プッシュは**ユーザーが明示したときだけ**。
- `work/`（バンドル出力）・`bundle/`・`dist/` は git-ignore のスクラッチ。勝手にコミットしない。
- 著者・出版社の表記は novela 側に準拠（虚蝉丸 / 黒蜜出版）。
