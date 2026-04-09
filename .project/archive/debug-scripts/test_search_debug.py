"""测试中大咨询集团的搜索问题 - 详细日志版本"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# 添加backend到路径
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# 设置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# 导入必要的模块
from agents.researcher import research
from config import load_settings, DEFAULT_TOOLS_CONFIG

async def test_search():
    """测试中大咨询集团的搜索"""

    # 模拟公司信息
    company_profile = {
        "company_name": "中大咨询集团",
        "project_name": "中大咨询集团尽调",
        "bd_code": "TEST001",
        "industry": "咨询服务",
        "is_listed": "否",
    }

    # 加载配置
    settings = load_settings()
    ai_config = settings.get("ai_config", {})
    researcher_cfg = ai_config.get("researcher", {})
    tools_config = settings.get("tools", DEFAULT_TOOLS_CONFIG)

    log.info("=" * 80)
    log.info("开始测试：中大咨询集团")
    log.info("=" * 80)
    log.info(f"公司信息: {json.dumps(company_profile, ensure_ascii=False, indent=2)}")
    log.info(f"搜索工具: {tools_config.get('search', {}).get('active_provider', 'unknown')}")
    log.info(f"抓取工具: {tools_config.get('scraper', {}).get('active_provider', 'unknown')}")
    log.info(f"数据源: {tools_config.get('datasource', {}).get('active_providers', [])}")
    log.info("=" * 80)

    try:
        # 执行研究
        log.info("\n开始执行 research() 函数...")
        result = await research(
            company_profile=company_profile,
            ai_config=researcher_cfg,
            tools_config=tools_config,
        )

        log.info("\n" + "=" * 80)
        log.info("研究结果:")
        log.info("=" * 80)
        log.info(f"结果类型: {type(result)}")
        log.info(f"结果内容:\n{json.dumps(result, ensure_ascii=False, indent=2)}")
        log.info("=" * 80)

        # 保存完整结果
        output_file = Path("test_search_result.json")
        output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"\n完整结果已保存到: {output_file.absolute()}")

        # 分析结果
        research_text = result.get("research", "")
        if "名称指向模糊" in research_text or "未能确认" in research_text:
            log.warning("\n⚠️ 检测到搜索失败的特征语句")
            log.warning("可能的原因:")
            log.warning("1. DuckDuckGo 在中国大陆被屏蔽")
            log.warning("2. 搜索关键词不够精确")
            log.warning("3. 该公司确实信息较少")
        else:
            log.info("\n✓ 搜索似乎成功获取了信息")

    except Exception as e:
        log.error(f"\n❌ 执行失败: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_search())
