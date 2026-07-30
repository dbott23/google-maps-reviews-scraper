"""Google Maps Reviews Scraper using camoufox + residential proxies."""

import asyncio
import re

from camoufox.async_api import AsyncCamoufox

from src.scrapers._proxy import parse_proxy

_SORT_LABELS = {
    "relevant": "Most relevant",
    "newest": "Newest",
    "highest": "Highest rating",
    "lowest": "Lowest rating",
}


def _parse_rating(aria_label: str | None) -> float | None:
    if not aria_label:
        return None
    m = re.search(r"([\d.]+)\s*star", aria_label, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _parse_count(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"[\d,]+", text.replace(",", ""))
    return int(m.group().replace(",", "")) if m else None


async def _dismiss_consent(page) -> None:
    for sel in [
        "button[aria-label='Accept all']",
        "button[aria-label*='Accept']",
        "form[action*='consent'] button",
        "[id*='consent'] button",
    ]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                await asyncio.sleep(1)
                return
        except Exception:
            pass


async def _get_place_info(page) -> dict:
    """Extract place name, rating, and total review count."""
    info: dict = {"place_name": None, "place_rating": None, "place_total_reviews": None}

    # Place name — h1 is most reliable
    for sel in ["h1.DUwDvf", "h1[class*='fontHeadline']", "h1"]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=4000):
                info["place_name"] = (await el.inner_text()).strip() or None
                break
        except Exception:
            pass

    # Overall rating
    try:
        rating_el = page.locator("div.F7nice span[aria-hidden='true']").first
        if await rating_el.is_visible(timeout=3000):
            txt = (await rating_el.inner_text()).strip()
            info["place_rating"] = float(txt) if txt else None
    except Exception:
        pass

    # Total review count
    try:
        count_el = page.locator("div.F7nice span[aria-label*='review']").first
        if await count_el.is_visible(timeout=2000):
            aria = await count_el.get_attribute("aria-label")
            info["place_total_reviews"] = _parse_count(aria)
    except Exception:
        pass

    return info


async def _click_reviews_tab(page) -> bool:
    for sel in [
        "button[aria-label*='Reviews']",
        "[role='tab'][aria-label*='Reviews']",
        "button[jsaction*='tab'] span:has-text('Reviews')",
    ]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.click()
                await asyncio.sleep(2)
                print("[gmaps] clicked Reviews tab", flush=True)
                return True
        except Exception:
            pass
    print("[gmaps] Reviews tab not found, may already be on reviews", flush=True)
    return False


async def _apply_sort(page, sort_by: str) -> None:
    sort_label = _SORT_LABELS.get(sort_by, "Newest")
    # Sort button varies by Google Maps version
    for sort_sel in [
        "button[aria-label='Sort reviews']",
        "button[jsaction*='pane.sort']",
        "[aria-label*='Sort']",
    ]:
        try:
            btn = page.locator(sort_sel).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                await asyncio.sleep(1)
                # Select option
                for opt_sel in [
                    f"[role='menuitemradio']:has-text('{sort_label}')",
                    f"[role='option']:has-text('{sort_label}')",
                    f"li:has-text('{sort_label}')",
                ]:
                    try:
                        opt = page.locator(opt_sel).first
                        if await opt.is_visible(timeout=2000):
                            await opt.click()
                            await asyncio.sleep(2)
                            print(f"[gmaps] sorted by: {sort_label}", flush=True)
                            return
                    except Exception:
                        pass
        except Exception:
            pass


async def _find_feed(page):
    """Return the locator for the scrollable reviews container."""
    for sel in [
        "div[role='feed']",
        "div.m6QErb[aria-label]",
        "div.m6QErb",
    ]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                print(f"[gmaps] feed found with: {sel}", flush=True)
                return el, sel
        except Exception:
            pass
    return None, None


def _js_extract_reviews() -> str:
    """JavaScript that extracts all visible reviews from the DOM."""
    return """
    () => {
        const reviews = [];

        // Review containers — Google uses data-review-id or jstcache on review divs
        const containers = [
            ...document.querySelectorAll('[data-review-id]'),
            ...document.querySelectorAll('div.jftiEf'),
        ];

        // Deduplicate by element reference
        const seen = new Set();
        const unique = [];
        for (const el of containers) {
            if (!seen.has(el)) { seen.add(el); unique.push(el); }
        }

        for (const el of unique) {
            try {
                // Reviewer name — first substantial text block
                let reviewer_name = null;
                const nameEl = el.querySelector('.d4r55, [class*="fontBodyMedium"] .d4r55, button[jsaction*="reviewer"] .d4r55');
                if (nameEl) reviewer_name = nameEl.innerText.trim();
                if (!reviewer_name) {
                    // Fallback: aria-label on the reviewer button
                    const btn = el.querySelector('button[aria-label][jsaction*="reviewer"]');
                    if (btn) reviewer_name = btn.getAttribute('aria-label');
                }

                // Local Guide badge
                const lgEl = el.querySelector('.RfnDt, [class*="localGuide"], [class*="fontBodySmall"] span');
                const is_local_guide = lgEl ? lgEl.innerText.toLowerCase().includes('local guide') : false;

                // Reviewer review count (shown as "· X reviews")
                let reviewer_review_count = null;
                const lgText = lgEl ? lgEl.innerText : '';
                const rcMatch = lgText.match(/(\d+)\s*review/i);
                if (rcMatch) reviewer_review_count = parseInt(rcMatch[1]);

                // Star rating from aria-label
                let rating = null;
                const starEl = el.querySelector('span[aria-label*="star"]');
                if (starEl) {
                    const m = starEl.getAttribute('aria-label').match(/[\d.]+/);
                    if (m) rating = parseFloat(m[0]);
                }

                // Date (relative: "2 months ago")
                let date = null;
                const dateEl = el.querySelector('.rsqaWe, span[class*="fontBodySmall"]:last-of-type');
                if (dateEl) date = dateEl.innerText.trim() || null;

                // Review text — expand "More" if present (button may already be clicked)
                let text = null;
                const textEl = el.querySelector('.wiI7pd, [jslog*="excerpt"] span, span[class*="fontBodyMedium"]:not(.d4r55)');
                if (textEl) text = textEl.innerText.trim() || null;

                // Helpful/likes count
                let helpful_count = null;
                const likeBtn = el.querySelector('button[aria-label*="helpful"], button[jsaction*="voteHelpful"]');
                if (likeBtn) {
                    const m2 = likeBtn.innerText.trim().match(/\d+/);
                    if (m2) helpful_count = parseInt(m2[0]);
                }

                // Owner response
                let owner_response = null;
                const respEl = el.querySelector('.CDe7pd');
                if (respEl) owner_response = respEl.innerText.trim() || null;

                // Unique key for dedup
                const reviewId = el.getAttribute('data-review-id') || null;

                reviews.push({
                    _key: reviewId || (reviewer_name + '|' + (text || '').slice(0, 40)),
                    reviewer_name,
                    is_local_guide,
                    reviewer_review_count,
                    rating,
                    date,
                    text,
                    helpful_count,
                    owner_response,
                });
            } catch (e) {
                // skip malformed element
            }
        }
        return reviews;
    }
    """


async def _expand_reviews(page) -> None:
    """Click all 'More' buttons to expand truncated reviews."""
    try:
        buttons = await page.query_selector_all("button[aria-label*='See more'], button[jsaction*='pane.review.expandReview']")
        for btn in buttons[:30]:  # cap at 30 to avoid infinite loops
            try:
                await btn.click()
                await asyncio.sleep(0.1)
            except Exception:
                pass
    except Exception:
        pass


async def scrape_place(page, url: str, max_reviews: int, sort_by: str) -> list[dict]:
    print(f"[gmaps] loading {url}", flush=True)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"[gmaps] navigation error: {e}", flush=True)

    await asyncio.sleep(3)
    await _dismiss_consent(page)

    place_info = await _get_place_info(page)
    print(f"[gmaps] place: {place_info['place_name']!r}, rating: {place_info['place_rating']}", flush=True)

    await _click_reviews_tab(page)
    await _apply_sort(page, sort_by)

    feed_el, feed_sel = await _find_feed(page)

    seen_keys: set[str] = set()
    reviews: list[dict] = []
    stall = 0

    for i in range(300):
        if len(reviews) >= max_reviews:
            break

        await _expand_reviews(page)

        raw = await page.evaluate(_js_extract_reviews())
        new_found = 0
        for r in raw:
            key = r.pop("_key", None) or f"{r.get('reviewer_name')}|{str(r.get('text', ''))[:40]}"
            if key not in seen_keys:
                seen_keys.add(key)
                reviews.append({**place_info, **r})
                new_found += 1

        print(f"[gmaps] scroll {i}: total={len(reviews)} (+{new_found})", flush=True)

        if new_found == 0:
            stall += 1
            if stall >= 6:
                print("[gmaps] no new reviews after 6 scrolls, stopping", flush=True)
                break
        else:
            stall = 0

        # Scroll the feed
        if feed_el:
            try:
                await feed_el.evaluate("el => el.scrollBy(0, 800)")
            except Exception:
                await page.keyboard.press("End")
        else:
            await page.keyboard.press("End")

        await asyncio.sleep(1.5)

    return reviews[:max_reviews]


async def scrape(
    place_urls: list[str],
    max_reviews_per_place: int = 50,
    sort_by: str = "newest",
    get_proxy_url=None,
) -> list[dict]:
    proxy = None
    if get_proxy_url:
        try:
            proxy = await get_proxy_url() if asyncio.iscoroutinefunction(get_proxy_url) else get_proxy_url()
        except Exception:
            pass

    if proxy:
        masked = proxy.split("@")[-1] if "@" in proxy else proxy
        print(f"[gmaps] proxy: ...@{masked}", flush=True)
    else:
        print("[gmaps] no proxy (direct)", flush=True)

    proxy_opts = parse_proxy(proxy)
    all_reviews: list[dict] = []

    async with AsyncCamoufox(
        headless=True,
        proxy=proxy_opts,
        geoip=True,
        firefox_user_prefs={"security.sandbox.content.level": 0},
    ) as browser:
        page = await browser.new_page()

        for url in place_urls:
            try:
                reviews = await scrape_place(page, url, max_reviews_per_place, sort_by)
                all_reviews.extend(reviews)
                print(f"[gmaps] {len(reviews)} reviews from {url}", flush=True)
            except Exception as e:
                print(f"[gmaps] error on {url}: {e}", flush=True)

            await asyncio.sleep(3)

    return all_reviews
