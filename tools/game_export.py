#!/usr/bin/env python3
"""小説（プレーンテキスト） → ノベルゲーム台本バンドルのスキャフォルダ。

novela が書き出したプレーンテキスト export を **入力ファイルとして** 読み、
ノベルゲーム化の土台（script.json / meta.json / cast.json / prompts/ / assets/）を生成する。

**疎結合の方針**: このスクリプトは `novels.db` を一切開かない。novela の DB スキーマ
（episodes テーブル・episode_number 列など）に依存させないため、入力は novela の
`novels_db.py export <work_id>` が吐く成果物だけに限定する:
  <input>/manuscript/ep_*.md          各話の本文（プレーンテキスト）
  <input>/metadata/kdp_metadata.json  タイトル/著者/出版社/シリーズ/キーワード
  <input>/config.json                 work_id 等のフォールバック（任意）

このスクリプトは「下ごしらえ」だけを機械的に行う:
  - 各 ep_*.md を 1 scene に割る（先頭の日付見出しを scene 見出しに）
  - 本文を行へ分解し、地の文 / セリフ（「」）を素朴に分類
  - セリフの話者は推定せず speaker="?" のプレースホルダにする
台本としての仕上げ（話者割当・背景/立ち絵指定・SDプロンプト・選択肢）は
game-export スキルの手順に従って Claude が後段で詰める。
カバー画像は VN 側で扱う（SDXL 生成 or novela 配布カバーを手動コピー）。

使い方:
  python3 tools/game_export.py <work_id> --input <export_dir> [--out <dir>]
  # --input 既定: $NOVELA_EXPORT、無ければ ../novela/work
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = os.environ.get("NOVELA_WORK", "work")
DEFAULT_INPUT = os.environ.get("NOVELA_EXPORT", str((ROOT.parent / "novela" / "work")))

# 日記体の話見出し: 「第一話　二〇二六年四月九日（木）　曇りのち雨」「最終話　…」など
EP_HEADING_RE = re.compile(r"^(第[〇一二三四五六七八九十百]+話|最終話|プロローグ|エピローグ|序章|終章)")
# 行頭/末の全角空白を含む素朴なセリフ判定
DIALOGUE_RE = re.compile(r"^[　\s]*[「『]")


def is_front_matter(body: str) -> bool:
    """タイトルページ/目次だけの前付け話か判定する。"""
    head = body[:400]
    if "Table of Contents" in head or "Title Page" in head:
        return True
    # 本文らしい地の文がほぼ無い（句点が極端に少ない）
    return body.count("。") < 2


def classify_line(text: str) -> dict:
    """1行を台本の line 要素に変換（話者は未割当）。"""
    stripped = text.strip()
    if DIALOGUE_RE.match(text):
        return {"speaker": "?", "sprite": None, "text": stripped}
    return {"speaker": None, "text": stripped}


def split_episode(body: str):
    """episode 本文を (heading, lines[]) に分解する。"""
    raw_lines = [ln for ln in body.splitlines()]
    heading = None
    lines = []
    for ln in raw_lines:
        s = ln.strip()
        if not s:
            continue
        if heading is None and EP_HEADING_RE.match(s):
            heading = s
            continue
        # 作品タイトルだけの行などはスキップ対象にしない（地の文として残す）
        lines.append(classify_line(ln))
    return heading, lines


def load_episodes(input_dir: Path):
    """<input>/manuscript/ep_*.md を episode_number 順に読む。"""
    man_dir = input_dir / "manuscript"
    files = sorted(man_dir.glob("ep_*.md"))
    eps = []
    for p in files:
        m = re.search(r"ep_(\d+)\.md$", p.name)
        num = int(m.group(1)) if m else len(eps) + 1
        eps.append({"episode_number": num, "body": p.read_text(encoding="utf-8")})
    return eps


def load_meta_source(input_dir: Path):
    """kdp_metadata.json（主）＋ config.json（フォールバック）を読む。"""
    kdp = {}
    cfg = {}
    kdp_path = input_dir / "metadata" / "kdp_metadata.json"
    cfg_path = input_dir / "config.json"
    if kdp_path.exists():
        try:
            kdp = json.loads(kdp_path.read_text(encoding="utf-8"))
        except Exception:
            kdp = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    return kdp, cfg


def load_cast(input_dir: Path):
    """<input>/characters/*.json があれば話者候補の出典を記録（無ければ空）。

    本文（script.json）から起こすのが基本。characters があれば後段の参考に出典だけ残す。
    """
    cast = {"characters": []}
    chars_dir = input_dir / "characters"
    for fname in ("protagonist.json", "sub_cast.json", "couples.json"):
        p = chars_dir / fname
        if p.exists():
            cast.setdefault("_source", []).append(str(p))
    return cast


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_id")
    ap.add_argument("--input", default=DEFAULT_INPUT,
                    help="novela の export ディレクトリ（既定: $NOVELA_EXPORT or ../novela/work）")
    ap.add_argument("--out", default=None, help="出力先（既定: $NOVELA_WORK/game/<work_id>）")
    ap.add_argument("--keep-front", action="store_true", help="先頭の前付け話を除外しない")
    args = ap.parse_args()

    input_dir = Path(args.input)
    man_dir = input_dir / "manuscript"
    if not man_dir.is_dir():
        print(f"ERROR: 入力に manuscript/ が無い: {man_dir}\n"
              f"  novela 側で `python scripts/novels_db.py export {args.work_id}` を先に実行してください。",
              file=sys.stderr)
        sys.exit(1)

    episodes = load_episodes(input_dir)
    if not episodes:
        print(f"ERROR: {man_dir} に ep_*.md が無い", file=sys.stderr)
        sys.exit(1)
    kdp, cfg = load_meta_source(input_dir)

    out_dir = Path(args.out) if args.out else (ROOT / WORK / "game" / args.work_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompts").mkdir(exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    def pick(key):
        return kdp.get(key) or cfg.get(key)

    # meta.json
    meta = {
        "work_id": args.work_id or cfg.get("work_id"),
        "title": pick("title"),
        "subtitle": pick("subtitle"),
        "author": pick("author"),
        "publisher": pick("publisher"),
        "series_name": pick("series_name"),
        "keywords": kdp.get("keywords", []),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "schema": "novela-game/1",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # script.json（scene 単位の足場）
    scenes = []
    skipped = 0
    for ep in episodes:
        if not args.keep_front and is_front_matter(ep["body"]):
            skipped += 1
            continue
        heading, lines = split_episode(ep["body"])
        head = heading or ""
        scenes.append({
            "id": f"ep{ep['episode_number']:02d}",
            "heading": head,
            "chapter": head,   # 話の冒頭=転換カード。同話を分割したら従シーンは外す
            "bg": None,        # TODO(claude): 背景ID（prompts/bg_*.txt と対応）
            "bgm": None,
            "lines": lines,
        })
    script = {
        "work_id": meta["work_id"],
        "title": meta["title"],
        "start": scenes[0]["id"] if scenes else None,
        "scenes": scenes,
    }
    (out_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    # cast.json（話者候補の足場）
    cast = load_cast(input_dir)
    (out_dir / "cast.json").write_text(json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8")

    n_lines = sum(len(s["lines"]) for s in scenes)
    n_dlg = sum(1 for s in scenes for ln in s["lines"] if ln.get("speaker") == "?")
    shown = out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir
    print(f"bundle: {shown}")
    print(f"  input       : {input_dir}")
    print(f"  scenes      : {len(scenes)}  (front-matter skipped: {skipped})")
    print(f"  lines       : {n_lines}  (dialogue: {n_dlg} 要話者割当)")
    print(f"  cast source : {cast.get('_source', '（characters 無し→台本から起こす）')}")
    print("\n次は game-export スキルの手順で script.json を仕上げる（話者・bg・sprite・SDプロンプト）。")
    print("カバーは VN 側で用意（SDXL 生成 or novela 配布カバーを assets/cover.jpg に手動コピー）。")


if __name__ == "__main__":
    main()
