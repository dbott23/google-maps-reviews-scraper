# Google Maps Reviews Scraper

Scrape reviews from any **Google Maps** business listing. Enter one or more place URLs and extract reviewer names, star ratings, review text, dates, local guide status, and owner responses — no Google API key required.

## Features

- Scrape up to **500 reviews per place**
- Run **multiple locations** in a single job
- Sort by **newest**, **most relevant**, **highest rating**, or **lowest rating**
- Extracts **owner responses** alongside each review
- Flags **Google Local Guides** (trusted reviewers)
- Captures review helpfulness votes
- Returns the **overall place rating** and total review count alongside individual reviews
- Runs on residential proxies — no IP blocks

## Use Cases

- **Reputation monitoring** — Track what customers say about your locations over time
- **Competitor analysis** — Understand rival businesses' strengths and weaknesses through their reviews
- **Market research** — Gather location-based consumer sentiment at scale
- **Lead generation** — Identify businesses with poor reputation scores as outreach prospects
- **Local SEO auditing** — Analyze review patterns, keywords, and response rates
- **AI training data** — Build labelled review datasets for sentiment models
- **Multi-location brands** — Aggregate reviews across 10, 100, or 1,000+ branches in one run

## How to Get a Place URL

1. Open [Google Maps](https://www.google.com/maps)
2. Search for any business or location
3. Click on the place to open its details panel
4. Copy the URL from your browser's address bar
5. Paste it into the `placeUrls` input field

The URL typically looks like:
```
https://www.google.com/maps/place/Eiffel+Tower/@48.858370,2.294481,15z/...
```

## Input

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `placeUrls` | Array | — | One or more Google Maps place URLs |
| `maxReviewsPerPlace` | Number | 50 | Reviews to fetch per location (max 500) |
| `sortBy` | String | `newest` | `newest`, `relevant`, `highest`, or `lowest` |

## Output

Each review is saved as a dataset item and exported as JSON, CSV, or Excel:

```json
{
  "place_name": "Eiffel Tower",
  "place_url": "https://www.google.com/maps/place/Eiffel+Tower/...",
  "place_rating": 4.7,
  "place_total_reviews": 243891,
  "reviewer_name": "John Smith",
  "is_local_guide": true,
  "reviewer_review_count": 47,
  "rating": 5,
  "date": "2 months ago",
  "text": "Absolutely stunning views from the top. Worth every penny!",
  "helpful_count": 12,
  "owner_response": "Thank you for visiting — we hope to see you again soon!"
}
```

## Frequently Asked Questions

**Does it require a Google API key?**
No. The scraper uses residential proxies to access Google Maps directly — no API credentials needed on your end.

**How many reviews can I scrape per place?**
Up to 500 per place URL per run. To get more, re-run with a different sort order to capture a different slice.

**Can I scrape multiple locations at once?**
Yes. Add as many place URLs as you need to the `placeUrls` array and the actor will process them sequentially.

**What does "Local Guide" mean?**
Google Local Guides are power-reviewers whose opinions many users treat as more credible. The `is_local_guide` field lets you filter or weight these.

**Does it capture owner responses?**
Yes. If the business owner replied to a review, the response is included in the `owner_response` field.

**Will it get blocked by Google?**
The actor uses residential proxy rotation to mimic real browser traffic. Block rates are low, but like any web scraping operation, occasional retries may occur.

## Pricing

- **$1.00 per 1,000 reviews** scraped
- Actor start: $0.00005 per run

Example: 500 reviews from each of 3 locations = 1,500 reviews = **$1.50** total.
