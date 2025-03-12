# AOTY API

An optimized, unofficial API for albumoftheyear.org that provides access to album information, user profiles, and more.

## Features

- 🎵 **Album Information**: Get detailed album data including tracks, reviews, and ratings
- 👥 **User Profiles**: Access user information, ratings, and reviews
- 🔍 **Search**: Find albums with fuzzy search support
- 🧩 **Similar Albums**: Discover albums similar to those you enjoy
- ⚡ **Performance**: Optimized caching with Redis for faster responses
- 🛡️ **Reliability**: Anti-bot detection with Playwright
- 📊 **Metrics**: Built-in API usage monitoring

## Installation

1. Clone the repository:

```bash
git clone https://github.com/connergroth/AOTY-API.git
cd AOTY-API
```

2. Create a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:

```bash
playwright install chromium
```

5. Set up environment variables:

Create a `.env` file in the root directory with the following variables:

```
UPSTASH_REDIS_REST_URL=your_redis_url
UPSTASH_REDIS_REST_TOKEN=your_redis_token
```

## Usage

Start the development server:

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`. You can access the interactive API documentation at `http://localhost:8000/docs`.

## API Endpoints

### Get Album Details

```
GET /album/?artist={artist_name}&album={album_name}
```

Returns detailed information about an album, including tracks, reviews, and more.

### Get Similar Albums

```
GET /album/similar/?artist={artist_name}&album={album_name}&limit={number}
```

Returns a list of albums similar to the specified album.

### Search Albums

```
GET /search/?query={search_query}&limit={number}
```

Searches for albums matching the query.

### Get User Profile

```
GET /user/?username={username}
```

Returns a user's profile information, including ratings, reviews, and favorite albums.

### Get API Metrics

```
GET /metrics
```

Returns current API usage statistics.

## Caching

The API uses Redis for caching with the following TTLs:

- Album data: 1 week
- Similar albums: 1 day
- User profiles: 1 hour
- Search results: 12 hours

You can force a refresh of cached data by adding `refresh=true` to your request.

## Rate Limiting

To ensure API stability, the following rate limits apply:

- 30 requests per minute per IP address

## Deployment

### Docker

Build and run the Docker container:

```bash
docker build -t aoty-api .
docker run -p 8000:8000 aoty-api
```

### Fly.io

Deploy to Fly.io:

```bash
fly launch
fly deploy
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This API is not affiliated with albumoftheyear.org. It's an unofficial API meant for educational purposes and personal use.