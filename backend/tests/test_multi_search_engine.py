"""Tests for the domestic multi search engine provider."""

import pytest

from agents.researcher import _build_active_tools
from tools import registry
from tools.multi_search_engine import MultiSearchEngine, _ENGINE_SPECS


def test_provider_registered():
    provider_cls = registry.get_provider_class("multi_search_engine")
    assert provider_cls is MultiSearchEngine


def test_provider_list_metadata_exposes_multi_search_engine():
    providers = registry.list_providers("search")
    provider_ids = {item["provider_id"] for item in providers}
    assert "multi_search_engine" in provider_ids


def test_parse_enabled_engines_filters_invalid_and_duplicates():
    engines = MultiSearchEngine._parse_enabled_engines("bing_cn,360,invalid,360,wechat")
    assert engines == ["bing_cn", "360", "wechat"]


def test_build_active_tools_uses_multi_search_engine_as_web_search():
    tools_config = {
        "search": {
            "active_provider": "multi_search_engine",
            "providers": {
                "multi_search_engine": {
                    "enabled_engines_cn": "bing_cn,360",
                    "request_delay_ms": 0,
                }
            },
        },
        "scraper": {
            "active_provider": "local_scraper",
            "providers": {"local_scraper": {"timeout": 5, "content_limit": 1000}},
        },
        "datasource": {"active_providers": [], "providers": {}},
    }

    tool_defs, executors = _build_active_tools(tools_config)

    assert any(item["function"]["name"] == "web_search" for item in tool_defs)
    assert isinstance(executors["web_search"], MultiSearchEngine)


@pytest.mark.asyncio
async def test_execute_merges_and_dedupes_results(monkeypatch):
    provider = MultiSearchEngine(
        {
            "enabled_engines_cn": "bing_cn,bing_int,360,sogou,wechat",
            "request_delay_ms": 0,
            "max_results_per_engine": 3,
            "max_merged_results": 6,
        }
    )

    html_by_engine = {
        "bing_cn": """
        <ul>
          <li class="b_algo">
            <h2><a href="https://example.com/report?utm_source=bing">Example Report</a></h2>
            <div class="b_caption"><p>Primary Bing result</p></div>
          </li>
        </ul>
        """,
        "bing_int": """
        <ul>
          <li class="b_algo">
            <h2><a href="https://example.org/news">Example News</a></h2>
            <div class="b_caption"><p>Bing INT result</p></div>
          </li>
        </ul>
        """,
        "360": """
        <ul>
          <li class="res-list">
            <h3><a href="https://example.com/report">Example Report</a></h3>
            <p class="res-desc">Duplicate from 360</p>
          </li>
          <li class="res-list">
            <h3><a href="https://360.com/unique">360 Unique</a></h3>
            <p class="res-desc">360 only</p>
          </li>
        </ul>
        """,
        "sogou": """
        <div class="vrwrap">
          <h3><a href="https://sogou.com/story">Sogou Story</a></h3>
          <p class="str-text">Sogou result</p>
        </div>
        """,
        "wechat": """
        <div class="news-box">
          <ul class="news-list">
            <li>
              <h3><a href="https://mp.weixin.qq.com/s/example">WeChat Article</a></h3>
              <p class="txt-info">WeChat result</p>
            </li>
          </ul>
        </div>
        """,
    }

    async def fake_fetch(_client, spec, _search_url, _delay_ms):
        return html_by_engine[spec.engine_id]

    monkeypatch.setattr(provider, "_fetch_search_page", fake_fetch)

    results = await provider.execute({"query": "测试公司", "max_results": 6})

    assert len(results) == 5
    assert results[0]["title"] == "Example Report"
    assert sorted(results[0]["engines"]) == ["360", "bing_cn"]
    assert any(item["engine"] == "wechat" for item in results)


def test_generic_parser_fallback_extracts_results():
    provider = MultiSearchEngine({})
    html = """
    <html>
      <body>
        <main>
          <div class="result-card">
            <a href="https://example.com/article">Fallback Article Title</a>
            <p>Fallback snippet content for parsing.</p>
          </div>
        </main>
      </body>
    </html>
    """

    parsed = provider._parse_engine_results(
        _ENGINE_SPECS["bing_cn"],
        html,
        "https://cn.bing.com/search?q=test",
        5,
    )

    assert parsed[0]["title"] == "Fallback Article Title"
    assert parsed[0]["url"] == "https://example.com/article"
    assert "Fallback snippet" in parsed[0]["snippet"]


def test_merge_results_keeps_highest_score_and_engine_list():
    provider = MultiSearchEngine({})
    merged = provider._merge_results(
        [
            {
                "title": "Same",
                "url": "https://example.com/a?utm_source=bing",
                "snippet": "from bing",
                "engine": "bing_cn",
                "rank": 1,
                "score": 1.0,
            },
            {
                "title": "Same",
                "url": "https://example.com/a",
                "snippet": "from 360",
                "engine": "360",
                "rank": 2,
                "score": 0.88,
            },
        ],
        10,
    )

    assert len(merged) == 1
    assert merged[0]["engine"] == "bing_cn"
    assert merged[0]["engines"] == ["360", "bing_cn"]
