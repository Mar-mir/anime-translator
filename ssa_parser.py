#!/usr/bin/env python3
"""پارسر فایلهای زیرنویس SSA/ASS

طراحی شده برای کنار srt_parser.py کار کنه:
- فقط متن Dialogue ترجمه میشه
- تایمینگ (Start/End)، استایل، لایه و همه هدرها دستنخورده میمونن
- تگهای override مثل pos(...) یا i1 برای ترجمه جدا میشن و موقع بازسازی سر جاشون برمیگردن
"""
import re
from dataclasses import dataclass
from typing import List, Tuple

OVERRIDE_RE = re.compile(r"\{[^}]*\}")


@dataclass
class SubtitleBlock:
    index: int
    timestamp: str      # "Start --> End" برای نمایش در UI
    text: str           # متن تمیز بدون تگ (همونی که به مترجم میره)
    translation: str = ""
    translated: bool = False
    # فیلدهای مخصوص ASS (برای بازسازی دقیق):
    start: str = ""
    end: str = ""
    style: str = "Default"
    name: str = ""
    margin_l: str = "0"
    margin_r: str = "0"
    margin_v: str = "0"
    effect: str = ""
    prefix_tags: str = ""   # تگهای اول خط مثل {\pos(400,570)}


def strip_tags(text: str) -> str:
    """حذف تگهای override از متن برای ترجمه"""
    return OVERRIDE_RE.sub("", text)


def extract_prefix_tags(text: str) -> Tuple[str, str]:
    """جدا کردن تگهای اول خط از بقیه متن. برمیگردونه (tags, rest)"""
    m = re.match(r"^((?:\{[^}]*\})+)(.*)$", text, re.DOTALL)
    if m:
        return m.group(1), m.group(2)
    return "", text


def parse_ass(content: str) -> Tuple[str, List[SubtitleBlock], str]:
    """پارس محتوای ASS/SSA.

    برمیگردونه: (header, blocks, format_line)
    - header: همه خطوط قبل از اولین Dialogue (استایلها، هدرها، بخش Events)
    - blocks: فقط خطوط Dialogue با Text غیرخالی
    - format_line: خط Format بخش Events
    """
    content = content.replace("\ufeff", "")
    lines = content.split("\n")

    header_lines: List[str] = []
    blocks: List[SubtitleBlock] = []
    format_line = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    in_events = False
    found_first_dialogue = False
    idx = 0

    for line in lines:
        stripped = line.strip()

        if stripped.lower() == "[events]":
            in_events = True
            if not found_first_dialogue:
                header_lines.append(line)
            continue

        if in_events and stripped.lower().startswith("format:"):
            format_line = stripped
            if not found_first_dialogue:
                header_lines.append(line)
            continue

        if in_events and stripped.lower().startswith("dialogue:"):
            found_first_dialogue = True
            # جدا کردن 9 کامای اول — بقیه متن Text هست (ممکنه کاما داشته باشه)
            payload = stripped[len("dialogue:"):].strip()
            parts = payload.split(",", 9)
            if len(parts) < 10:
                continue
            layer, start, end, style, name, ml, mr, mv, effect, text = [p.strip() for p in parts]
            if not strip_tags(text).strip():
                continue  # خط خالی — ترجمه نمیخواد
            idx += 1
            tags, clean = extract_prefix_tags(text)
            blocks.append(SubtitleBlock(
                index=idx,
                timestamp=f"{start} --> {end}",
                text=strip_tags(clean).replace("\\N", "\n").replace("\\n", "\n").strip(),
                start=start, end=end, style=style, name=name,
                margin_l=ml, margin_r=mr, margin_v=mv, effect=effect,
                prefix_tags=tags,
            ))
            continue

        if not found_first_dialogue:
            header_lines.append(line)

    header = "\n".join(header_lines).rstrip("\n")
    return header, blocks, format_line


def blocks_to_ass(header: str, blocks: List[SubtitleBlock]) -> str:
    """بازسازی فایل ASS — تایمینگ و استایل از مقادیر اصلی، فقط Text جایگزین میشه."""
    out = [header, ""]
    for b in blocks:
        text = b.translation if b.translated else b.text
        # برگردوندن newline به فرمت ASS + چسبوندن تگهای اول خط
        ass_text = b.prefix_tags + text.replace("\n", "\\N")
        out.append(
            f"Dialogue: 0,{b.start},{b.end},{b.style},{b.name},"
            f"{b.margin_l},{b.margin_r},{b.margin_v},{b.effect},{ass_text}"
        )
    return "\n".join(out) + "\n"


def is_ass_filename(filename: str) -> bool:
    fn = filename.lower()
    return fn.endswith(".ass") or fn.endswith(".ssa")
