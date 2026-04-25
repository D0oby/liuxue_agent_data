from __future__ import annotations

import re
import json
from difflib import SequenceMatcher
from urllib.request import urlopen
from xml.etree import ElementTree
from urllib.parse import quote

import scrapy

from src.crawl.models import AdmissionsPayload, ApplicationDetails, AcademicPathway, LanguageTestScore
from src.crawl.parser import (
    build_source_fingerprint,
    canonicalize_url,
    extract_relevant_blocks,
    normalize_text,
    parse_academic_pathways,
    parse_application_details,
    parse_language_tests,
)


SEARCH_PRIORITY = 30
COURSE_PRIORITY = 10
GLOBAL_ENGLISH_URL = (
    "https://www.sydney.edu.au/study/applying/how-to-apply/international-students/"
    "english-language-requirements.html"
)
COURSES_SITEMAP_URL = "https://www.sydney.edu.au/courses/sitemap.xml"
RESOURCE_BLOCKLIST = {"image", "media", "font"}


class UsydAdmissionsSpider(scrapy.Spider):
    name = "usyd_admissions"
    allowed_domains = ["sydney.edu.au"]
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_TIMEOUT": 30,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30000,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
    }

    def __init__(self, seeds: list[dict], results: list[dict] | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.seeds = seeds
        self.results = results if results is not None else []
        self.global_english_text: str | None = None
        self.sitemap_course_urls = self._load_sitemap_course_urls()

    def start_requests(self):
        yield scrapy.Request(
            GLOBAL_ENGLISH_URL,
            callback=self.parse_global_english,
            meta={"playwright": True, "playwright_include_page": True},
            priority=SEARCH_PRIORITY,
        )
        for seed in self.seeds:
            sitemap_url = self._match_sitemap_url(seed["course_name"])
            if sitemap_url:
                yield self._build_course_request(sitemap_url, seed)
                continue
            if seed.get("source_url"):
                yield self._build_course_request(seed["source_url"], seed)
                continue
            query = quote(seed["course_name"])
            search_url = f"https://www.sydney.edu.au/s/search.html?collection=Usyd&query={query}"
            yield scrapy.Request(
                search_url,
                callback=self.parse_search_results,
                meta={"seed": seed},
                priority=SEARCH_PRIORITY,
            )

    async def parse_global_english(self, response):
        page = response.meta["playwright_page"]
        try:
            await self._expand_page(page)
            self.global_english_text = normalize_text(await page.locator("body").inner_text())
        finally:
            await page.close()

    def parse_search_results(self, response):
        seed = response.meta["seed"]
        hrefs = response.css("a::attr(href)").getall()
        candidates = []
        for href in hrefs:
            if "/courses/courses/pc/" not in href and "/courses/courses/pr/" not in href:
                continue
            if not href.startswith("http"):
                href = response.urljoin(href)
            candidates.append(href)
        if not candidates:
            self.results.append(
                {
                    "seed": seed,
                    "status": "dlq",
                    "stage": "discovery",
                    "error_code": "DISCOVERY_NO_MATCH",
                    "error_message": "No Sydney course page could be found from the official site search.",
                }
            )
            return
        yield self._build_course_request(self._select_best_candidate(seed, candidates), seed)

    def _build_course_request(self, url: str, seed: dict) -> scrapy.Request:
        return scrapy.Request(
            url,
            callback=self.parse_course,
            meta={
                "seed": seed,
            },
            priority=COURSE_PRIORITY,
        )

    async def parse_course(self, response):
        page = response.meta.get("playwright_page")
        seed = response.meta["seed"]
        try:
            if page is not None:
                await self._expand_page(page)
                text = normalize_text(await page.locator("body").inner_text())
            else:
                text = normalize_text(response.text)
            canonical_url = canonicalize_url(response.url)
            course_json = self._fetch_course_jsons(canonical_url)
            derived = self._extract_requirement_payload(course_json, text)
            academic_text = derived["academic_text"]
            language_text = derived["language_text"]
            application_text = derived["application_text"]
            language_tests = derived["language_tests"] or self._collect_language_tests(
                course_language_text=language_text,
                fallback_language_text=self.global_english_text,
                source_url=canonical_url,
            )
            for test in language_tests:
                if not test.get("source_url"):
                    test["source_url"] = derived["language_source_url"]
            supplementary_metadata = self._build_supplementary_metadata(derived["supplementary_text"])
            payload = AdmissionsPayload(
                course_id=seed["course_id"],
                course_name=seed["course_name"],
                cricos=seed["cricos"],
                source_url=response.url,
                canonical_url=canonical_url,
                academic_requirement_text=academic_text,
                academic_pathways=[AcademicPathway(**item) for item in parse_academic_pathways(academic_text)],
                raw_english_requirement=language_text,
                language_tests=[LanguageTestScore(**item) for item in language_tests],
                application_details=ApplicationDetails(**parse_application_details(application_text)),
                supplementary_metadata=supplementary_metadata,
                source_map={
                    "academic_requirement_text": derived["academic_source_url"],
                    "raw_english_requirement": derived["language_source_url"],
                    "application_details": derived["application_source_url"],
                    "supplementary_metadata": canonical_url,
                },
                notes=self._build_notes(text, extract_relevant_blocks(text)),
            )
            self.results.append(
                {
                    "seed": seed,
                    "status": "ok",
                    "payload": payload,
                    "source_url": response.url,
                    "source_fingerprint": build_source_fingerprint(payload),
                }
            )
        except Exception as exc:  # pragma: no cover - runtime safety net
            self.results.append(
                {
                    "seed": seed,
                    "status": "dlq",
                    "stage": "parse",
                    "error_code": "PARSE_AMBIGUOUS_CONTENT",
                    "error_message": str(exc),
                    "source_url": response.url,
                    "raw_payload_json": {
                        "canonical_url": canonicalize_url(response.url),
                        "text_excerpt": text[:1500] if "text" in locals() else "",
                    },
                }
            )
        finally:
            if page is not None:
                await page.close()

    def _build_notes(self, full_text: str, blocks: dict[str, str]) -> list[str]:
        notes: list[str] = []
        lowered = full_text.casefold()
        if "limited places" in lowered:
            notes.append("Course page mentions limited places.")
        if "quota applies" in lowered:
            notes.append("Course page mentions quota applies.")
        if not blocks["language"] and self.global_english_text:
            notes.append("Language requirements fell back to the central English requirements page.")
        return notes

    async def _expand_page(self, page) -> None:
        async def handle_route(route):
            if route.request.resource_type in RESOURCE_BLOCKLIST:
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", handle_route)
        await page.wait_for_load_state("domcontentloaded")
        for selector in ["button", "[role='button']", "summary", "[aria-expanded='false']"]:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(min(count, 40)):
                try:
                    await locator.nth(index).click(timeout=500)
                except Exception:
                    continue
        for label in ["International", "international"]:
            try:
                await page.get_by_text(label, exact=False).first.click(timeout=1000)
                break
            except Exception:
                continue
        await page.wait_for_timeout(800)

    def _select_best_candidate(self, seed: dict, candidates: list[str]) -> str:
        normalized_name = normalize_text(seed["course_name"]).casefold()

        def score(url: str) -> tuple[int, int]:
            canonical = canonicalize_url(url)
            score_value = 0
            if "/courses/courses/pc/" in canonical:
                score_value += 20
            if "/courses/courses/pr/" in canonical and self._is_research_course_name(seed["course_name"]):
                score_value += 30
            if seed["cricos"].casefold() in canonical.casefold():
                score_value += 5
            slug = canonical.rsplit("/", 1)[-1].replace(".html", "").replace("-", " ")
            overlap = len(set(normalized_name.split()) & set(slug.casefold().split()))
            score_value += overlap
            return (score_value, -len(canonical))

        return sorted(candidates, key=score, reverse=True)[0]

    def _load_sitemap_course_urls(self) -> list[str]:
        try:
            with urlopen(COURSES_SITEMAP_URL, timeout=30) as response:
                sitemap_xml = response.read()
        except Exception:
            return []

        try:
            root = ElementTree.fromstring(sitemap_xml)
        except ElementTree.ParseError:
            return []

        urls: list[str] = []
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//sm:loc", namespace):
            value = normalize_text(loc.text or "")
            if "/courses/courses/pc/" in value or "/courses/courses/pr/" in value:
                urls.append(value)
        return urls

    def _match_sitemap_url(self, course_name: str) -> str | None:
        normalized_name = self._normalize_course_name(course_name)
        if not normalized_name or not self.sitemap_course_urls:
            return None

        best_url = None
        best_score = 0.0
        is_research = self._is_research_course_name(course_name)
        for url in self.sitemap_course_urls:
            slug = url.rsplit("/", 1)[-1].replace(".html", "")
            normalized_slug = self._normalize_course_name(slug.replace("-", " "))
            if not normalized_slug:
                continue

            token_overlap = len(set(normalized_name.split()) & set(normalized_slug.split()))
            score = SequenceMatcher(None, normalized_name, normalized_slug).ratio() + (token_overlap * 0.08)
            if is_research and "/courses/courses/pr/" in url:
                score += 0.25
            if not is_research and "/courses/courses/pc/" in url:
                score += 0.05
            if score > best_score:
                best_score = score
                best_url = url

        if best_score >= 0.72:
            return best_url
        return None

    def _normalize_course_name(self, value: str) -> str:
        normalized = normalize_text(value).casefold()
        normalized = normalized.replace("&", " and ")
        normalized = re.sub(r"[()/:,]", " ", normalized)
        normalized = re.sub(r"\bthe\b", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _is_research_course_name(self, course_name: str) -> bool:
        lowered = normalize_text(course_name).casefold()
        return any(
            marker in lowered
            for marker in [
                "doctor of philosophy",
                "master of philosophy",
                "(research)",
                "research",
            ]
        )

    def _collect_language_tests(self, course_language_text: str, fallback_language_text: str | None, source_url: str) -> list[dict]:
        if course_language_text:
            return parse_language_tests(
                course_language_text,
                source_url=source_url,
                source_type="explicit_course_page",
                source_priority=1,
            )
        if fallback_language_text:
            return parse_language_tests(
                fallback_language_text,
                source_url=GLOBAL_ENGLISH_URL,
                source_type="global_standard_reference",
                source_priority=4,
            )
        return []

    def _fallback_academic_block(self, text: str) -> str:
        lowered = text.casefold()
        start = min(
            [lowered.find(marker) for marker in ["admission", "entry requirements", "academic requirements"] if lowered.find(marker) != -1],
            default=0,
        )
        end = lowered.find("requirements for award", start)
        if end == -1:
            end = start + 2400
        return text[start:end].strip()

    def _fallback_application_block(self, text: str) -> str:
        lowered = text.casefold()
        start = min(
            [lowered.find(marker) for marker in ["how to apply", "supplementary form", "portfolio", "limited places"] if lowered.find(marker) != -1],
            default=0,
        )
        return text[start : start + 1400].strip()

    def _build_supplementary_metadata(self, text: str) -> dict:
        lowered = text.casefold()
        return {
            "program_rules": [
                sentence.strip()
                for sentence in re.findall(r"[^.]*credit points[^.]*\.?", text, flags=re.IGNORECASE)
            ][:5],
            "award_requirements_detected": "requirements for award" in lowered,
            "rpl_detected": "credit for previous study" in lowered or "recognition of prior learning" in lowered,
        }

    def _fetch_course_jsons(self, canonical_url: str) -> dict[str, dict]:
        base_url = canonical_url[:-5] if canonical_url.endswith(".html") else canonical_url
        payloads: dict[str, dict] = {}
        for key, suffix in {
            "model": ".model.json",
            "coredata": ".coredata.json",
            "explorer": ".explorer.json",
        }.items():
            try:
                with urlopen(f"{base_url}{suffix}", timeout=30) as response:
                    payloads[key] = json.loads(response.read().decode("utf-8"))
            except Exception:
                payloads[key] = {}
        return payloads

    def _extract_requirement_payload(self, course_json: dict[str, dict], page_text: str) -> dict:
        model_data = course_json.get("model", {})
        coredata = course_json.get("coredata", {})
        explorer = course_json.get("explorer", {})
        core_content = explorer.get("content", {})
        model_items = model_data.get(":items", {})

        academic_chunks = [
            self._strip_html(core_content.get("course-admission-requirement-rte", {}).get("summary", "")),
            self._strip_html(model_items.get("nd-qualifications-pg", {}).get("description", "")),
            self._strip_html(model_items.get("nd-qualifications-pg", {}).get("additionalText", "")),
            self._strip_html(core_content.get("nd-qualifications-pg", {}).get("description", "")),
            self._strip_html(core_content.get("nd-qualifications-pg", {}).get("additionalText", "")),
        ]
        academic_text = self._select_best_academic_text(academic_chunks)

        application_chunks = [
            self._strip_html(model_items.get("nd-before-how-to-apply", {}).get("description", "")),
            self._strip_html(model_items.get("nd-submit-how-to-apply", {}).get("customOpenText", "")),
            self._strip_html(core_content.get("course-applying-for-admission-rte", {}).get("summary", "")),
            self._strip_html(core_content.get("course-how-to-apply", {}).get("intHowToApply", "")),
            self._strip_html(core_content.get("course-how-to-apply", {}).get("intDateForSemester", "")),
        ]
        extra_application = self._extract_application_sentences(
            academic_text,
            self._strip_html(core_content.get("course-opportunities-rte", {}).get("summary", "")),
            self._strip_html(core_content.get("course-applying-for-admission-rte", {}).get("summary", "")),
        )
        application_text = normalize_text(" ".join(chunk for chunk in [*application_chunks, extra_application] if chunk))

        explorer_tests = self._parse_explorer_entry_requirements(coredata)
        entry_requirement_years = coredata.get("attributes", {}).get("entryRequirements", {}).get("entryRequirementsByYear", [])
        language_text = normalize_text(
            " ".join(item["description"] for item in entry_requirement_years[0].get("entryRequirements", []))
        ) if entry_requirement_years else ""
        if not language_text:
            language_text = self._extract_english_section(self._strip_html(core_content.get("course-admission-requirement-rte", {}).get("summary", "")))
        if not language_text:
            language_text = self.global_english_text or ""

        canonical_url = model_data.get("link") or ""
        return {
            "academic_text": academic_text or self._fallback_academic_block(page_text),
            "language_text": language_text,
            "application_text": application_text or self._fallback_application_block(page_text),
            "language_tests": explorer_tests,
            "supplementary_text": normalize_text(" ".join(filter(None, [academic_text, application_text]))),
            "academic_source_url": f"{canonical_url[:-5]}.coredata.json" if canonical_url.endswith(".html") else canonical_url,
            "language_source_url": f"{canonical_url[:-5]}.explorer.json" if canonical_url.endswith(".html") and explorer_tests else (GLOBAL_ENGLISH_URL if self.global_english_text else canonical_url),
            "application_source_url": f"{canonical_url[:-5]}.model.json" if canonical_url.endswith(".html") else canonical_url,
        }

    def _select_best_academic_text(self, candidates: list[str]) -> str:
        best_text = ""
        best_score = -1
        for candidate in candidates:
            cleaned = normalize_text(candidate)
            if not cleaned:
                continue
            if "for academic requirements check" in cleaned.casefold():
                continue
            trimmed = re.split(r"english requirements", cleaned, flags=re.IGNORECASE)[0].strip() or cleaned
            lowered = trimmed.casefold()
            score = len(trimmed)
            for marker in [
                "admission",
                "eligible",
                "bachelor",
                "degree",
                "qualification",
                "honours",
                "master",
                "thesis",
                "experience",
                "graduate certificate",
                "graduate diploma",
                "cognate discipline",
                "equivalent qualification",
            ]:
                if marker in lowered:
                    score += 100
            if score > best_score:
                best_score = score
                best_text = trimmed
        return best_text

    def _parse_explorer_entry_requirements(self, explorer: dict) -> list[dict]:
        tests: list[dict] = []
        years = explorer.get("attributes", {}).get("entryRequirements", {}).get("entryRequirementsByYear", [])
        if not years:
            return tests
        for requirement in years[0].get("entryRequirements", []):
            description = normalize_text(requirement.get("description", ""))
            code_desc = normalize_text(requirement.get("codeDesc", ""))
            lowered = code_desc.casefold()
            test_name = None
            if "ielts" in lowered:
                test_name = "IELTS Academic"
            elif "toefl" in lowered:
                test_name = "TOEFL iBT"
            elif "pearsons" in lowered or "pte" in lowered:
                test_name = "PTE Academic"
            if not test_name:
                continue
            score_payload = self._extract_scores_from_requirement_description(test_name, description)
            tests.append(
                {
                    "test_name": test_name,
                    "overall": score_payload["overall"],
                    "component_scores": score_payload["component_scores"],
                    "raw_text": description,
                    "source_url": "",
                    "source_type": "explicit_course_page",
                    "source_priority": 1,
                }
            )
        return tests

    def _extract_scores_from_requirement_description(self, test_name: str, description: str) -> dict:
        numbers = re.findall(r"\d+(?:\.\d+)?", description)
        overall = numbers[0] if numbers else None
        component_scores: dict[str, str] = {}

        if test_name == "IELTS Academic":
            band_match = re.search(r"minimum result of (\d+(?:\.\d+)?) in each band", description, re.IGNORECASE)
            band = band_match.group(1) if band_match else (numbers[1] if len(numbers) > 1 else None)
            if band:
                component_scores = {
                    "listening": band,
                    "reading": band,
                    "speaking": band,
                    "writing": band,
                }
        elif test_name == "PTE Academic":
            each_match = re.search(r"minimum result of (\d+(?:\.\d+)?) in each band", description, re.IGNORECASE)
            band = each_match.group(1) if each_match else (numbers[1] if len(numbers) > 1 else None)
            if band:
                component_scores = {
                    "listening": band,
                    "reading": band,
                    "speaking": band,
                    "writing": band,
                }
        elif test_name == "TOEFL iBT":
            labels = ["reading", "listening", "writing", "speaking"]
            for label, value in zip(labels, numbers[1:5]):
                component_scores[label] = value

        return {"overall": overall, "component_scores": component_scores}

    def _extract_application_sentences(self, *texts: str) -> str:
        sentences: list[str] = []
        markers = ["limited places", "quota", "interview", "declaration form", "criminal record", "resume", "resumé", "referee", "portfolio", "personal statement"]
        for text in texts:
            for marker in markers:
                if marker in text.casefold():
                    sentences.append(text)
                    break
        return normalize_text(" ".join(sentences))

    def _extract_english_section(self, text: str) -> str:
        match = re.search(
            r"english requirements?(.*?)(important information|credit for previous study|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        return normalize_text(match.group(0))

    def _strip_html(self, value: str) -> str:
        if not value:
            return ""
        text = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
        text = re.sub(r"</p>|</li>|</tr>|</h\d>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return normalize_text(text)
