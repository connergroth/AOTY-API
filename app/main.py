from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from time import time
from contextlib import asynccontextmanager
from typing import Optional

from .config import API_VERSION, API_DESCRIPTION
from .utils.metrics import metrics
from .utils.cache import (
    get_cache,
    set_cache,
    ALBUM_TTL,
    SIMILAR_TTL,
    USER_TTL,
    SEARCH_TTL,
)
from .models import Album, UserProfile, SearchResult
from .scraper.aoty_scraper import (
    get_album_url,
    scrape_album,
    get_user_profile,
    get_similar_albums,
    search_albums,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize any resources on startup
    yield
    # Clean up resources on shutdown


app = FastAPI(
    title="AOTY API",
    description=API_DESCRIPTION,
    version=API_VERSION,
    contact={
        "name": "Conner Groth",
        "url": "https://github.com/connergroth/AOTY-API",
    },
    license_info={
        "name": "MIT",
    },
    lifespan=lifespan,
)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limit error handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    metrics.record_error()
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal server error: {str(exc)}",
            "path": request.url.path,
            "method": request.method,
        },
    )


@app.get(
    "/album/",
    response_model=Album,
    summary="Get Album Details",
    description="Retrieve detailed information about an album.",
    response_description="Detailed album information including tracks, reviews, and more.",
    responses={
        404: {"description": "Album not found"},
        503: {"description": "Error accessing album site"},
    },
)
@limiter.limit("30/minute")
async def get_album_endpoint(
    request: Request,
    artist: str = Query(..., description="Name of the artist", example="Radiohead"),
    album: str = Query(..., description="Name of the album", example="OK Computer"),
    refresh: bool = Query(False, description="Force refresh the cache"),
):
    start_time = time()
    try:
        cache_key = f"album:{artist}:{album}"
        
        # Check cache unless refresh is requested
        if not refresh and (cached_result := await get_cache(cache_key)):
            metrics.record_request(cache_hit=True)
            return Album(**cached_result)

        metrics.record_request(cache_hit=False)
        result = await get_album_url(artist, album)
        if not result:
            raise HTTPException(status_code=404, detail="Album not found")

        url, artist_name, title = result
        album_data = await scrape_album(url, artist_name, title)

        await set_cache(cache_key, album_data.dict(), ALBUM_TTL)
        metrics.record_response_time(time() - start_time)
        return album_data

    except HTTPException:
        raise
    except Exception as e:
        metrics.record_error()
        raise HTTPException(status_code=503, detail=str(e))


@app.get(
    "/album/similar/",
    response_model=list[Album],
    summary="Get Similar Albums",
    description="Find albums similar to a specified album.",
    response_description="List of albums similar to the specified album",
    responses={
        404: {"description": "Album not found"},
        503: {"description": "Error accessing album site"},
    },
)
@limiter.limit("30/minute")
async def get_similar_albums_endpoint(
    request: Request,
    artist: str = Query(..., description="Name of the artist", example="Radiohead"),
    album: str = Query(..., description="Name of the album", example="OK Computer"),
    refresh: bool = Query(False, description="Force refresh the cache"),
    limit: int = Query(5, description="Maximum number of similar albums to return", ge=1, le=10),
):
    start_time = time()
    try:
        cache_key = f"similar:{artist}:{album}:{limit}"
        
        # Check cache unless refresh is requested
        if not refresh and (cached_result := await get_cache(cache_key)):
            metrics.record_request(cache_hit=True)
            return [Album(**album_data) for album_data in cached_result]

        metrics.record_request(cache_hit=False)
        result = await get_album_url(artist, album)
        if not result:
            raise HTTPException(status_code=404, detail="Album not found")

        url, _, _ = result
        similar_albums = await get_similar_albums(url, limit)

        # Cache the list of albums as dictionaries
        await set_cache(
            cache_key, 
            [album.dict() for album in similar_albums], 
            SIMILAR_TTL
        )
        
        metrics.record_response_time(time() - start_time)
        return similar_albums

    except HTTPException:
        raise
    except Exception as e:
        metrics.record_error()
        raise HTTPException(status_code=503, detail=str(e))


@app.get(
    "/search/",
    response_model=list[SearchResult],
    summary="Search Albums",
    description="Search for albums matching the query.",
    response_description="List of albums matching the search query",
    responses={
        503: {"description": "Error accessing album site"},
    },
)
@limiter.limit("30/minute")
async def search_albums_endpoint(
    request: Request,
    query: str = Query(..., description="Search query", example="Radiohead OK Computer"),
    limit: int = Query(10, description="Maximum number of results to return", ge=1, le=20),
):
    start_time = time()
    try:
        cache_key = f"search:{query}:{limit}"
        
        if cached_result := await get_cache(cache_key):
            metrics.record_request(cache_hit=True)
            return [SearchResult(**result) for result in cached_result]

        metrics.record_request(cache_hit=False)
        results = await search_albums(query, limit)
        
        await set_cache(cache_key, [result.dict() for result in results], SEARCH_TTL)
        metrics.record_response_time(time() - start_time)
        return results

    except Exception as e:
        metrics.record_error()
        raise HTTPException(status_code=503, detail=str(e))


@app.get(
    "/user/",
    response_model=UserProfile,
    summary="Get User Profile",
    description="Retrieve a user's profile information.",
    response_description="User profile information",
    responses={
        404: {"description": "User not found"},
        503: {"description": "Error accessing user profile"},
    },
)
@limiter.limit("30/minute")
async def get_user_endpoint(
    request: Request,
    username: str = Query(
        ..., description="Username on albumoftheyear.org", example="evrynoiseatonce"
    ),
    refresh: bool = Query(False, description="Force refresh the cache"),
):
    start_time = time()
    try:
        cache_key = f"user:{username}"
        
        # Check cache unless refresh is requested
        if not refresh and (cached_result := await get_cache(cache_key)):
            metrics.record_request(cache_hit=True)
            return UserProfile(**cached_result)

        metrics.record_request(cache_hit=False)
        user_profile = await get_user_profile(username)

        await set_cache(cache_key, user_profile.dict(), USER_TTL)
        metrics.record_response_time(time() - start_time)
        return user_profile

    except HTTPException:
        raise
    except Exception as e:
        metrics.record_error()
        raise HTTPException(status_code=503, detail=str(e))


@app.get(
    "/metrics",
    summary="API Usage Metrics",
    description="Get current API usage statistics",
    response_description="Current API usage statistics",
    responses={
        200: {
            "description": "API metrics including request counts and response times",
            "content": {
                "application/json": {
                    "example": {
                        "total_requests": 7,
                        "cache_hits": 5,
                        "cache_misses": 2,
                        "errors": 0,
                        "avg_response_time": 0.158826896122524,
                        "last_reset": "2025-03-11T05:17:38.585115",
                    }
                }
            },
        }
    },
)
async def get_metrics_endpoint():
    return metrics.get_metrics()