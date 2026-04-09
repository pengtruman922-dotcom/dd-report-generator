"""测试DuckDuckGo是否完全可用"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from duckduckgo_search import DDGS

def test():
    print("测试DuckDuckGo基本功能...")
    print("=" * 60)

    # 测试一个肯定有结果的查询
    test_cases = [
        ("Python programming", "wt-wt"),
        ("Microsoft", "wt-wt"),
        ("GitHub", "wt-wt"),
        ("阿里巴巴集团", "wt-wt"),
    ]

    for query, region in test_cases:
        print(f"\n查询: {query} | Region: {region}")
        print("-" * 60)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, region=region, max_results=3))
                print(f"[OK] 找到 {len(results)} 条结果")

                if results:
                    for i, r in enumerate(results, 1):
                        print(f"  {i}. {r.get('title', 'N/A')[:60]}")
                else:
                    print("  [WARNING] 返回空列表")

        except Exception as e:
            print(f"[ERROR] {e}")

if __name__ == "__main__":
    test()
