"""Google Maps Reviews Scraper — scrapes reviews from Google Maps place URLs."""

import asyncio

from apify import Actor

from src.scrapers import gmaps

CHECKPOINT_KEY = "SCRAPER_CHECKPOINT"


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        Actor.log.info(f"Input keys: {list(inp.keys())}")

        place_urls: list[str] = inp.get("placeUrls") or []
        max_reviews: int = max(1, min(int(inp.get("maxReviewsPerPlace") or 50), 500))
        sort_by: str = inp.get("sortBy") or "newest"

        if not place_urls:
            await Actor.fail(status_message="Input must include at least one Google Maps place URL.")
            return

        proxy_config = None
        try:
            proxy_config = await Actor.create_proxy_configuration(groups=["RESIDENTIAL"], country_code="US")
            Actor.log.info("Residential proxy configured (US exit for English UI)")
        except Exception as exc:
            Actor.log.warning(f"Proxy setup failed ({exc}) — running without proxy (may be blocked by Google)")

        checkpoint = await Actor.get_value(CHECKPOINT_KEY) or {}
        done: set[str] = set(checkpoint.get("done") or [])
        total_pushed: int = checkpoint.get("total_pushed") or 0

        failures: list[str] = []
        remaining = [u for u in place_urls if u not in done]
        Actor.log.info(f"{len(remaining)} places to scrape (of {len(place_urls)} total)")

        for url in remaining:
            Actor.log.info(f"Scraping: {url}")
            place_errors: list[str] = []
            pushed_here = 0

            # Push as reviews arrive so a timeout or a lost browser cannot discard the
            # work already done. push_data fires the billing event exactly once per
            # item, so the results must NOT be pushed again after scrape() returns.
            async def push_batch(batch: list[dict]) -> None:
                nonlocal total_pushed, pushed_here
                await Actor.push_data(batch)
                total_pushed += len(batch)
                pushed_here += len(batch)

            try:
                await gmaps.scrape(
                    place_urls=[url],
                    max_reviews_per_place=max_reviews,
                    sort_by=sort_by,
                    get_proxy_url=proxy_config.new_url if proxy_config else None,
                    errors=place_errors,
                    on_batch=push_batch,
                )
                failures.extend(place_errors)
            except Exception as exc:
                Actor.log.error(f"Error scraping {url}: {exc}")
                failures.append(f"{url}: {exc}")

            done.add(url)
            await Actor.set_value(CHECKPOINT_KEY, {"done": list(done), "total_pushed": total_pushed})
            Actor.log.info(f"  → {pushed_here} reviews (total: {total_pushed})")

        Actor.log.info(f"Done. Total reviews pushed: {total_pushed}")

        # A green run with an empty dataset tells the user nothing. Fail with the reason.
        if total_pushed == 0 and failures:
            await Actor.fail(
                status_message=(
                    f"No reviews scraped — all {len(failures)} place(s) failed. "
                    f"First error: {failures[0]}"
                )
            )
            return
        if total_pushed == 0:
            await Actor.set_status_message(
                f"No reviews found. The places may genuinely have none, or the input may not "
                f"match anything — check the run log for the requests that were made."
            )
        if failures:
            Actor.log.warning(
                f"{len(failures)} place(s) failed but {total_pushed} review(s) were "
                f"scraped from the rest. First error: {failures[0]}"
            )


if __name__ == "__main__":
    asyncio.run(main())
