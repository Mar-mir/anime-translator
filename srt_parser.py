#!/usr/bin/env python3
"""پارسر فایل‌های زیرنویس SRT"""
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SubtitleBlock:
    index: int
    timestamp: str
    text: str
    translation: str = ""
    translated: bool = False


def parse_srt(content: str) -> List[SubtitleBlock]:
    """پارس محتوای SRT و بازگشت لیست زیرنویس‌ها"""
    blocks = []
    # حذف BOM
    content = content.replace('\ufeff', '')
    # جدا کردن بلوک‌ها با دو خط خالی
    raw_blocks = re.split(r'\n\s*\n', content.strip())

    for block in raw_blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue

        # پیدا کردن خط timestamp
        ts_idx = -1
        for i, line in enumerate(lines):
            if '-->' in line:
                ts_idx = i
                break

        if ts_idx < 0:
            continue

        # شماره زیرنویس (خط قبل از timestamp)
        try:
            idx = int(lines[ts_idx - 1].strip())
        except (ValueError, IndexError):
            continue

        timestamp = lines[ts_idx].strip()
        text = '\n'.join(lines[ts_idx + 1:]).strip()

        if text:
            blocks.append(SubtitleBlock(
                index=idx,
                timestamp=timestamp,
                text=text
            ))

    return blocks


def blocks_to_srt(blocks: List[SubtitleBlock]) -> str:
    """تبدیل لیست بلوک‌ها به فرمت SRT"""
    parts = []
    for b in blocks:
        text = b.translation if b.translated else b.text
        parts.append(f"{b.index}\n{b.timestamp}\n{text}")
    return '\n\n'.join(parts) + '\n'


def batch_blocks(blocks: List[SubtitleBlock], batch_size: int = 20, context_lines: int = 5) -> List[dict]:
    """
    دسته‌بندی بلوک‌ها برای ترجمه
    هر دسته شامل batch_size خط + context_lines خط قبل و بعد
    """
    batches = []
    total = len(blocks)

    for i in range(0, total, batch_size):
        start = max(0, i - context_lines)
        end = min(total, i + batch_size + context_lines)

        context_before = blocks[start:i]
        current = blocks[i:i + batch_size]
        context_after = blocks[i + batch_size:end]

        batches.append({
            'context_before': context_before,
            'current': current,
            'context_after': context_after,
            'batch_num': len(batches) + 1,
            'total_batches': (total + batch_size - 1) // batch_size
        })

    return batches


def extract_translation(response: str, batch_size: int) -> List[str]:
    """
    استخراج ترجمه‌ها از پاسخ مدل
    فرمت مورد انتظار: هر خط ترجمه در یک خط جداگانه
    """
    lines = [l.strip() for l in response.strip().split('\n') if l.strip()]

    # اگه تعداد خطوط کمتر از batch_size بود، خطوط خالی رو نادیده بگیر
    translations = []
    for line in lines:
        # حذف شماره خط اگه وجود داشته باشه (مثلاً "1. ترجمه")
        cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
        if cleaned:
            translations.append(cleaned)

    return translations
