# transfermarkt-api

This project provides a lightweight and easy-to-use interface for extracting data from [Transfermarkt](https://www.transfermarkt.com/) 
by applying web scraping processes and offering a RESTful API service via FastAPI. With this service, developers can 
seamlessly integrate Transfermarkt data into their applications, websites, or data analysis pipelines.

Please note that the deployed application is used only for testing purposes and has a rate limiting 
feature enabled. If you'd like to customize it, consider hosting in your own cloud service. 

### API Swagger
https://transfermarkt-api.fly.dev/

### Running Locally

````bash
# Clone the repository
$ git clone https://github.com/felipeall/transfermarkt-api.git

# Go to the project's root folder
$ cd transfermarkt-api

# Instantiate a Poetry virtual env
$ poetry shell

# Install the dependencies
$ poetry install --no-root

# (optional) Append the current directory to PYTHONPATH
$ export PYTHONPATH=$PYTHONPATH:$(pwd)

# Start the API server
$ python app/main.py

# Access the API local page
$ open http://localhost:8000/
````

### Running via Docker

````bash
# Clone the repository
$ git clone https://github.com/felipeall/transfermarkt-api.git

# Go to the project's root folder
$ cd transfermarkt-api

# Build the Docker image
$ docker build -t transfermarkt-api . 

# Instantiate the Docker container
$ docker run -d -p 8000:8000 transfermarkt-api

# Access the API local page
$ open http://localhost:8000/
````

### Caching

Transfermarkt fronts its pages with an anti-bot layer that answers suspicious traffic with an HTTP
202 challenge instead of the page you asked for. Responses are cached in memory to keep the number
of outbound scrapes down, and cached data doubles as a fallback when a scrape is blocked anyway.

Every response carries an `X-Cache` header describing where it came from:

| `X-Cache` | Meaning                                                                        |
|-----------|--------------------------------------------------------------------------------|
| `MISS`    | Scraped from Transfermarkt and stored                                           |
| `HIT`     | Served from cache, still within its TTL                                         |
| `STALE`   | The scrape was blocked, so an expired entry was served. `Age` says how old it is |

Alongside those, responses carry `ETag`, `Cache-Control` and (for `HIT`/`STALE`) `Age`, so browsers
and CDNs can revalidate with `If-None-Match` and get a `304` rather than the whole body.

When a scrape is blocked and there is no usable cached copy, the API returns `503` with a
`Retry-After` header. After several consecutive challenges a circuit breaker stops making outbound
requests altogether for a cooldown period, since retrying into an active block tends to prolong it.

`GET /health` reports the cache hit rate and whether the breaker is currently open.

TTLs vary by how quickly the underlying data changes, from 6 hours for squads and profiles up to 24
hours for honours and jersey numbers. Endpoints taking a `season_id` for a completed season are
cached for 30 days, since past-season data never changes.

Note that the cache lives in process memory: it is lost on restart, and each instance keeps its own.
If you deploy more than one instance, or scale to zero while idle, expect a correspondingly lower
hit rate.

### Environment Variables

| Variable                  | Description                                               | Default      |
|---------------------------|-----------------------------------------------------------|--------------|
| `RATE_LIMITING_ENABLE`    | Enable rate limiting feature for API calls                | `false`      |
| `RATE_LIMITING_FREQUENCY` | Delay allowed between each API call. See [slowapi](https://slowapi.readthedocs.io/en/latest/) for more | `2/3seconds` |
| `CACHE_ENABLE`            | Enable response caching                                   | `true`       |
| `CACHE_MAX_ENTRIES`       | Maximum cached responses before least-recently-used eviction | `2000`    |
| `CACHE_STALE_SECONDS`     | How long an expired entry stays servable when a scrape is blocked | `604800` (7d) |
| `CACHE_NEGATIVE_TTL`      | How long a genuine 404 is remembered                      | `300` (5m)   |
| `CACHE_TTL_SHORT`         | TTL for squads, profiles, stats and searches              | `21600` (6h) |
| `CACHE_TTL_MEDIUM`        | TTL for market values, transfers and injuries             | `43200` (12h)|
| `CACHE_TTL_LONG`          | TTL for honours, jersey numbers and club profiles         | `86400` (24h)|
| `CACHE_TTL_ARCHIVE`       | TTL for completed seasons                                 | `2592000` (30d) |
| `BOT_BREAKER_ENABLE`      | Stop outbound requests after repeated bot challenges      | `true`       |
| `BOT_BREAKER_THRESHOLD`   | Consecutive challenges before the circuit opens           | `3`          |
| `BOT_BREAKER_COOLDOWN`    | Seconds the circuit stays open                            | `60`         |
