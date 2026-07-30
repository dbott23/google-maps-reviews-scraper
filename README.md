# Google Maps Reviews Scraper

Scrape reviews from any **Google Maps** business listing. Enter one or more place URLs and extract reviewer names, star ratings, review text, dates, local guide status, and owner responses.

## Features

- Scrape up to **500 reviews per place**
- Supports **multiple locations** in a single run
- Sort by **newest**, **most relevant**, **highest rating**, or **lowest rating**
- Extracts **owner responses** to reviews
- Identifies **Google Local Guides**
- Works with residential proxies to avoid blocks

## How to Get a Place URL

1. Open [Google Maps](https://www.google.com/maps)
2. Search for any business or location
3. Click on the place to open its details
4. Copy the URL from your browser's address bar
5. Paste it into the `placeUrls` input

## Input

| Field | Type | Description |
|-------|------|-------------|
| `placeUrls` | Array | Google Maps place URLs to scrape |
| `maxReviewsPerPlace` | Number | Max reviews per place (default: 50, max: 500) |
| `sortBy` | String | `newest`, `relevant`, `highest`, or `lowest` |

## Output

Each review is saved as a dataset item:

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
  "owner_response": null
}
```

## Use Cases

- **Reputation monitoring** — Track what customers say about your business
- **Competitor analysis** — Understand competitor strengths and weaknesses
- **Market research** — Gather location-based consumer sentiment
- **Lead generation** — Identify businesses with poor reviews as sales prospects
- **Local SEO** — Analyze review patterns for local search optimization

## Pricing

- **$1.00 per 1,000 reviews** scraped
- Actor start fee: $0.00005 per run

Scraping 500 reviews from 3 locations = ~$0.0015 total.
