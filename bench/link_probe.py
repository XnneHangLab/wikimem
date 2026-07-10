"""Link-value probe: does one-hop wiki-link expansion recall what search misses?

The claim under test (lab ADR-0001 / issue XnneHangLab#484): links written at
memorization time recall *meaning-related, wording-disjoint* items that BM25
cannot reach. This harness seeds a small synthetic corpus with deliberate
cross-category chains, runs every probe with ``expand_links`` on and off, and
reports recall + latency + injected-token deltas.

Probes are classified from the data, not by hand: an expected item that only
appears with expansion counts as an *association win*; one that BM25 finds by
itself is *direct*. Run:

    uv run python bench/link_probe.py
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wikimem import MemoryIndex, MemoryStore  # noqa: E402

# (category, name, content) — links form chains across categories.
CORPUS: list[tuple[str, str, str]] = [
    (
        "career",
        "转行后端",
        "从市场营销转行做了后端开发，主要写 Python 服务。[[daily_life:搬到上海]]",
    ),
    ("daily_life", "搬到上海", "因为换了新工作，从北京搬到了上海浦东。[[social:想念北京朋友]]"),
    ("social", "想念北京朋友", "很想念北京的老朋友，周末经常和他们视频聊天。"),
    ("preferences", "likes-the-sea", "喜欢海边，说过想找机会去海边放松。[[daily_life:三亚之行]]"),
    ("daily_life", "三亚之行", "打算夏天去三亚，看日出和潜水。"),
    ("preferences", "手冲咖啡", "只喝手冲咖啡，从不加糖。[[health:控糖]]"),
    ("health", "控糖", "在控制糖分摄入，甜食基本都戒掉了。"),
    (
        "projects",
        "vtuber-项目",
        "在开发桌面虚拟形象项目，用 Live2D 做形象层。[[projects:记忆管线]]",
    ),
    ("projects", "记忆管线", "给桌面伙伴做长期记忆，文件优先、markdown 是唯一事实源。"),
    ("preferences", "科幻小说", "喜欢科幻小说，最近在重读三体。"),
    # 干扰项（无链接）
    ("daily_life", "健身习惯", "每周去三次健身房，主要练力量。"),
    ("social", "同事聚餐", "上周和新同事聚了餐，气氛不错。"),
    ("knowledge", "python-异步", "熟悉 asyncio，写过不少异步服务。"),
    ("event", "领养猫", "上个月领养了一只橘猫，取名叫年糕。"),
]

# (query, expected item names)
PROBES: list[tuple[str, list[str]]] = [
    ("用户喝什么咖啡？", ["手冲咖啡"]),
    ("用户最近在读什么书？", ["科幻小说"]),
    ("用户的咖啡习惯和身体状况有什么关联？", ["手冲咖啡", "控糖"]),
    ("用户做后端开发之后生活发生了什么变化？", ["转行后端", "搬到上海"]),
    ("用户搬到上海之后心情怎么样？", ["搬到上海", "想念北京朋友"]),
    ("用户喜欢海边吗？有什么出行安排？", ["likes-the-sea", "三亚之行"]),
    ("桌面虚拟形象项目有什么配套系统？", ["vtuber-项目", "记忆管线"]),
    ("用户为什么想念北京的朋友？", ["想念北京朋友", "搬到上海"]),
]


def run() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "memory")
        for category, name, content in CORPUS:
            store.add(category, name, content, owner="probe")
        index = MemoryIndex(store, use_jieba=None)

        rows: list[dict[str, object]] = []
        latencies: dict[bool, list[float]] = {True: [], False: []}
        tokens: dict[bool, list[int]] = {True: [], False: []}

        for query, expected in PROBES:
            found: dict[bool, set[str]] = {}
            for expand in (False, True):
                started = time.perf_counter()
                result = index.retrieve(query, budget_tokens=800, expand_links=expand)
                latencies[expand].append((time.perf_counter() - started) * 1000)
                tokens[expand].append(result.budget_used)
                found[expand] = {entry.item.name for entry in result.items}
            hit_off = [name for name in expected if name in found[False]]
            hit_on = [name for name in expected if name in found[True]]
            link_only = sorted(set(hit_on) - set(hit_off))
            rows.append(
                {
                    "query": query,
                    "expected": len(expected),
                    "off": len(hit_off),
                    "on": len(hit_on),
                    "link_only": "、".join(link_only) or "-",
                }
            )

        total_expected = sum(int(r["expected"]) for r in rows)
        total_off = sum(int(r["off"]) for r in rows)
        total_on = sum(int(r["on"]) for r in rows)

        print(
            f"corpus: {len(CORPUS)} items | probes: {len(PROBES)} | tokenizer: char-bigram (no jieba)"
        )
        print()
        print("| probe | expected | BM25 only | +links | link-only wins |")
        print("|---|---|---|---|---|")
        for r in rows:
            print(f"| {r['query']} | {r['expected']} | {r['off']} | {r['on']} | {r['link_only']} |")
        print()
        off_pct = 100.0 * total_off / total_expected
        on_pct = 100.0 * total_on / total_expected
        print(
            f"recall: BM25-only {total_off}/{total_expected} ({off_pct:.0f}%) → "
            f"+links {total_on}/{total_expected} ({on_pct:.0f}%)  [Δ +{on_pct - off_pct:.0f}pp]"
        )
        print(
            f"latency (ms, median): off {statistics.median(latencies[False]):.2f} / "
            f"on {statistics.median(latencies[True]):.2f}"
        )
        print(
            f"injected tokens (mean): off {statistics.mean(tokens[False]):.0f} / "
            f"on {statistics.mean(tokens[True]):.0f}"
        )


if __name__ == "__main__":
    run()
