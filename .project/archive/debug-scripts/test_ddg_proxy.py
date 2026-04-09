"""测试DuckDuckGo代理配置"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from duckduckgo_search import DDGS

def test_with_proxy():
    print("测试DuckDuckGo（显式配置代理）...")
    print("=" * 60)

    # 正确的代理配置格式
    proxy = "http://127.0.0.1:7890"

    try:
        print(f"\n使用代理: {proxy}")
        print("-" * 60)

        # 使用proxy参数（不是proxies）
        with DDGS(proxy=proxy, timeout=20) as ddgs:
            results = list(ddgs.text("Python programming", region="wt-wt", max_results=3))
            print(f"[OK] 找到 {len(results)} 条结果")

            if results:
                for i, r in enumerate(results, 1):
                    print(f"  {i}. {r.get('title', 'N/A')[:60]}")
                    print(f"     {r.get('href', 'N/A')[:80]}")
            else:
                print("  [WARNING] 返回空列表 - 可能DuckDuckGo检测到自动化请求")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_with_proxy()
