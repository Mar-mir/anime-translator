#!/usr/bin/env python3
"""موتور ترجمه زیرنویس با OpenAI API"""
import json
import os
import time
import requests
from typing import List, Optional, Callable
from srt_parser import SubtitleBlock, batch_blocks, extract_translation


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

SYSTEM_PROMPT = """You are a professional anime subtitle translator. Translate English anime dialogue to natural, colloquial Persian (Farsi).

RULES:
1. Translate ONLY the text provided, do NOT add or remove any lines
2. Keep the same number of lines as input
3. Use natural Persian that anime fans would use
4. Preserve anime-specific terms appropriately
5. Do NOT include line numbers or timestamps in your response
6. Each translated line should be on a separate line
7. If a line is empty or just a sound effect (like *sigh*, *gasps*), translate it naturally
8. For names, keep the original Japanese name or use common Persian fan translations
9. Be concise - subtitle lines should be short and readable
10. Match the tone: casual dialogue should stay casual, dramatic should stay dramatic"""


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"api_keys": [], "default_model": "gpt-4o-mini", "batch_size": 20}


def save_config(config: dict):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_api_key() -> Optional[str]:
    """دریافت اولین کلید API معتبر"""
    config = load_config()
    keys = config.get("api_keys", [])
    # فیلتر کردن کلیدهای خالی
    valid_keys = [k for k in keys if k and k.strip()]
    return valid_keys[0] if valid_keys else None


def get_all_api_keys() -> List[str]:
    config = load_config()
    return [k for k in config.get("api_keys", []) if k and k.strip()]


def translate_batch(
    texts: List[str],
    context_before: List[SubtitleBlock] = None,
    context_after: List[SubtitleBlock] = None,
    api_key: str = None,
    model: str = None,
    base_url: str = None
) -> List[str]:
    """
    ترجمه یک دسته متن
    """
    if not api_key:
        api_key = get_api_key()
    if not api_key:
        raise ValueError("کلید API تنظیم نشده! لطفاً از صفحه تنظیمات یک کلید اضافه کنید.")

    config = load_config()
    if not model:
        model = config.get("default_model", "gpt-4o-mini")
    if not base_url:
        base_url = config.get("base_url", "https://api.openai.com/v1")

    # ساخت پرامپت با بافت
    prompt_parts = []

    if context_before:
        ctx_text = '\n'.join([f"[context] {b.text}" for b in context_before])
        prompt_parts.append(f"Previous lines (for context only, do NOT translate these):\n{ctx_text}")

    prompt_parts.append("NOW TRANSLATE THE FOLLOWING LINES:\n")
    for i, t in enumerate(texts, 1):
        prompt_parts.append(f"{i}. {t}")

    if context_after:
        ctx_text = '\n'.join([f"[context] {b.text}" for b in context_after])
        prompt_parts.append(f"\nNext lines (for context only, do NOT translate these):\n{ctx_text}")

    prompt_parts.append(f"\nTranslate exactly {len(texts)} lines. Output ONLY the Persian translations, one per line, numbered {len(texts)}.")

    prompt = '\n\n'.join(prompt_parts)

    # درخواست API
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4096
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    translations = extract_translation(content, len(texts))

    # اگه تعداد ترجمه‌ها کمتر از مورد انتظار بود، خطوط باقی‌مانده رو خالی بذار
    while len(translations) < len(texts):
        translations.append("")

    return translations[:len(texts)]


def translate_subtitles(
    blocks: List[SubtitleBlock],
    api_key: str = None,
    model: str = None,
    base_url: str = None,
    batch_size: int = 20,
    progress_callback: Callable = None
) -> List[SubtitleBlock]:
    """
    ترجمه تمام زیرنویس‌ها با پیشرفت
    """
    batches = batch_blocks(blocks, batch_size=batch_size)
    total_batches = len(batches)
    translated_count = 0

    for batch_info in batches:
        current_batch = batch_info['current']
        if not current_batch:
            continue

        texts = [b.text for b in current_batch]

        try:
            translations = translate_batch(
                texts=texts,
                context_before=batch_info['context_before'],
                context_after=batch_info['context_after'],
                api_key=api_key,
                model=model,
                base_url=base_url
            )

            for block, trans in zip(current_batch, translations):
                block.translation = trans
                block.translated = True

            translated_count += len(current_batch)

            if progress_callback:
                progress_callback(
                    current=batch_info['batch_num'],
                    total=total_batches,
                    translated=translated_count,
                    total_lines=len(blocks)
                )

        except Exception as e:
            print(f"خطا در دسته {batch_info['batch_num']}: {e}")
            # در صورت خطا، خطوط ترجمه نشده باقی میمونن
            if progress_callback:
                progress_callback(
                    current=batch_info['batch_num'],
                    total=total_batches,
                    translated=translated_count,
                    total_lines=len(blocks),
                    error=str(e)
                )

        # تأخیر بین درخواست‌ها برای جلوگیری از rate limit
        time.sleep(0.5)

    return blocks
