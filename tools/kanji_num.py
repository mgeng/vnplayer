#!/usr/bin/env python3
"""横書きゲーム台本向け：漢数字→アラビア数字 変換（安全版）。

慣用語（一緒・一番・一気・一斉・第一印象 など）を壊さないため、
**数量を表す文脈に限定**して変換する：
  - 年号の位置記数 二〇二六 → 2026（〇を含む数字列＋年）
  - 第N話 → 第{n}話
  - <漢数字><カウンタ> （年/月/日/時/分/秒/歳/回/人/ヶ月/週間/年間/時間/日間/枚/cm/kg…）
カウンタの無い裸の漢数字や、慣用語は変換しない。
"""
import re

_D = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
      "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNIT = {"十": 10, "百": 100, "千": 1000}

# 変換を許可するカウンタ（慣用語になりにくいもの）。番/度/つ 等は除外。
COUNTERS = ["年間", "週間", "日間", "時間", "ヶ月", "ヵ月", "カ月", "か月",
            "年", "月", "日", "時", "分", "秒", "歳", "才", "回", "人",
            "枚", "本", "個", "杯", "匹", "冊", "歩", "階", "件", "centimeter"]
_KNUM = "〇零一二三四五六七八九十百千"


def _parse_kanji_int(s: str) -> int:
    """十百千を含む通常の漢数字（例 二十二, 千五百）を int に。"""
    total = 0
    cur = 0
    for ch in s:
        if ch in _D:
            cur = cur * 10 + _D[ch] if False else _D[ch]
            # 単純化: 連続単数字（二十二の"二"等）は下で処理
        if ch in _D:
            cur = _D[ch]
            last = cur
        elif ch in _UNIT:
            u = _UNIT[ch]
            total += (cur if cur != 0 else 1) * u
            cur = 0
    total += cur
    return total


def _parse_positional(s: str) -> int:
    """〇を含む位置記数（二〇二六）。各字を1桁として連結。"""
    return int("".join(str(_D[c]) for c in s))


def _conv_run(run: str) -> str:
    if "〇" in run or "零" in run:
        # 位置記数（年号など）。十百千が混じる異常系は通常パースに回す。
        if not (set(run) & set("十百千")):
            return str(_parse_positional(run))
    return str(_parse_kanji_int(run))


def convert(text: str) -> str:
    if not text:
        return text

    # 第N話
    def _ep(m):
        return f"第{_conv_run(m.group(1))}話"
    text = re.sub(rf"第([{_KNUM}]+)話", _ep, text)

    # <漢数字列><カウンタ>
    counter_alt = "|".join(sorted(COUNTERS, key=len, reverse=True))
    pat = re.compile(rf"([{_KNUM}]+)(?={counter_alt})")
    text = pat.sub(lambda m: _conv_run(m.group(1)), text)

    return text


if __name__ == "__main__":
    tests = [
        "第一話　二〇二六年四月九日（木）　曇りのち雨",
        "第二十二話　二〇二六年五月二十二日（金）　晴れ",
        "一ヶ月くらいかけて、毎日ちゃんと確認しながら",
        "二人でゆっくりお風呂に入って",
        "二回も小さな絶頂を迎え",
        "五分ほどかけて",
        "二十七歳の人妻",
        # 慣用語（変換されないこと）
        "歩美と一緒に、初めての経験",
        "一番好きなのは",
        "一気に飛散するかも",
        "全部一斉に",
    ]
    for t in tests:
        print(f"{t}\n  → {convert(t)}\n")
