#!/usr/bin/env python3
"""ゲーム用画像を mangen SDXL(Illustrious XL) で本生成する（VN 作品固有ドライバ）。

素の SDXL 生成（プロンプト→PNG、白背景の透過keying、mangen API/VM 規律）は
ルート共通スキル `~/.claude/skills/sdxl-image/sdxl.py` に集約済み。本ファイルは
その CLI を shell out しつつ、この作品固有の素材だけを持つ:
  - 歩美 アンカータグ + 固定 seed（キャラ一貫性の肝）
  - 表情 / 背景 / イベントCG カタログ
  - VN エンジン解決名での出力（work/game/<work_id>/assets/）

VM コスト規律・キャッシュバグ等はルートスキル SKILL.md を参照。生成は VM 稼働中に一括で。

使い方:
  python3 tools/game_sdxl.py <work_id>                  # bg+char+face+cg 全部
  python3 tools/game_sdxl.py <work_id> --kind face      # 顔だけ
  python3 tools/game_sdxl.py <work_id> --kind char --exprs blush smile
  python3 tools/game_sdxl.py <work_id> --kind char --no-key   # 透過を後回し（VM時間節約）
"""
import sys, os, json, time, argparse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = os.environ.get("NOVELA_WORK", "work")
SDXL_CLI = os.path.expanduser("~/.claude/skills/sdxl-image/sdxl.py")

# ── 歩美 アンカータグ ────────────────────────────────────────
# 一貫性の肝：素体（顔・髪・体）＝IDENTITY を全カットで完全固定し、
# 服装は別タグにして立ち絵/顔とCG（裸体あり）で出し分ける。
# 識別の決め手として「泣きぼくろ(mole under eye)」を固定特徴に入れる。
AYUMI = ("1girl, mature female, 28 years old, black hair, medium hair, straight hair, "
         "hair between eyes, brown eyes, tareme, mole under eye, long eyelashes, "
         "fair skin, slender, large breasts, soft delicate face, beautiful detailed eyes")
AYUMI_OUTFIT = "pink cardigan, white blouse, black choker"  # 立ち絵/顔の通常衣装
SEED_AYUMI = 7777  # 立ち絵(char)の seed 固定（char は構図が広く差分が小さいので共有可）

# 顔アイコンは表情ごとに固有 seed を割り当てる。
# 理由: mangen サーバの結果キャッシュが (seed, size) のみをキーにしており
# prompt/negative を無視する既知バグ（ルート SKILL.md 参照）。同 seed・同 size の
# 8 表情がすべて同一画像に潰れていた。一貫性はアンカータグ(AYUMI)に任せ seed は分離。
FACE_SEEDS = {
    "normal": 7701, "blush": 7712, "shy": 7703, "smile": 7714,
    "determined": 7715, "pain": 7706, "tearful": 7707, "ecstasy": 7708,
}

# ── 表情差分（danbooru 寄り）───────────────────────────────
EXPRESSIONS = {
    "normal":     "calm expression, neutral face, soft gaze, closed mouth, slight smile",
    "blush":      "blush, shy, embarrassed, gentle smile, looking away, light smile",
    "shy":        "heavy blush, embarrassed, looking down, covering mouth, nervous, bashful",
    "smile":      "smile, happy, light blush, looking at viewer, gentle eyes, open mouth",
    "determined": "serious, determined, looking at viewer, straight face, parted lips",
    "pain":       "pain, closed eyes, furrowed brow, wince, gritted teeth, distressed",
    "tearful":    "crying, tears, teary eyes, trembling, sad, looking down, parted lips",
    "ecstasy":    "half-closed eyes, heavy blush, parted lips, ahegao, ecstasy, "
                  "dreamy expression, flushed, sweat",
}

# ── 背景（人物なし）──────────────────────────────────────
BACKGROUNDS = {
    "bg_living_evening":
        "no humans, indoors, living room, japanese apartment, evening, sofa, "
        "warm dim lighting, soft shadows, cozy, scenery",
    "bg_bedroom_night":
        "no humans, indoors, bedroom, double bed, white sheets, night, "
        "bedside lamp, dim warm light, calm atmosphere, scenery",
}

# ── イベントCG（1枚絵）─────────────────────────────────────
# 物語の山場の主役画像。全カット 歩美 単独 + POV（夫=一人称の語り手は画面外）に
# 統一＝二人構図の破綻を避け、同一人物性を保つ。横長フルステージ・透過なし。
# (id, prompt, seed)  prompt は AYUMI(素体) を前置きして合成する。
CGS = {
    "cg_confession": (
        "solo, sitting on sofa, living room, evening, indoors, pink cardigan, "
        "heavy blush, shy, embarrassed, looking at viewer, hand on own chest, "
        "parted lips, intimate mood, warm dim lighting, cinematic", 1001),
    "cg_first_anal_pain": (
        "solo, completely nude, bedroom, on bed, white sheets, night, on all fours, "
        "top-down bottom-up, looking back, tears, crying, pain, gritted teeth, blush, "
        "gripping sheets, large breasts, pov, dim warm light", 1002),
    "cg_finger_training": (
        "solo, nude, bedroom, on bed, night, blush, embarrassed, fingering, "
        "looking back, ass focus, presenting, sweat, parted lips, pov, dim light", 1003),
    "cg_noshirt_welcome": (
        "solo, white dress shirt, naked shirt, no panties, bottomless, standing, "
        "genkan, indoors, evening, blush, shy, looking at viewer, inviting, "
        "bare thighs, hand on door, pov, warm lighting", 1004),
    "cg_mirror_masturbation": (
        # 旧プロンプトの "mirror, reflection, looking at mirror" が人物を二重化（分身）。
        # 鏡/反射を撤去して単独構図に。solo/1girl を強調し別seedで再生成。
        "solo, 1girl, nude, bedroom, on bed, sitting, spread legs, "
        "masturbation, heavy blush, ecstasy, sweat, parted lips, looking at viewer, "
        "large breasts, dim lamp light", 1015),
    "cg_first_anal_sex": (
        "solo, nude, on bed, bedroom, night, ecstasy, heavy blush, sweat, "
        "spread legs, looking at viewer, large breasts, parted lips, tears of pleasure, "
        "pov, intimate, dim warm light", 1006),
    "cg_collar_slave": (
        "solo, nude, black leather collar, leash, kneeling, living room, looking up at viewer, "
        "blush, submissive, obedient, hands on thighs, large breasts, pov, dim lighting", 1007),
    "cg_finale_ecstasy": (
        "solo, close-up, face focus, ecstasy, ahegao, heavy blush, sweat, tears, "
        "half-closed eyes, tongue out, orgasm, looking at viewer, intense pleasure, "
        "dim warm light, cinematic", 1008),
    "cg_cowgirl_sex": (  # ep04: 騎乗位で激しく交わる山場
        "solo, 1girl, nude, girl on top, cowgirl position, straddling, on bed, "
        "bedroom, night, heavy blush, ecstasy, sweat, large breasts, "
        "looking at viewer, parted lips, pov, dim warm light, cinematic", 1009),
    "cg_morning_apron": (  # ep06: 朝のキッチン、裸エプロンで自ら晒す
        "solo, 1girl, naked apron, bottomless, no panties, kitchen, morning, "
        "bent over, looking back, blush, embarrassed, presenting, ass focus, "
        "bare thighs, sweat, pov, bright morning light", 1010),
    "cg_cunnilingus": (  # ep08: 焦らしのクンニ、脚を大きく広げて
        "solo, 1girl, nude, on bed, bedroom, spread legs, knees up, pussy focus, "
        "from above, heavy blush, ecstasy, tears, sweat, large breasts, "
        "parted lips, pov, dim warm light", 1011),
    "cg_bondage_training": (  # ep10: 拘束・ハーネス・ボールギャグの調教撮影
        "solo, 1girl, nude, bdsm, black leather harness, bondage, blindfold, "
        "ball gag, drooling, restrained, spread legs, bound, on bed, "
        "heavy blush, sweat, large breasts, pov, dim light", 1012),
    "cg_car_exposure": (  # ep11: 下着なし白ワンピで助手席、露出調教の始まり
        "solo, 1girl, white sundress, no panties, sitting, car interior, "
        "passenger seat, daytime, blush, embarrassed, aroused, thighs together, "
        "black leather choker, pov, sunlight through trees", 1013),
}


def gen_to(out: Path, prompt, size, seed=None, neg_preset="base", neg_extra=None):
    """ルート共通 sdxl.py の gen を shell out。成功時 meta(dict) を返す。失敗時 None。"""
    cmd = [sys.executable, SDXL_CLI, "gen", "--prompt", prompt, "--size", size,
           "--neg-preset", neg_preset, "--out", str(out)]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if neg_extra:
        cmd += ["--neg-extra", neg_extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stderr:
        sys.stderr.write(r.stderr)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def key_file(out: Path):
    """ルート共通 sdxl.py の key を shell out。透過率を返す（失敗時 -1）。"""
    r = subprocess.run([sys.executable, SDXL_CLI, "key", str(out)],
                       capture_output=True, text=True)
    if r.stderr:
        sys.stderr.write(r.stderr)
    if r.returncode != 0:
        return -1.0
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]).get("transparent_ratio", -1.0)
    except (ValueError, IndexError):
        return -1.0


def run_bg(assets, only=None):
    for bid, tags in BACKGROUNDS.items():
        if only and bid not in only:
            continue
        out = assets / f"{bid}.png"
        print(f"→ bg {bid} ...")
        meta = gen_to(out, tags, "1344x768", seed=None, neg_preset="bg")
        if meta:
            print(f"  ✓ {out.name}  ({meta['elapsed']}, seed={meta['seed']})")
        else:
            print(f"  ✗ {out.name} 失敗", file=sys.stderr)


def run_char(assets, exprs, do_key=True):
    # 白一色スタジオ背景で「分離した」立ち絵を強制（壁/影が入って抜けない対策）。
    base = ("1girl, solo, standing, full body, cowboy shot, "
            "simple background, white background, plain white background, "
            "isolated on white, studio background, "
            f"{AYUMI}, {AYUMI_OUTFIT}")
    for expr in exprs:
        out = assets / f"char_ayumi_{expr}.png"
        print(f"→ char {expr} ...")
        meta = gen_to(out, f"{base}, {EXPRESSIONS[expr]}", "768x1344",
                      seed=SEED_AYUMI, neg_preset="sprite")
        if meta:
            # 透過処理は重い(ローカルBFS)。VM稼働時間節約のため --no-key 時はスキップし
            # vm-down 後にまとめてローカルで key する。
            tr = key_file(out) if do_key else -1
            tag = f"透過{tr:.0%}" if do_key else "raw(未透過)"
            print(f"  ✓ {out.name}  ({meta['elapsed']}, seed={meta['seed']}, {tag})")
        else:
            print(f"  ✗ {out.name} 失敗", file=sys.stderr)


def run_face(assets, exprs):
    # 顔窓は「顔全体」が入る head-and-shoulders 構図にする。
    # "close-up, face focus" は片目だけの極端アップに潰れる。
    # head shot + whole face in frame + chin/forehead を明示し、画面外クロップを防ぐ。
    base = ("head shot, portrait, whole face visible, entire head in frame, "
            "forehead visible, chin visible, headroom above head, "
            "face centered in frame, shoulders at bottom edge, looking at viewer, "
            "white background, simple background, "
            f"{AYUMI}, {AYUMI_OUTFIT}")
    # クローズアップ過多・見切れ・バストアップへの drift を抑えるネガティブ。
    neg_extra = ("extreme close-up, cropped face, out of frame, "
                 "face cut off, partial face, zoomed in, "
                 "head out of frame, forehead cut off, cropped head, "
                 "bust shot, chest focus, cleavage focus, breast focus")
    for expr in exprs:
        out = assets / f"face_ayumi_{expr}.png"
        seed = FACE_SEEDS.get(expr, SEED_AYUMI)
        print(f"→ face {expr} (seed={seed}) ...")
        meta = gen_to(out, f"{base}, {EXPRESSIONS[expr]}", "768x768",
                      seed=seed, neg_preset="char", neg_extra=neg_extra)
        if meta:
            tr = key_file(out)
            print(f"  ✓ {out.name}  ({meta['elapsed']}, seed={meta['seed']}, 透過{tr:.0%})")
        else:
            print(f"  ✗ {out.name} 失敗", file=sys.stderr)


def run_cg(assets, only=None):
    """イベントCG（1枚絵）を生成。横長フルステージ・透過なし。"""
    for cid, (tags, seed) in CGS.items():
        if only and cid not in only:
            continue
        out = assets / f"{cid}.png"
        print(f"→ cg {cid} ...")
        meta = gen_to(out, f"{AYUMI}, {tags}", "1344x768", seed=seed, neg_preset="char")
        if meta:
            print(f"  ✓ {out.name}  ({meta['elapsed']}, seed={meta['seed']})")
        else:
            print(f"  ✗ {out.name} 失敗", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_id")
    ap.add_argument("--kind", choices=["all", "bg", "char", "face", "cg"], default="all")
    ap.add_argument("--exprs", nargs="*", help="表情ID（省略時は全部）")
    ap.add_argument("--bg", nargs="*", help="背景ID（省略時は全部）")
    ap.add_argument("--cg", nargs="*", help="CG ID（省略時は全部）")
    ap.add_argument("--no-key", action="store_true",
                    help="立ち絵の透過処理をスキップ（rawのみ）。VM時間節約用、後でローカルkey")
    args = ap.parse_args()

    assets = ROOT / WORK / "game" / args.work_id / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    exprs = args.exprs or list(EXPRESSIONS.keys())
    for e in exprs:
        if e not in EXPRESSIONS:
            sys.exit(f"不明な表情ID: {e}")

    t0 = time.time()
    if args.kind in ("all", "bg"):
        run_bg(assets, args.bg)
    if args.kind in ("all", "char"):
        run_char(assets, exprs, do_key=not args.no_key)
    if args.kind in ("all", "face"):
        run_face(assets, exprs)
    if args.kind in ("all", "cg"):
        run_cg(assets, args.cg)
    print(f"\n完了 ({time.time()-t0:.0f}s) → {assets.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
