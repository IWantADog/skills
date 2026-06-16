#!/usr/bin/env python3
"""Parse an .epub or .mobi file and emit JSON describing its chapters.

Output schema (stdout, one JSON object):
{
  "title":    str,
  "author":   str | null,
  "language": "zh" | "en",
  "chapters": [
    {"index": int, "title": str, "length": int}  # length = chars (zh) or words (en)
  ],
  "total_length": int
}

Errors are emitted as {"error": "..."} with exit code 1.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def ensure_deps():
    try:
        import ebooklib  # noqa: F401
        import bs4  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--user", "-q",
             "ebooklib", "beautifulsoup4", "lxml"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def ensure_mobi():
    try:
        import mobi  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--user", "-q", "mobi"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


CJK_RE = re.compile(r"[一-鿿]")
WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def detect_language(sample_text: str) -> str:
    if not sample_text:
        return "en"
    cjk = len(CJK_RE.findall(sample_text))
    total = len(sample_text)
    return "zh" if total and cjk / total > 0.1 else "en"


def count_length(text: str, lang: str) -> int:
    if lang == "zh":
        return len(CJK_RE.findall(text))
    return len(WORD_RE.findall(text))


def html_to_text(html_bytes: bytes) -> str:
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html_bytes, "lxml")
    except Exception:
        soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def parse_epub(path: str) -> dict:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(path, options={"ignore_ncx": False})

    title = ""
    try:
        meta_title = book.get_metadata("DC", "title")
        if meta_title:
            title = meta_title[0][0]
    except Exception:
        pass
    if not title:
        title = Path(path).stem

    author = None
    try:
        meta_author = book.get_metadata("DC", "creator")
        if meta_author:
            author = meta_author[0][0]
    except Exception:
        pass

    item_text: dict[str, str] = {}
    sample_chunks: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        text = html_to_text(item.get_content())
        href = item.get_name()
        item_text[href] = text
        if len(sample_chunks) < 5:
            sample_chunks.append(text[:2000])
    sample = " ".join(sample_chunks)
    lang = detect_language(sample)

    def walk_toc(toc, out: list, depth: int = 0):
        for entry in toc:
            if isinstance(entry, tuple):
                section, children = entry
                walk_toc([section], out, depth)
                walk_toc(children, out, depth + 1)
            else:
                link = entry
                title_s = (getattr(link, "title", None) or "").strip()
                href = (getattr(link, "href", None) or "").split("#")[0]
                out.append((title_s, href, depth))

    flat: list[tuple[str, str, int]] = []
    walk_toc(book.toc, flat)

    chapters = []
    if flat:
        seen_href: set[str] = set()
        for i, (ch_title, href, _depth) in enumerate(flat):
            if not href or not ch_title:
                continue
            if href in seen_href:
                continue
            seen_href.add(href)
            text = item_text.get(href, "")
            if not text:
                for k, v in item_text.items():
                    if k.endswith(href) or href.endswith(k):
                        text = v
                        break
            length = count_length(text, lang)
            chapters.append({
                "index": len(chapters) + 1,
                "title": ch_title,
                "length": length,
            })

    if not chapters:
        for i, (href, text) in enumerate(item_text.items(), 1):
            length = count_length(text, lang)
            if length < 50:
                continue
            chapters.append({
                "index": len(chapters) + 1,
                "title": f"Section {len(chapters) + 1}",
                "length": length,
            })

    total = sum(c["length"] for c in chapters)
    return {
        "title": title,
        "author": author,
        "language": lang,
        "chapters": chapters,
        "total_length": total,
    }


def parse_mobi(path: str) -> dict:
    ensure_mobi()
    import mobi

    tmpdir, filepath = mobi.extract(path)
    try:
        filepath = str(filepath)
        if filepath.lower().endswith(".epub"):
            return parse_epub(filepath)

        candidates: list[Path] = []
        for root, _, files in os.walk(tmpdir):
            for fn in files:
                if fn.lower().endswith(".epub"):
                    candidates.append(Path(root) / fn)
        if candidates:
            return parse_epub(str(candidates[0]))

        html_files: list[Path] = []
        for root, _, files in os.walk(tmpdir):
            for fn in files:
                if fn.lower().endswith((".html", ".htm", ".xhtml")):
                    html_files.append(Path(root) / fn)
        if not html_files:
            raise RuntimeError("无法从 mobi 中提取章节内容")

        html_files.sort()
        sample_chunks: list[str] = []
        per_file_text: list[tuple[str, str]] = []
        for fp in html_files:
            text = html_to_text(fp.read_bytes())
            per_file_text.append((fp.name, text))
            if len(sample_chunks) < 5:
                sample_chunks.append(text[:2000])
        lang = detect_language(" ".join(sample_chunks))

        chapters = []
        for name, text in per_file_text:
            length = count_length(text, lang)
            if length < 50:
                continue
            chapters.append({
                "index": len(chapters) + 1,
                "title": Path(name).stem,
                "length": length,
            })
        total = sum(c["length"] for c in chapters)
        return {
            "title": Path(path).stem,
            "author": None,
            "language": lang,
            "chapters": chapters,
            "total_length": total,
        }
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- Scheduling & Markdown rendering ---------------------------------------
#
# 调度策略：**优先按用户每天的分钟数切日**，章节根据字数被拆分到多天。
# 同一章跨多天时,每段标 `[i/N]` 并显示页码区间。

SPEED_ZH = 300          # 字 / 分钟
SPEED_EN = 250          # 词 / 分钟
CHARS_PER_PAGE_ZH = 600 # 估算每页字数（参考印刷版）
WORDS_PER_PAGE_EN = 250 # 估算每页词数（参考印刷版）


def schedule_markdown(data: dict, daily_minutes: int) -> str:
    title = data["title"]
    author = data.get("author")
    language = data["language"]
    chapters = data["chapters"]
    total_length = data["total_length"]

    if language == "zh":
        speed, per_page, unit = SPEED_ZH, CHARS_PER_PAGE_ZH, "字"
    else:
        speed, per_page, unit = SPEED_EN, WORDS_PER_PAGE_EN, "词"

    budget = daily_minutes * speed
    total_pages = max(1, (total_length + per_page - 1) // per_page)

    cursor = 0
    for ch in chapters:
        ch["_offset"] = cursor
        cursor += ch["length"]

    days: list[list[dict]] = []
    current: list[dict] = []
    current_load = 0

    for ch in chapters:
        if ch["length"] <= 0:
            continue
        consumed = 0
        remaining = ch["length"]
        while remaining > 0:
            space = budget - current_load
            if space <= 0:
                days.append(current)
                current = []
                current_load = 0
                space = budget
            take = min(remaining, space)
            seg_start = ch["_offset"] + consumed
            seg_end = seg_start + take - 1
            page_start = seg_start // per_page + 1
            page_end = seg_end // per_page + 1
            current.append({
                "title": ch["title"],
                "ch_index": ch["index"],
                "length": take,
                "page_start": page_start,
                "page_end": page_end,
                "minutes": max(1, round(take / speed)),
            })
            consumed += take
            remaining -= take
            current_load += take

    if current:
        days.append(current)

    seg_counts: dict[int, int] = {}
    for day in days:
        for seg in day:
            seg_counts[seg["ch_index"]] = seg_counts.get(seg["ch_index"], 0) + 1

    seen: dict[int, int] = {}
    for day in days:
        for seg in day:
            total_segs = seg_counts[seg["ch_index"]]
            if total_segs > 1:
                seen[seg["ch_index"]] = seen.get(seg["ch_index"], 0) + 1
                seg["seg_label"] = f" [{seen[seg['ch_index']]}/{total_segs}]"
            else:
                seg["seg_label"] = ""

    lines: list[str] = []
    lines.append(f"# 《{title}》阅读计划")
    lines.append("")
    lines.append(f"**书籍**: 《{title}》")
    if author:
        lines.append(f"**作者**: {author}")
    lines.append(f"**总章节**: {len(chapters)}")
    lines.append(f"**估算总{unit}数**: {total_length:,}")
    lines.append(f"**估算总页数**: {total_pages:,} 页（按每页 {per_page} {unit}估算）")
    lines.append(f"**每天阅读**: {daily_minutes} 分钟（约 {budget:,} {unit}）")
    lines.append(f"**预计需要**: {len(days)} 天读完")
    lines.append(f"**阅读速度参考**: 中文 {SPEED_ZH} 字/分钟、英文 {SPEED_EN} 词/分钟")
    lines.append("")
    lines.append("## 每日 Todo")
    lines.append("")
    lines.append("> 每行都是自包含的，可直接复制到滴答清单 / Todoist / Notion 等工具。")
    lines.append("> 哪天开始读、是否连续都不影响，按自己的节奏勾选即可。")
    lines.append("")
    for day_idx, day in enumerate(days, 1):
        day_minutes = sum(seg["minutes"] for seg in day)
        suffix = " ✅ 完成全书" if day_idx == len(days) else ""
        lines.append(f"- [ ] 《{title}》Day {day_idx} · 约 {day_minutes} 分钟{suffix}")
        for seg in day:
            if seg["page_start"] == seg["page_end"]:
                page_range = f"P.{seg['page_start']}"
            else:
                page_range = f"P.{seg['page_start']}-{seg['page_end']}"
            lines.append(f"  - {seg['title']}{seg['seg_label']}（{page_range}）")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append(f"- {unit}数、页数均为估算值，实际阅读速度和分页因人/设备而异。")
    lines.append("- 完成一天后把 `[ ]` 改成 `[x]` 即可。")
    lines.append("- 拆分到多天的章节用 `[i/N]` 标注，按页码区间连续阅读即可。")
    lines.append(f"- 中文按 {SPEED_ZH} 字/分钟、每页 {CHARS_PER_PAGE_ZH} 字估算；英文按 {SPEED_EN} 词/分钟、每页 {WORDS_PER_PAGE_EN} 词估算。")
    return "\n".join(lines)


def parse_book(path: str) -> dict:
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "epub":
        return parse_epub(path)
    if ext == "mobi":
        return parse_mobi(path)
    raise ValueError(f"不支持的格式: .{ext}（仅支持 epub/mobi）")


def main(argv: list[str]) -> int:
    daily_minutes: int | None = None
    output: str | None = None
    positional: list[str] = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--schedule":
            i += 1
            try:
                daily_minutes = int(argv[i])
            except (IndexError, ValueError):
                print(json.dumps({"error": "--schedule 需要一个整数分钟数"}, ensure_ascii=False))
                return 1
        elif a == "--output":
            i += 1
            if i >= len(argv):
                print(json.dumps({"error": "--output 需要一个文件路径"}, ensure_ascii=False))
                return 1
            output = argv[i]
        elif a in ("-h", "--help"):
            print("用法: parse_ebook.py <book_path> [--schedule MINUTES] [--output PATH]")
            return 0
        else:
            positional.append(a)
        i += 1

    if len(positional) != 1:
        print(json.dumps({"error": "用法: parse_ebook.py <book_path> [--schedule MINUTES] [--output PATH]"}, ensure_ascii=False))
        return 1
    path = positional[0]
    if not os.path.isfile(path):
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
        return 1

    ensure_deps()

    try:
        result = parse_book(path)
    except Exception as e:
        print(json.dumps({"error": f"解析失败: {type(e).__name__}: {e}"}, ensure_ascii=False))
        return 1

    if daily_minutes is None:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    md = schedule_markdown(result, daily_minutes)
    if output is None:
        book_dir = os.path.dirname(os.path.abspath(path))
        stem = result.get("title") or Path(path).stem
        output = os.path.join(book_dir, f"{stem}-reading-plan.md")
    with open(output, "w", encoding="utf-8") as f:
        f.write(md)
    print(json.dumps({"ok": True, "output": output, "days": md.count("\n- [ ]")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
