from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from pathlib import Path

import scrapy
from parsel import Selector
from scrapy.http import Request, Response


class Ao3CommentsTagsSpider(scrapy.Spider):
    """Crawl AO3 search results and extract listing-card metadata."""

    name = "ao3_comments_tags"
    allowed_domains = ["archiveofourown.org"]
    custom_settings = {
        "AUTOTHROTTLE_ENABLED": True,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "COOKIES_ENABLED": True,
        "DOWNLOAD_DELAY": 2,
        "FEED_EXPORT_ENCODING": "utf-8",
        "LOG_LEVEL": "INFO",
        "RANDOMIZE_DOWNLOAD_DELAY": True,
    }

    def __init__(
        self,
        start_url: str | None = None,
        source_label: str | None = None,
        max_pages: str | int = 1,
        cookie_header: str | None = None,
        include_comments: str | bool = True,
        max_works: str | int | None = None,
        max_comment_pages: str | int | None = None,
        debug_dump_dir: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if not start_url:
            raise ValueError(
                "start_url is required, e.g. -a start_url='https://archiveofourown.org/works?...'"
            )

        self.start_url = start_url
        self.source_label = source_label
        self.max_pages = int(max_pages)
        self.include_comments = self._to_bool(include_comments)
        self.max_works = self._to_optional_int(max_works)
        self.max_comment_pages = self._to_optional_int(max_comment_pages)
        self.processed_work_count = 0
        self.debug_dump_dir = Path(debug_dump_dir) if debug_dump_dir else Path.cwd() / "ao3_debug"
        self.debug_dump_dir.mkdir(parents=True, exist_ok=True)
        self.request_cookies = {"view_adult": "true"}
        self.request_cookies.update(self._parse_cookie_header(cookie_header))

    async def start(self) -> Any:
        yield self._make_request(
            self.start_url,
            callback=self.parse_search,
            meta={"search_page": 1},
        )

    def start_requests(self) -> Any:
        # Keep backward compatibility with older Scrapy versions.
        yield self._make_request(
            self.start_url,
            callback=self.parse_search,
            meta={"search_page": 1},
        )

    def parse_search(self, response: Response) -> Any:
        work_nodes = response.css("ol.work.index.group > li.work.blurb")
        if not work_nodes:
            self.logger.warning(
                "No work cards found on %s. AO3 may have changed its markup or blocked the request.",
                response.url,
            )

        for work in work_nodes:
            if (
                self.max_works is not None
                and self.processed_work_count >= self.max_works
            ):
                self.logger.info(
                    "Reached max_works=%s; skipping remaining works.",
                    self.max_works,
                )
                return

            work_href = work.xpath(
                './/h4[contains(@class, "heading")]//a[contains(@href, "/works/")][not(@rel="author")]/@href'
            ).get()
            if not work_href:
                continue

            work_url = response.urljoin(work_href)
            listing_data = {
                "item_type": "work",
                "source_label": self.source_label,
                "work_id": self._extract_work_id(work_url),
                "search_page": response.meta["search_page"],
                "search_url": self.start_url,
                "work_url": work_url,
                "title": self._clean_text(
                    work.xpath(
                        './/h4[contains(@class, "heading")]//a[contains(@href, "/works/")][not(@rel="author")]/text()'
                    ).get()
                ),
                "authors": self._clean_list(
                    work.xpath('.//h4[contains(@class, "heading")]//a[@rel="author"]/text()').getall()
                ),
                "fandoms": self._clean_list(work.css("h5.fandoms a.tag::text").getall()),
                "summary": self._join_text(
                    work.css("blockquote.userstuff.summary, .summary blockquote.userstuff")
                    .xpath(".//text()")
                    .getall()
                ),
                "series": self._clean_list(
                    work.css("h6.series a::text").getall()
                ),
                "gift_recipients": self._clean_list(
                    work.css("h4.heading a[rel='bookmark']::text").getall()
                ),
                "icon_info": self._extract_icon_info(work),
                "listing_tags": self._extract_listing_tags(work),
                "published_or_updated": self._clean_text(
                    work.css("p.datetime::text").get()
                ),
                "language": self._extract_dd_text(work, "language"),
                "words": self._extract_dd_text(work, "words"),
                "chapters": self._extract_dd_text(work, "chapters"),
                "collections": self._extract_dd_text(work, "collections"),
                "comments_total": self._extract_dd_text(work, "comments"),
                "kudos": self._extract_dd_text(work, "kudos"),
                "bookmarks": self._extract_dd_text(work, "bookmarks"),
                "hits": self._extract_dd_text(work, "hits"),
                "title": self._clean_text(
                    work.xpath(
                        './/h4[contains(@class, "heading")]//a[contains(@href, "/works/")][not(@rel="author")]/text()'
                    ).get()
                ),
            }
            self.processed_work_count += 1
            self.logger.info(
                "Queueing work %s/%s: %s",
                self.processed_work_count,
                self.max_works if self.max_works is not None else "?",
                listing_data["work_url"],
            )
            yield listing_data

        current_page = int(response.meta["search_page"])
        if current_page >= self.max_pages:
            return

        next_page_href = self._extract_search_next(response)
        if next_page_href:
            yield self._make_request(
                response.urljoin(next_page_href),
                callback=self.parse_search,
                meta={"search_page": current_page + 1},
            )

    def parse_work(self, response: Response) -> Any:
        listing_data = response.meta["listing_data"]
        work_item = self._build_work_item(response, listing_data)
        self.logger.info(
            "Parsed work %s (%s)",
            work_item["work_id"],
            work_item["title"] or work_item["work_url"],
        )
        self._log_comment_page_state(response, work_item, stage="work")
        yield work_item

        if not self.include_comments:
            return

        yield from self._extract_comment_items(response, work_item)

        next_comments_href = self._extract_comments_next(response)
        next_comment_page = int(response.meta.get("comment_page", 1)) + 1
        if next_comments_href and self._can_follow_comment_page(next_comment_page):
            yield self._make_request(
                response.urljoin(next_comments_href),
                callback=self.parse_comments_page,
                meta={
                    "work_item": work_item,
                    "comment_page": next_comment_page,
                },
            )

    def parse_comments_page(self, response: Response) -> Any:
        work_item = response.meta["work_item"]
        self.logger.info(
            "Parsed comments page %s for work %s",
            int(response.meta.get("comment_page", 1)),
            work_item["work_id"],
        )
        self._log_comment_page_state(response, work_item, stage="comments")
        yield from self._extract_comment_items(response, work_item)

        next_comments_href = self._extract_comments_next(response)
        next_comment_page = int(response.meta.get("comment_page", 1)) + 1
        if next_comments_href and self._can_follow_comment_page(next_comment_page):
            yield self._make_request(
                response.urljoin(next_comments_href),
                callback=self.parse_comments_page,
                meta={
                    "work_item": work_item,
                    "comment_page": next_comment_page,
                },
            )

    def _build_work_item(
        self, response: Response, listing_data: dict[str, Any]
    ) -> dict[str, Any]:
        canonical_url = (
            response.xpath('//link[@rel="canonical"]/@href').get()
            or response.url.split("?")[0]
        )
        work_id = self._extract_work_id(canonical_url) or listing_data.get("work_id")

        detail_tags = {
            "ratings": self._extract_detail_tags(response, "rating"),
            "warnings": self._extract_detail_tags(response, "warning"),
            "categories": self._extract_detail_tags(response, "category"),
            "fandoms": self._extract_detail_tags(response, "fandom"),
            "relationships": self._extract_detail_tags(response, "relationship"),
            "characters": self._extract_detail_tags(response, "character"),
            "freeforms": self._extract_detail_tags(response, "freeform"),
        }

        return {
            "item_type": "work",
            "work_id": work_id,
            "work_url": canonical_url,
            "search_url": self.start_url,
            "search_page": listing_data.get("search_page"),
            "title": self._clean_text(
                response.css("h2.title.heading::text").get()
                or listing_data.get("title")
            ),
            "authors": self._clean_list(
                response.css("h3.byline.heading a[rel='author']::text").getall()
                or listing_data.get("authors", [])
            ),
            "summary": self._join_text(
                response.xpath(
                    '//*[contains(@class, "summary")]//*[contains(@class, "userstuff")]//text()'
                ).getall()
            ),
            "tags": detail_tags,
            "listing_tags": listing_data.get("listing_tags", {}),
            "language": self._clean_text(response.css("dd.language::text").get()),
            "published": self._clean_text(response.css("dd.published::text").get()),
            "updated": self._clean_text(response.css("dd.status::text").get()),
            "words": self._clean_text(response.css("dd.words::text").get()),
            "chapters": self._clean_text(response.css("dd.chapters::text").get()),
            "kudos": self._clean_text(response.css("dd.kudos::text").get()),
            "bookmarks": self._clean_text(response.css("dd.bookmarks::text").get()),
            "hits": self._clean_text(response.css("dd.hits::text").get()),
            "comments_total": self._clean_text(
                response.css("dd.comments::text").get()
                or listing_data.get("listing_comment_total")
            ),
        }

    def _extract_comment_items(
        self, response: Response, work_item: dict[str, Any]
    ) -> list[dict[str, Any]]:
        comment_nodes = response.xpath(
            '//ol[contains(@class, "thread")]//li[contains(concat(" ", normalize-space(@class), " "), " comment ")]'
        )
        if not comment_nodes:
            self.logger.warning(
                "No comment nodes found for work %s on %s",
                work_item["work_id"],
                response.url,
            )
            self._dump_comment_debug(response, work_item)
        items: list[dict[str, Any]] = []
        for comment in comment_nodes:
            comment_id = self._strip_prefix(comment.attrib.get("id"), "comment_")
            parent_id = self._strip_prefix(
                comment.xpath(
                    './parent::ol[contains(@class, "thread")]/parent::li[contains(@class, "comment")]/@id'
                ).get(),
                "comment_",
            )
            body_selector = comment.xpath(
                './/*[contains(concat(" ", normalize-space(@class), " "), " userstuff ")]'
            )
            body_html = "".join(body_selector.getall()).strip() if body_selector else ""
            body_text = self._join_text(body_selector.xpath(".//text()").getall())

            items.append(
                {
                    "item_type": "comment",
                    "work_id": work_item["work_id"],
                    "work_url": work_item["work_url"],
                    "work_title": work_item["title"],
                    "comment_page": int(response.meta.get("comment_page", 1)),
                    "comment_id": comment_id,
                    "parent_comment_id": parent_id,
                    "depth": self._extract_comment_depth(comment),
                    "author": self._clean_text(
                        comment.css("a[rel='author']::text").get()
                        or comment.xpath(
                            './/*[contains(@class, "byline")]//text()[normalize-space()][1]'
                        ).get()
                    ),
                    "posted_at": self._join_text(
                        comment.xpath(
                            './/*[contains(@class, "datetime")]//text()'
                        ).getall()
                    ),
                    "permalink": response.urljoin(
                        comment.xpath(
                            './/a[contains(@href, "#comment_")]/@href'
                        ).get()
                        or f"#comment_{comment_id}"
                    ),
                    "text": body_text,
                    "html": body_html,
                    "page_url": response.url,
                }
            )
        return items

    def _extract_listing_tags(self, work: Selector) -> dict[str, list[str]]:
        tags = {
            "ratings": self._clean_list(work.css("li.rating a.tag::text").getall()),
            "categories": self._clean_list(work.css("li.categories a.tag::text").getall()),
            "warnings": self._clean_list(work.css("li.warnings a.tag::text").getall()),
            "relationships": self._clean_list(
                work.css("li.relationships a.tag::text").getall()
            ),
            "characters": self._clean_list(work.css("li.characters a.tag::text").getall()),
            "freeforms": self._clean_list(work.css("li.freeforms a.tag::text").getall()),
            "fandoms": self._clean_list(work.css("h5.fandoms a.tag::text").getall()),
        }
        icon_info = self._extract_icon_info(work)
        if not tags["ratings"] and icon_info.get("rating_text"):
            tags["ratings"] = [str(icon_info["rating_text"])]
        if not tags["categories"] and icon_info.get("category_text"):
            tags["categories"] = [str(icon_info["category_text"])]
        if not tags["warnings"] and icon_info.get("warning_text"):
            tags["warnings"] = [str(icon_info["warning_text"])]
        return tags

    def _extract_icon_info(self, work: Selector) -> dict[str, Any]:
        icon_info: dict[str, Any] = {}
        icon_spans = work.css("ul.required-tags span")
        for span in icon_spans:
            classes = (span.attrib.get("class") or "").split()
            if "text" in classes:
                continue

            label = self._clean_text(
                span.css("span.text::text").get()
                or span.attrib.get("title")
                or span.attrib.get("aria-label")
                or span.attrib.get("alt")
            )
            semantic_classes = [
                cls
                for cls in classes
                if cls not in {"rating", "category", "warning", "complete", "iswip"}
            ]
            class_blob = " ".join(classes)

            if "rating" in classes:
                icon_info["rating_code"] = semantic_classes[0] if semantic_classes else None
                if label:
                    icon_info["rating_text"] = label
            elif "category" in classes:
                icon_info["category_code"] = semantic_classes[0] if semantic_classes else None
                if label:
                    icon_info["category_text"] = label
            elif "warning" in classes:
                icon_info["warning_code"] = semantic_classes[0] if semantic_classes else None
                if label:
                    icon_info["warning_text"] = label
            elif "complete" in classes or "iswip" in classes:
                icon_info["complete_code"] = semantic_classes[0] if semantic_classes else None
                if label:
                    icon_info["complete_text"] = label
            else:
                key = semantic_classes[0] if semantic_classes else (classes[0] if classes else "unknown")
                icon_info[key] = label or class_blob or True

        if not icon_info:
            text_values = self._clean_list(
                work.css("ul.required-tags span.text::text, ul.required-tags img::attr(alt), ul.required-tags img::attr(title)").getall()
            )
            if text_values:
                icon_info["raw_text"] = text_values
        return icon_info

    def _extract_detail_tags(self, response: Response, tag_group: str) -> list[str]:
        return self._clean_list(
            response.css(f"dd.{tag_group}.tags a.tag::text").getall()
        )

    def _extract_dd_text(self, node: Selector, class_name: str) -> str | None:
        value = self._join_text(
            node.css(f"dd.{class_name}").xpath(".//text()").getall()
        )
        if value is None:
            return None
        return re.sub(r"\s*/\s*", "/", value)

    def _extract_search_next(self, response: Response) -> str | None:
        return response.xpath(
            '(//ol[contains(@class, "pagination")]//a[starts-with(normalize-space(.), "Next")]/@href)[last()]'
        ).get()

    def _extract_comments_next(self, response: Response) -> str | None:
        candidates = [
            '(//div[contains(@id, "comment")]//ol[contains(@class, "pagination")]//a[starts-with(normalize-space(.), "Next")]/@href)[1]',
            '(//a[starts-with(normalize-space(.), "Next")][contains(@href, "show_comments")]/@href)[1]',
            '(//a[starts-with(normalize-space(.), "Next")][contains(@href, "#comments")]/@href)[1]',
        ]
        for xpath in candidates:
            href = response.xpath(xpath).get()
            if href:
                return href
        return None

    def _extract_comment_depth(self, comment: Selector) -> int:
        depth_value = comment.xpath(
            'count(ancestor::ol[contains(@class, "thread")])'
        ).get()
        if not depth_value:
            return 0
        return max(int(float(depth_value)) - 1, 0)

    def _make_request(
        self,
        url: str,
        callback: Any,
        meta: dict[str, Any] | None = None,
    ) -> Request:
        return scrapy.Request(
            url=self._set_query_params(url, view_adult="true"),
            callback=callback,
            cookies=self.request_cookies,
            meta=meta or {},
        )

    @staticmethod
    def _extract_work_id(url: str | None) -> str | None:
        if not url:
            return None
        match = re.search(r"/works/(\d+)", url)
        return match.group(1) if match else None

    @staticmethod
    def _strip_prefix(value: str | None, prefix: str) -> str | None:
        if not value:
            return None
        return value[len(prefix) :] if value.startswith(prefix) else value

    @staticmethod
    def _parse_cookie_header(cookie_header: str | None) -> dict[str, str]:
        if not cookie_header:
            return {}
        cookies: dict[str, str] = {}
        for part in cookie_header.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name:
                cookies[name] = value
        return cookies

    @staticmethod
    def _set_query_params(url: str, **params: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        for key, value in params.items():
            query[key] = value
        return urlunparse(
            parsed._replace(query=urlencode(query, doseq=True))
        )

    @staticmethod
    def _to_bool(value: str | bool) -> bool:
        if isinstance(value, bool):
            return value
        return value.strip().lower() not in {"0", "false", "no", "off"}

    @staticmethod
    def _to_optional_int(value: str | int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        value = value.strip()
        if not value:
            return None
        return int(value)

    def _can_follow_comment_page(self, page_number: int) -> bool:
        if self.max_comment_pages is None:
            return True
        if page_number <= self.max_comment_pages:
            return True
        self.logger.info(
            "Reached max_comment_pages=%s; stopping comment pagination.",
            self.max_comment_pages,
        )
        return False

    def _log_comment_page_state(
        self, response: Response, work_item: dict[str, Any], stage: str
    ) -> None:
        comment_threads = response.xpath(
            '//ol[contains(@class, "thread")]//li[contains(concat(" ", normalize-space(@class), " "), " comment ")]'
        )
        comment_container_count = len(
            response.xpath('//*[contains(@id, "comment")]')
        )
        comments_heading = self._clean_text(
            response.xpath(
                'string((//*[self::h3 or self::h4][contains(translate(normalize-space(.), "COMMENTS", "comments"), "comments")])[1])'
            ).get()
        )
        next_comments_href = self._extract_comments_next(response)
        self.logger.info(
            "Comment page state [%s] work=%s url=%s comment_nodes=%s comment_containers=%s heading=%r next=%r",
            stage,
            work_item["work_id"],
            response.url,
            len(comment_threads),
            comment_container_count,
            comments_heading,
            next_comments_href,
        )

    def _dump_comment_debug(
        self, response: Response, work_item: dict[str, Any]
    ) -> None:
        page_number = int(response.meta.get("comment_page", 1))
        stem = f"work_{work_item['work_id']}_comments_page_{page_number}"
        html_path = self.debug_dump_dir / f"{stem}.html"
        meta_path = self.debug_dump_dir / f"{stem}.txt"
        comment_heading = self._clean_text(
            response.xpath(
                'string((//*[self::h3 or self::h4][contains(translate(normalize-space(.), "COMMENTS", "comments"), "comments")])[1])'
            ).get()
        )
        comment_container_count = len(response.xpath('//*[contains(@id, "comment")]'))
        comment_node_count = len(
            response.xpath(
                '//ol[contains(@class, "thread")]//li[contains(concat(" ", normalize-space(@class), " "), " comment ")]'
            )
        )
        next_comments_href = self._extract_comments_next(response)

        html_path.write_bytes(response.body)
        meta_path.write_text(
            "\n".join(
                [
                    f"url={response.url}",
                    f"status={response.status}",
                    f"work_id={work_item['work_id']}",
                    f"title={work_item.get('title')}",
                    f"comment_page={page_number}",
                    f"comment_heading={comment_heading}",
                    f"comment_container_count={comment_container_count}",
                    f"comment_node_count={comment_node_count}",
                    f"next_comments_href={next_comments_href!r}",
                ]
            ),
            encoding="utf-8",
        )
        self.logger.info(
            "Saved comment debug dump for work %s to %s",
            work_item["work_id"],
            html_path,
        )

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    def _clean_list(self, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = self._clean_text(value)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    def _join_text(self, values: list[str]) -> str | None:
        return self._clean_text(" ".join(value.strip() for value in values if value.strip()))
