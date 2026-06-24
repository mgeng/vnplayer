#!/usr/bin/env python3
"""スタンドアロン配布ビルダー（FANZA同人 DL 向け / サーバ不要）。

novela が吐いたゲーム台本バンドル（SCHEMA: novela-game/1）を、
エンジン一式と一緒に **自己完結フォルダ + ZIP** に固める。
出力は `file://` で動く（index.html をダブルクリックで起動）。

仕組み:
  - script/meta/cast.json を `bundle.js`（window.NOVELA_BUNDLE=...）に埋め込み、fetch を消す
  - engine.js / style.css をコピー、index.html には bundle.js の読み込みを注入
  - バンドルの assets/ をコピー
  - 参照されている BGM だけ assets/bgm/ にコピー（共有ライブラリから）

使い方:
  python3 build.py <bundle_dir> [--name <出力名>] [--no-zip]
  例: python3 build.py /home/gkato/novela/work/game/boku-dake-no-mazo-tsuma
"""
import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE_FILES = ["engine.js", "style.css"]
SHARED_BGM = ROOT / "assets" / "bgm"


def load_bundle(bundle_dir: Path):
    def read(name, default):
        p = bundle_dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    return {
        "script": read("script.json", None),
        "meta": read("meta.json", {}),
        "cast": read("cast.json", {"characters": []}),
    }


def referenced_bgm(script) -> set:
    ids = set()
    for sc in (script or {}).get("scenes", []):
        if sc.get("bgm"):
            ids.add(sc["bgm"])
    return ids


def build_index(src_index: Path) -> str:
    """dev用 index.html に bundle.js の読み込みを注入した版を返す。"""
    html = src_index.read_text(encoding="utf-8")
    inject = '  <script src="bundle.js"></script>\n  <script src="engine.js"></script>'
    if '<script src="bundle.js">' in html:
        return html
    return html.replace('  <script src="engine.js"></script>', inject)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle_dir")
    ap.add_argument("--name", default=None, help="出力名（既定: バンドルのフォルダ名）")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    if not (bundle_dir / "script.json").exists():
        raise SystemExit(f"ERROR: {bundle_dir} に script.json が無い")

    name = args.name or bundle_dir.name
    out = ROOT / "dist" / name
    if out.exists():
        shutil.rmtree(out)
    (out / "assets" / "bgm").mkdir(parents=True, exist_ok=True)

    data = load_bundle(bundle_dir)

    # bundle.js（埋め込みデータ）
    (out / "bundle.js").write_text(
        "window.NOVELA_BUNDLE = " + json.dumps(data, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    # エンジン一式
    for f in ENGINE_FILES:
        shutil.copy2(ROOT / f, out / f)
    (out / "index.html").write_text(build_index(ROOT / "index.html"), encoding="utf-8")

    # バンドルの assets（cover / bg / char / cg …）
    src_assets = bundle_dir / "assets"
    if src_assets.exists():
        for item in src_assets.iterdir():
            if item.is_file():
                shutil.copy2(item, out / "assets" / item.name)

    # 参照BGMだけ同梱（共有ライブラリから）
    bgm_ids = referenced_bgm(data["script"])
    copied_bgm = []
    for bid in sorted(bgm_ids):
        src = SHARED_BGM / f"{bid}.mp3"
        if src.exists():
            shutil.copy2(src, out / "assets" / "bgm" / src.name)
            copied_bgm.append(bid)

    # ZIP
    zip_path = None
    if not args.no_zip:
        zip_path = ROOT / "dist" / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in out.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(out.parent))

    n_assets = sum(1 for _ in (out / "assets").glob("*") if _.is_file())
    print(f"standalone build → {out.relative_to(ROOT)}")
    print(f"  index.html をダブルクリックで起動（サーバ不要・file://）")
    print(f"  assets: {n_assets} files / bgm: {copied_bgm or '（なし）'}")
    if zip_path:
        print(f"  zip: {zip_path.relative_to(ROOT)} ({zip_path.stat().st_size/1024:.0f}KB)")


if __name__ == "__main__":
    main()
