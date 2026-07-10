"""Link-value probe: does one-hop wiki-link expansion recall what search misses?

The claim under test (lab ADR-0001 / issue XnneHangLab#484): links written at
memorization time recall *meaning-related, wording-disjoint* items that BM25
cannot reach. Two corpora, every probe run with ``expand_links`` on and off:

- **small** — 14 hand-written items, 8 probes (readable, worst-case-free)
- **generated** — ~150 items: 30 unique 3-item chains (career → move → social,
  each with distinct profession/city entities) + 60 unlinked distractors,
  60 probes. Deliberately floods BM25 with structurally identical competitors
  (thirty items all containing 转行/搬到) so ranking must rely on the unique
  entity terms, and the wording-disjoint chain tails stay link-only.

Deterministic (seeded); no randomness in scoring. Probes are classified from
the data, not by hand: an expected item that only appears with expansion
counts as an *association win*. Run:

    uv run python bench/link_probe.py
"""

from __future__ import annotations

import random
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


_PROFESSIONS = [
    "后端开发",
    "游戏开发",
    "数据分析",
    "产品经理",
    "界面设计",
    "算法工程",
    "运维工程",
    "前端开发",
    "测试工程",
    "技术写作",
    "电商运营",
    "视频剪辑",
    "同声翻译",
    "商业插画",
    "广告配音",
    "直播主播",
    "律师助理",
    "注册会计",
    "中学教师",
    "健身教练",
    "西餐厨师",
    "人像摄影",
    "定制木工",
    "园艺景观",
    "精品咖啡烘焙",
    "调酒",
    "宠物美容",
    "出境导游",
    "剧本编剧",
    "影视作曲",
]
_CITIES = [
    "上海",
    "深圳",
    "广州",
    "杭州",
    "成都",
    "重庆",
    "武汉",
    "西安",
    "南京",
    "苏州",
    "天津",
    "长沙",
    "青岛",
    "厦门",
    "大连",
    "宁波",
    "合肥",
    "郑州",
    "济南",
    "福州",
    "昆明",
    "贵阳",
    "南宁",
    "哈尔滨",
    "沈阳",
    "兰州",
    "银川",
    "海口",
    "珠海",
    "太原",
]
_FOODS = [
    "螺蛳粉",
    "藤椒鱼",
    "羊肉泡馍",
    "肠粉",
    "锅包肉",
    "臭鳜鱼",
    "串串香",
    "煲仔饭",
    "生腌虾",
    "豆汁",
    "醪糟汤圆",
    "梅菜扣肉",
    "白切鸡",
    "小炒黄牛肉",
    "冷面",
    "驴打滚",
    "糖油粑粑",
    "胡辣汤",
    "蛋烘糕",
    "沙茶面",
]
_HABITS = [
    "晨跑五公里",
    "睡前冥想",
    "记手账",
    "养多肉",
    "拼乐高",
    "打羽毛球",
    "练毛笔字",
    "钓鱼",
    "拍星空",
    "收集邮票",
    "弹尤克里里",
    "玩桌游",
    "做木雕",
    "学法语",
    "跳街舞",
    "练滑板",
    "包饺子",
    "酿果酒",
    "修钢笔",
    "叠纸模型",
]


def build_generated_corpus() -> tuple[list[tuple[str, str, str]], list[tuple[str, list[str]]]]:
    """30 unique chains + 60 unlinked distractors, 60 association probes."""
    rng = random.Random(42)
    corpus: list[tuple[str, str, str]] = []
    probes: list[tuple[str, list[str]]] = []
    for i in range(30):
        prof = _PROFESSIONS[i]
        city = _CITIES[i]
        origin = _CITIES[(i + 7) % 30]
        career = f"转行{prof}"
        move = f"搬到{city}"
        social = f"想念{origin}老友{i}"
        corpus.append(
            (
                "career",
                career,
                f"从原来的行业转行做了{prof}，最近在补相关技能。[[daily_life:{move}]]",
            )
        )
        corpus.append(
            ("daily_life", move, f"因为换了新工作，从{origin}搬到了{city}。[[social:{social}]]")
        )
        corpus.append(("social", social, f"很想念{origin}的老朋友们，周末常和他们视频。"))
        probes.append((f"用户转行做{prof}之后生活发生了什么变化？", [career, move]))
        probes.append((f"用户搬到{city}之后心情怎么样？", [move, social]))
    for j, food in enumerate(_FOODS):
        corpus.append(("preferences", f"爱吃{food}", f"特别爱吃{food}，隔三差五就要来一顿。"))
        del j
    for j, habit in enumerate(_HABITS):
        corpus.append(("daily_life", f"习惯-{habit}", f"保持着{habit}的习惯，坚持了挺久。"))
        del j
    for j in range(20):
        topic = f"领域笔记{j}"
        corpus.append(("knowledge", topic, f"记录过关于{_PROFESSIONS[j]}方向的一些工作笔记。"))
    rng.shuffle(corpus)
    return corpus, probes


def run_corpus(
    title: str,
    corpus: list[tuple[str, str, str]],
    probes: list[tuple[str, list[str]]],
    *,
    show_rows: bool,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "memory")
        for category, name, content in corpus:
            store.add(category, name, content, owner="probe")
        index = MemoryIndex(store, use_jieba=None)

        rows: list[dict[str, object]] = []
        latencies: dict[bool, list[float]] = {True: [], False: []}
        tokens: dict[bool, list[int]] = {True: [], False: []}

        for query, expected in probes:
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

        print(f"## {title}")
        print(
            f"corpus: {len(corpus)} items | probes: {len(probes)} | tokenizer: char-bigram (no jieba)"
        )
        print()
        if show_rows:
            print("| probe | expected | BM25 only | +links | link-only wins |")
            print("|---|---|---|---|---|")
            for r in rows:
                print(
                    f"| {r['query']} | {r['expected']} | {r['off']} | {r['on']} | {r['link_only']} |"
                )
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
        print()


def run() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage
    run_corpus("small (hand-written)", CORPUS, PROBES, show_rows=True)
    generated_corpus, generated_probes = build_generated_corpus()
    run_corpus(
        "generated (chains + distractor flood)", generated_corpus, generated_probes, show_rows=False
    )


if __name__ == "__main__":
    run()
