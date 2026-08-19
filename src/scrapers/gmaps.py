"""Google Maps Reviews Scraper using camoufox + residential proxies."""

import asyncio
import json
import re
import urllib.parse

from camoufox.async_api import AsyncCamoufox

from src.scrapers._proxy import parse_proxy

# Reviews shown on the place overview panel before the Reviews pane is opened.
_OVERVIEW_PREVIEW_MAX = 3

_BROWSER_GONE_MARKERS = (
    "has been closed",
    "target closed",
    "browser closed",
    "connection closed",
)


def _browser_is_gone(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _BROWSER_GONE_MARKERS)

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
        "button:has-text('Accept all')",
        "button:has-text('Tout accepter')",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Aceptar todo')",
        "form[action*='consent'] button[type='submit']",
        "form[action*='consent'] button",
        "[id*='consent'] button",
    ]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                await asyncio.sleep(2)
                print("[gmaps] dismissed consent/cookie dialog", flush=True)
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


# The overview panel shows 3 preview reviews; the real list only appears after the
# Reviews tab is opened. "Write a review" also matches aria-label*='review', and
# clicking it opens a sign-in dialog while leaving the overview panel underneath —
# which is exactly how this actor silently degraded to 3 reviews per place. So the
# tab candidates are ordered most-specific-first, "Write/Add a review" is excluded,
# and every click is verified against a control that only exists on the reviews pane.
_REVIEW_TAB_SELECTORS = [
    "[role='tab'][aria-label^='Reviews']",
    "button[aria-label^='Reviews']",
    "[role='tab']:has-text('Reviews')",
    "button[jsaction*='tab'] span:has-text('Reviews')",
    (
        "button[aria-label*='review' i]"
        ":not([aria-label*='Write' i]):not([aria-label*='Add' i])"
    ),
]

_REVIEWS_PANE_MARKERS = [
    "button[aria-label*='Sort' i]",
    "button[jsaction*='pane.sort']",
    "button[data-value='Sort']",
    "[aria-label='Refine reviews']",
]


async def _on_reviews_pane(page) -> bool:
    """True when a control that only exists on the reviews pane is visible."""
    for sel in _REVIEWS_PANE_MARKERS:
        try:
            if await page.locator(sel).first.is_visible(timeout=1500):
                return True
        except Exception:
            pass
    return False


async def _log_tab_candidates(page) -> None:
    """Dump the tab/button DOM so a future break can be diagnosed from the log alone."""
    try:
        found = await page.evaluate(
            """() => Array.from(document.querySelectorAll("[role='tab'], button[aria-label]"))
                .map(e => ({
                    role: e.getAttribute('role'),
                    aria: e.getAttribute('aria-label'),
                    text: (e.innerText || '').trim().slice(0, 24),
                }))
                .filter(e => (e.aria || e.text))
                .slice(0, 25)"""
        )
        print(f"[gmaps] tab candidates: {json.dumps(found)[:1200]}", flush=True)
    except Exception as exc:
        print(f"[gmaps] could not dump tab candidates: {exc}", flush=True)


async def _click_reviews_tab(page) -> bool:
    for sel in _REVIEW_TAB_SELECTORS:
        try:
            el = page.locator(sel).first
            if not await el.is_visible(timeout=4000):
                continue
            aria = await el.get_attribute("aria-label")
            await el.click()
            await asyncio.sleep(3)
        except Exception:
            continue

        if await _on_reviews_pane(page):
            print(f"[gmaps] opened Reviews pane via {sel} (aria={aria!r})", flush=True)
            return True

        # Wrong target (often a dialog over the overview panel) — close and try the next.
        print(
            f"[gmaps] {sel} (aria={aria!r}) did not open the reviews pane, trying next",
            flush=True,
        )
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)
        except Exception:
            pass

    if await _on_reviews_pane(page):
        print("[gmaps] already on the reviews pane", flush=True)
        return True

    print("[gmaps] could not open the Reviews pane", flush=True)
    await _log_tab_candidates(page)
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


def _force_english(url: str) -> str:
    """Append hl=en&gl=us so Google Maps renders in English regardless of proxy geo.

    The English UI is required because the Reviews tab / Sort controls are matched
    by their English label text; a localized UI (e.g. 'Recensioni') breaks them.
    """
    if "hl=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}hl=en&gl=us"


def _extract_place_name(url: str) -> str | None:
    m = re.search(r"/place/([^/@?]+)[/@?]", url)
    if m:
        name = m.group(1)
        if name:
            return urllib.parse.unquote_plus(name)
    return None


async def _search_and_open_first_result(page, place_name: str) -> bool:
    search_url = _force_english(f"https://www.google.com/maps/search/{urllib.parse.quote(place_name)}")
    print(f"[gmaps] place URL had no panel — searching: {place_name}", flush=True)
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        print(f"[gmaps] search navigation failed: {e}", flush=True)
        return False
    for sel in ["a.hfpxzc", ".Nv2PK a", "[data-result-index='0'] a"]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=5000):
                await el.click()
                await asyncio.sleep(3)
                print(f"[gmaps] clicked first search result", flush=True)
                return True
        except Exception:
            pass
    print(f"[gmaps] could not click first search result", flush=True)
    return False


# Dynamically scroll the reviews list. Google dropped div[role='feed'] and keeps
# reshuffling its obfuscated class names, so instead of hardcoding a selector we
# walk up from a review element to its actual scrollable ancestor and scroll that.
_SCROLL_REVIEWS_JS = """
() => {
    const rev = document.querySelector('[data-review-id], div.jftiEf');
    if (!rev) return false;
    let el = rev.parentElement;
    while (el && el.scrollHeight <= el.clientHeight + 4) el = el.parentElement;
    if (!el) return false;
    el.scrollBy(0, Math.max(el.clientHeight * 0.9, 800));
    return true;
}
"""


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
                const rcMatch = lgText.match(/(\\d+)\\s*review/i);
                if (rcMatch) reviewer_review_count = parseInt(rcMatch[1]);

                // Star rating — use stable Google class (language-agnostic)
                // span[aria-label*="star"] fails when proxy returns non-English UI
                let rating = null;
                const starEl = el.querySelector('span.kvMYJc, span[role="img"][aria-label]');
                if (starEl) {
                    const m = starEl.getAttribute('aria-label').match(/[\\d.]+/);
                    if (m) {
                        const v = parseFloat(m[0]);
                        if (v >= 1 && v <= 5) rating = v;
                    }
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
                    const m2 = likeBtn.innerText.trim().match(/\\d+/);
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


# Playwright's default click timeout is 30s. A "See more" button that is covered or
# detached therefore blocks for 30s, and 30 of them stall the scroll loop for 15
# minutes — long enough to burn the whole run timeout without scraping anything.
_EXPAND_CLICK_TIMEOUT_MS = 1500
_EXPAND_BUDGET_S = 10.0


async def _expand_reviews(page) -> None:
    """Click 'More' buttons to expand truncated reviews, within a fixed time budget."""
    deadline = asyncio.get_event_loop().time() + _EXPAND_BUDGET_S
    try:
        buttons = await page.query_selector_all(
            "button[aria-label*='See more'], button[jsaction*='pane.review.expandReview']"
        )
        for btn in buttons[:30]:  # cap at 30 to avoid infinite loops
            if asyncio.get_event_loop().time() > deadline:
                print("[gmaps] expand budget spent, moving on", flush=True)
                break
            try:
                await btn.click(timeout=_EXPAND_CLICK_TIMEOUT_MS)
                await asyncio.sleep(0.1)
            except Exception as exc:
                if _browser_is_gone(exc):
                    raise
    except Exception as exc:
        if _browser_is_gone(exc):
            raise
        print(f"[gmaps] expand skipped: {exc}", flush=True)


async def scrape_place(
    page,
    url: str,
    max_reviews: int,
    sort_by: str,
    on_batch=None,
) -> list[dict]:
    # Pre-accept Google consent by visiting google.com first
    try:
        await page.goto("https://www.google.com/?hl=en&gl=us", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await _dismiss_consent(page)
        await asyncio.sleep(2)
        print(f"[gmaps] pre-consent step done, current url: {page.url[:60]}", flush=True)
    except Exception as e:
        print(f"[gmaps] pre-consent step failed: {e}", flush=True)

    url = _force_english(url)
    print(f"[gmaps] loading {url}", flush=True)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"[gmaps] navigation error: {e}", flush=True)

    await asyncio.sleep(3)

    # If redirected to consent page, handle it
    current_url = page.url
    if "consent.google" in current_url:
        print(f"[gmaps] consent redirect detected: {current_url[:80]}", flush=True)
        await _dismiss_consent(page)
        await asyncio.sleep(3)
    else:
        await _dismiss_consent(page)

    # If URL resolved to coordinate view without a place panel (place name stripped),
    # fall back to a search so we still get the right place panel
    if "/place//@" in page.url:
        place_name = _extract_place_name(url)
        if place_name:
            await _search_and_open_first_result(page, place_name)
            await _dismiss_consent(page)

    print(f"[gmaps] page url: {page.url[:80]}", flush=True)

    # Wait for place panel (h1 is the place name)
    for wait_sel in ["h1.DUwDvf", "h1", "[data-item-id]"]:
        try:
            await page.wait_for_selector(wait_sel, timeout=10000)
            print(f"[gmaps] place panel ready ({wait_sel})", flush=True)
            break
        except Exception:
            pass

    place_info = await _get_place_info(page)
    print(f"[gmaps] place: {place_info['place_name']!r}, rating: {place_info['place_rating']}", flush=True)

    # Panel didn't load (e.g. a URL pasted without the place-id `data=` hash) —
    # recover by searching for the place name and opening the first result.
    if not place_info.get("place_name"):
        pname = _extract_place_name(url)
        if pname and await _search_and_open_first_result(page, pname):
            await _dismiss_consent(page)
            for wait_sel in ["h1.DUwDvf", "h1"]:
                try:
                    await page.wait_for_selector(wait_sel, timeout=10000)
                    break
                except Exception:
                    pass
            place_info = await _get_place_info(page)
            print(f"[gmaps] place (after search): {place_info['place_name']!r}", flush=True)

    pane_opened = await _click_reviews_tab(page)
    if pane_opened:
        # Wait for review elements to appear in the DOM
        try:
            await page.wait_for_selector("[data-review-id], div.jftiEf", timeout=10000)
            print("[gmaps] reviews visible in DOM", flush=True)
        except Exception:
            print("[gmaps] no review elements found after tab click", flush=True)

    await _apply_sort(page, sort_by)

    seen_keys: set[str] = set()
    reviews: list[dict] = []
    stall = 0

    for i in range(300):
        if len(reviews) >= max_reviews:
            break

        try:
            await _expand_reviews(page)
            raw = await page.evaluate(_js_extract_reviews())
        except Exception as exc:
            if _browser_is_gone(exc):
                print(
                    f"[gmaps] browser closed after {len(reviews)} review(s) — "
                    f"keeping the partial result ({exc})",
                    flush=True,
                )
                break
            raise
        new_found = 0
        for r in raw:
            key = r.pop("_key", None) or f"{r.get('reviewer_name')}|{str(r.get('text', ''))[:40]}"
            if key not in seen_keys:
                seen_keys.add(key)
                reviews.append({**place_info, **r})
                new_found += 1

        print(f"[gmaps] scroll {i}: total={len(reviews)} (+{new_found})", flush=True)

        # Hand new reviews to the caller as they arrive. A run that later times out or
        # loses the browser then keeps everything scraped up to that point.
        if new_found and on_batch is not None:
            await on_batch(reviews[-new_found:])

        if new_found == 0:
            stall += 1
            # Be patient while the FIRST batch is still loading (slow residential
            # proxies can take 15-30s after the sort reload); once reviews are
            # flowing, stop promptly after 6 empty scrolls.
            limit = 15 if not reviews else 6
            if stall >= limit:
                print(f"[gmaps] no new reviews after {stall} scrolls, stopping", flush=True)
                break
        else:
            stall = 0

        # Scroll the reviews list (dynamically finds the scrollable container).
        # camoufox occasionally dies mid-scrape ("Target page, context or browser has
        # been closed"); keep the reviews collected so far instead of losing the lot.
        try:
            scrolled = await page.evaluate(_SCROLL_REVIEWS_JS)
            if not scrolled:
                await page.keyboard.press("End")
        except Exception as exc:
            if _browser_is_gone(exc):
                print(
                    f"[gmaps] browser closed after {len(reviews)} review(s) — "
                    f"keeping the partial result ({exc})",
                    flush=True,
                )
                break
            print(f"[gmaps] scroll failed ({exc}), retrying", flush=True)

        await asyncio.sleep(1.5)

    # Google's overview panel carries a handful of preview reviews. Returning those as
    # if they were a real scrape is how this actor silently shipped 3 reviews for a
    # place with 492k of them — bill the user for junk and look successful doing it.
    if not pane_opened and len(reviews) <= _OVERVIEW_PREVIEW_MAX:
        raise RuntimeError(
            f"Only {len(reviews)} preview review(s) were reachable and the Reviews pane "
            "never opened — Google has likely changed the place-panel layout. Refusing "
            "to return a partial result."
        )

    return reviews[:max_reviews]


async def scrape(
    place_urls: list[str],
    max_reviews_per_place: int = 50,
    sort_by: str = "newest",
    get_proxy_url=None,
    errors: list[str] | None = None,
    on_batch=None,
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
        locale="en-US",
        firefox_user_prefs={"security.sandbox.content.level": 0},
    ) as browser:
        page = await browser.new_page()

        for url in place_urls:
            try:
                reviews = await scrape_place(
                    page, url, max_reviews_per_place, sort_by, on_batch=on_batch
                )
                all_reviews.extend(reviews)
                print(f"[gmaps] {len(reviews)} reviews from {url}", flush=True)
            except Exception as e:
                print(f"[gmaps] error on {url}: {e}", flush=True)
                if errors is not None:
                    errors.append(f"{url}: {e}")
                # A dead browser fails every remaining URL instantly — try a fresh page.
                if _browser_is_gone(e):
                    try:
                        page = await browser.new_page()
                        print("[gmaps] recovered with a fresh page", flush=True)
                    except Exception as exc2:
                        print(f"[gmaps] browser unrecoverable: {exc2}", flush=True)
                        break

            await asyncio.sleep(3)

    return all_reviews
