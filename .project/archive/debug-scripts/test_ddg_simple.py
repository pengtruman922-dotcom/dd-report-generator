"""快速测试DuckDuckGo是否可用"""

import sys
import io

# 修复Windows控制台编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from duckduckgo_search import DDGS

def test_ddg():
    print("测试 DuckDuckGo 搜索（不同region参数）...")
    print("=" * 60)

    test_cases = [
        ("中大咨询集团", "cn-zh", "中国区域"),
        ("中大咨询集团", "wt-wt", "全球区域"),
        ("中大咨询集团", "us-en", "美国区域"),
        ("Zhongda Consulting Group", "wt-wt", "英文查询-全球"),
    ]

    for query, region, desc in test_cases:
        print(f"\n查询: {query} | Region: {region} ({desc})")
        print("-" * 60)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, region=region, max_results=5))
                print(f"[OK] 找到 {len(results)} 条结果")

                for i, r in enumerate(results, 1):
                    print(f"  {i}. {r.get('title', 'N/A')[:60]}")
                    print(f"     {r.get('href', 'N/A')[:80]}")

        except Exception as e:
            print(f"[ERROR] 搜索失败: {e}")
            print(f"错误类型: {type(e).__name__}")

if __name__ == "__main__":
    test_ddg()
