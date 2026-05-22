"""Domestic multi-engine search provider without API keys."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from tools.base import ToolProvider
from tools.registry import register

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15
_DEFAULT_DELAY_MS = 1200
_DEFAULT_RESULTS_PER_ENGINE = 5
_DEFAULT_MERGED_RESULTS = 10
_DEFAULT_ENABLED_ENGINES = "bing_cn,bing_int,360,sogou,wechat"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class EngineSpec:
    engine_id: str
    display_name: str
    search_url_template: str
    homepage: str
    weight: float
    parser: str


_ENGINE_SPECS: dict[str, EngineSpec] = {
    "bing_cn": EngineSpec(
        engine_id="bing_cn",
        display_name="Bing CN",
        search_url_template="https://cn.bing.com/search?q={query}&ensearch=0",
        homepage="https://cn.bing.com/",
        weight=1.0,
        parser="bing",
    ),
    "bing_int": EngineSpec(
        engine_id="bing_int",
        display_name="Bing INT",
        search_url_template="https://cn.bing.com/search?q={query}&ensearch=1",
        homepage="https://cn.bing.com/",
        weight=0.95,
        parser="bing",
    ),
    "360": EngineSpec(
        engine_id="360",
        display_name="360",
        search_url_template="https://www.so.com/s?q={query}",
        homepage="https://www.so.com/",
        weight=0.9,
        parser="so360",
    ),
    "sogou": EngineSpec(
        engine_id="sogou",
        display_name="Sogou",
        search_url_template="https://www.sogou.com/web?query={query}",
        homepage="https://www.sogou.com/",
        weight=0.85,
        parser="sogou",
    ),
    "wechat": EngineSpec(
        engine_id="wechat",
        display_name="WeChat",
        search_url_template="https://wx.sogou.com/weixin?type=2&query={query}",
        homepage="https://wx.sogou.com/",
        weight=0.75,
        parser="wechat",
    ),
}


@register
class MultiSearchEngine(ToolProvider):
    tool_type = "search"
    provider_id = "multi_search_engine"
    display_name = "多引擎聚合搜索"
    description = "免 API Key 的国内多搜索引擎聚合，一阶段支持 Bing/360/Sogou/微信"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "enabled_engines_cn",
                "label": "启用引擎",
                "type": "text",
                "required": False,
                "default": _DEFAULT_ENABLED_ENGINES,
                "description": "逗号分隔，如 bing_cn,bing_int,360,sogou,wechat",
            },
            {
                "key": "max_results_per_engine",
                "label": "单引擎结果数",
                "type": "number",
                "required": False,
                "default": _DEFAULT_RESULTS_PER_ENGINE,
                "description": "每个搜索引擎最多提取多少条结果",
            },
            {
                "key": "max_merged_results",
                "label": "聚合结果上限",
                "type": "number",
                "required": False,
                "default": _DEFAULT_MERGED_RESULTS,
                "description": "多引擎去重后最多返回多少条结果",
            },
            {
                "key": "request_delay_ms",
                "label": "请求间隔(ms)",
                "type": "number",
                "required": False,
                "default": _DEFAULT_DELAY_MS,
                "description": "不同引擎之间的请求间隔，建议 1000-2000",
            },
            {
                "key": "timeout",
                "label": "超时时间(秒)",
                "type": "number",
                "required": False,
                "default": _DEFAULT_TIMEOUT,
                "description": "单次 HTTP 请求超时时间",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web using multiple domestic search engines. "
                    "Useful for Chinese company information, industry articles, "
                    "news, official announcements, and WeChat public account content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of merged results to return (default 8, max 20).",
                            "default": 8,
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        query = str(args["query"]).strip()
        if not query:
            raise ValueError("query is required")

        requested_results = min(max(int(args.get("max_results", 8)), 1), 20)
        timeout = int(self.config.get("timeout", _DEFAULT_TIMEOUT))
        delay_ms = max(int(self.config.get("request_delay_ms", _DEFAULT_DELAY_MS)), 0)
        per_engine_limit = max(int(self.config.get("max_results_per_engine", _DEFAULT_RESULTS_PER_ENGINE)), 1)
        merged_limit = max(int(self.config.get("max_merged_results", _DEFAULT_MERGED_RESULTS)), 1)
        final_limit = min(requested_results, merged_limit)
        enabled_engines = self._parse_enabled_engines(
            self.config.get("enabled_engines_cn", _DEFAULT_ENABLED_ENGINES)
        )
        log.info(
            "Multi search start query=%r engines=%s final_limit=%s per_engine_limit=%s",
            query,
            enabled_engines,
            final_limit,
            per_engine_limit,
        )

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        all_results: list[dict[str, Any]] = []
        successful_engines = 0

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            for index, engine_id in enumerate(enabled_engines):
                spec = _ENGINE_SPECS[engine_id]
                if index > 0 and delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)

                search_url = spec.search_url_template.format(query=quote_plus(query))
                started_at = time.perf_counter()
                try:
                    html = await self._fetch_search_page(client, spec, search_url, delay_ms)
                    parsed = self._parse_engine_results(spec, html, search_url, per_engine_limit)
                    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                    if parsed:
                        successful_engines += 1
                        all_results.extend(parsed)
                        log.info(
                            "Multi search engine=%s parsed=%s elapsed_ms=%s",
                            engine_id,
                            len(parsed),
                            elapsed_ms,
                        )
                    else:
                        log.info(
                            "Multi search engine=%s returned no parsed results elapsed_ms=%s query=%r",
                            engine_id,
                            elapsed_ms,
                            query,
                        )
                except Exception as exc:
                    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                    log.warning(
                        "Multi search engine=%s failed elapsed_ms=%s query=%r error=%s",
                        engine_id,
                        elapsed_ms,
                        query,
                        exc,
                    )

        merged = self._merge_results(all_results, final_limit)
        log.info(
            "Multi search complete query=%r successful_engines=%s raw_results=%s merged_results=%s",
            query,
            successful_engines,
            len(all_results),
            len(merged),
        )
        if not merged and successful_engines == 0:
            raise RuntimeError("No search engines returned usable results")
        return merged

    @staticmethod
    def _parse_enabled_engines(raw_value: Any) -> list[str]:
        raw_text = str(raw_value or _DEFAULT_ENABLED_ENGINES)
        engines: list[str] = []
        for token in raw_text.split(","):
            engine_id = token.strip().lower()
            if not engine_id:
                continue
            if engine_id not in _ENGINE_SPECS:
                log.warning("Ignoring unsupported search engine config: %s", engine_id)
                continue
            if engine_id not in engines:
                engines.append(engine_id)
        return engines or list(_ENGINE_SPECS.keys())

    async def _fetch_search_page(
        self,
        client: httpx.AsyncClient,
        spec: EngineSpec,
        search_url: str,
        delay_ms: int,
    ) -> str:
        response = await client.get(search_url)
        log.debug("Multi search HTTP engine=%s status=%s url=%s", spec.engine_id, response.status_code, search_url)
        if response.status_code not in (403, 429):
            response.raise_for_status()
            return response.text

        log.info("Refreshing session cookies for %s after HTTP %s", spec.engine_id, response.status_code)
        await client.get(spec.homepage)
        if delay_ms > 0:
            await asyncio.sleep(min(delay_ms, 2000) / 1000.0)

        retry = await client.get(search_url)
        retry.raise_for_status()
        return retry.text

    def _parse_engine_results(
        self,
        spec: EngineSpec,
        html: str,
        source_url: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        if spec.parser == "bing":
            results = self._parse_bing(soup, source_url)
        elif spec.parser == "so360":
            results = self._parse_360(soup, source_url)
        elif spec.parser == "sogou":
            results = self._parse_sogou(soup, source_url)
        elif spec.parser == "wechat":
            results = self._parse_wechat(soup, source_url)
        else:
            results = []

        if len(results) < max_results:
            generic_results = self._parse_generic_results(soup, spec, source_url)
            if generic_results:
                if not results:
                    log.info("Multi search engine=%s used generic parser fallback", spec.engine_id)
                else:
                    log.info(
                        "Multi search engine=%s supplemented parser-specific results with generic fallback",
                        spec.engine_id,
                    )
                seen_pairs = {
                    (
                        self._clean_text(item.get("title", "")).lower(),
                        self._clean_text(item.get("url", "")),
                    )
                    for item in results
                }
                for item in generic_results:
                    pair = (
                        self._clean_text(item.get("title", "")).lower(),
                        self._clean_text(item.get("url", "")),
                    )
                    if pair in seen_pairs:
                        continue
                    results.append(item)
                    seen_pairs.add(pair)
                    if len(results) >= max_results:
                        break

        normalized: list[dict[str, Any]] = []
        for rank, item in enumerate(results[:max_results], start=1):
            normalized_item = self._normalize_result(item, spec, source_url, rank)
            if normalized_item:
                normalized.append(normalized_item)
        if results and not normalized:
            log.info("Multi search engine=%s parsed candidates=%s but normalized=0", spec.engine_id, len(results))
        return normalized

    def _parse_bing(self, soup: BeautifulSoup, source_url: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        candidates = soup.select("li.b_algo") or soup.select("div.b_algo")
        for item in candidates:
            link = item.select_one("h2 a")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href", "")
            snippet = ""
            snippet_node = item.select_one(".b_caption p") or item.select_one(".b_algoSlug")
            if snippet_node:
                snippet = snippet_node.get_text(" ", strip=True)
            results.append({"title": title, "url": url, "snippet": snippet})
        return results

    def _parse_360(self, soup: BeautifulSoup, source_url: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        candidates = (
            soup.select("li.res-list")
            or soup.select("div.res-list")
            or soup.select("li.result")
            or soup.select("div.result")
        )
        for item in candidates:
            link = item.select_one("h3 a") or item.select_one("a[data-md]")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href", "")
            snippet_node = (
                item.select_one(".res-desc")
                or item.select_one("p")
                or item.select_one(".mh-detail")
            )
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            results.append({"title": title, "url": url, "snippet": snippet})
        return results

    def _parse_sogou(self, soup: BeautifulSoup, source_url: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        candidates = (
            soup.select("div.vrwrap")
            or soup.select("div.rb")
            or soup.select("div.results > div")
            or soup.select("div.results .vr-result")
        )
        for item in candidates:
            link = item.select_one("h3 a") or item.select_one("a[data-click]")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href", "")
            snippet_node = (
                item.select_one(".str-text")
                or item.select_one(".ft")
                or item.select_one(".text-layout")
                or item.select_one("p")
            )
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            results.append({"title": title, "url": url, "snippet": snippet})
        return results

    def _parse_wechat(self, soup: BeautifulSoup, source_url: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        candidates = (
            soup.select("ul.news-list li")
            or soup.select("div.news-box li")
            or soup.select("div.txt-box")
            or soup.select("div.wx-rb")
        )
        for item in candidates:
            link = item.select_one("h3 a") or item.select_one("a")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href", "")
            snippet_node = item.select_one(".txt-info") or item.select_one(".s-p") or item.select_one("p")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            results.append({"title": title, "url": url, "snippet": snippet})
        return results

    def _parse_generic_results(
        self,
        soup: BeautifulSoup,
        spec: EngineSpec,
        source_url: str,
    ) -> list[dict[str, str]]:
        search_host = urlparse(spec.homepage).netloc.lower()
        selectors = [
            "main a[href]",
            "ol a[href]",
            "ul a[href]",
            "div a[href]",
        ]
        results: list[dict[str, str]] = []
        seen: set[str] = set()

        for selector in selectors:
            for link in soup.select(selector):
                title = self._clean_text(link.get_text(" ", strip=True))
                raw_url = str(link.get("href", "")).strip()
                if not self._is_likely_result_link(title, raw_url):
                    continue

                resolved_url = self._resolve_result_url(raw_url, source_url)
                if not resolved_url:
                    continue

                resolved_host = urlparse(resolved_url).netloc.lower()
                if resolved_host == search_host:
                    continue

                key = self._canonical_key(resolved_url) or resolved_url
                if key in seen:
                    continue
                seen.add(key)

                container = self._result_container_for_link(link)
                snippet = self._snippet_from_container(container, title)
                results.append({"title": title, "url": resolved_url, "snippet": snippet})

                if len(results) >= max(_DEFAULT_MERGED_RESULTS * 2, 20):
                    return results

        return results

    def _normalize_result(
        self,
        item: dict[str, Any],
        spec: EngineSpec,
        source_url: str,
        rank: int,
    ) -> dict[str, Any] | None:
        title = self._clean_text(item.get("title", ""))
        raw_url = str(item.get("url", "")).strip()
        snippet = self._clean_text(item.get("snippet", ""))
        if not title or not raw_url:
            return None

        resolved_url = self._resolve_result_url(raw_url, source_url)
        if not resolved_url:
            return None

        domain = urlparse(resolved_url).netloc.lower()
        score = round(spec.weight - ((rank - 1) * 0.02), 4)
        return {
            "title": title,
            "url": resolved_url,
            "snippet": snippet,
            "engine": spec.engine_id,
            "rank": rank,
            "domain": domain,
            "score": score,
        }

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = " ".join(str(value or "").split())
        return text.strip()

    def _is_likely_result_link(self, title: str, raw_url: str) -> bool:
        if not title or len(title) < 4:
            return False
        if title in {"下一页", "上一页", "相关搜索", "更多", "首页"}:
            return False
        lowered = raw_url.lower()
        if lowered.startswith(("#", "javascript:", "mailto:", "tel:")):
            return False
        return True

    def _result_container_for_link(self, link) -> Any:
        current = link
        for _ in range(4):
            current = getattr(current, "parent", None)
            if current is None:
                break
            name = getattr(current, "name", "")
            if name in {"li", "article"}:
                return current
            classes = set(current.get("class", []))
            if classes & {"b_algo", "res-list", "vrwrap", "rb", "news-box", "txt-box", "result"}:
                return current
        return getattr(link, "parent", None)

    def _snippet_from_container(self, container: Any, title: str) -> str:
        if not container:
            return ""
        text = self._clean_text(container.get_text(" ", strip=True))
        if text.startswith(title):
            text = self._clean_text(text[len(title):])
        if len(text) > 220:
            text = text[:217] + "..."
        return text

    def _resolve_result_url(self, raw_url: str, source_url: str) -> str:
        candidate = html_unescape(raw_url.strip())
        candidate = urljoin(source_url, candidate)
        parsed = urlparse(candidate)
        query = parse_qs(parsed.query)

        for key in ("target", "url", "u", "ru"):
            if key in query and query[key]:
                nested = unquote(query[key][0]).strip()
                if nested.startswith("http://") or nested.startswith("https://"):
                    return nested

        return candidate if parsed.scheme in ("http", "https") else ""

    def _merge_results(self, results: list[dict[str, Any]], max_results: int) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in results:
            url_key = self._canonical_key(item.get("url", ""))
            title_key = self._clean_text(item.get("title", "")).lower()
            key = url_key or title_key
            if not key:
                continue

            existing = deduped.get(key)
            merged_engines = set()
            if existing:
                merged_engines.update(existing.get("engines", [existing.get("engine")]))
            merged_engines.update(item.get("engines", [item.get("engine")]))

            if existing is None or item.get("score", 0) > existing.get("score", 0):
                deduped[key] = dict(item)
                deduped[key]["engines"] = sorted(engine for engine in merged_engines if engine)
                continue

            existing["engines"] = sorted(engine for engine in merged_engines if engine)

        merged = sorted(
            deduped.values(),
            key=lambda item: (
                float(item.get("score", 0)),
                -int(item.get("rank", 999)),
            ),
            reverse=True,
        )

        for item in merged:
            if "engines" not in item and item.get("engine"):
                item["engines"] = [item["engine"]]

        return merged[:max_results]

    @staticmethod
    def _canonical_key(url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return ""

        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/")
        allowed_params = []
        query = parse_qs(parsed.query)
        for key in sorted(query):
            if key.startswith("utm_"):
                continue
            if key in {"spm", "from", "source"}:
                continue
            for value in query[key]:
                allowed_params.append(f"{key}={value}")
        query_part = "&".join(allowed_params)
        return f"{host}{path}?{query_part}" if query_part else f"{host}{path}"


def html_unescape(value: str) -> str:
    return (
        value.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
