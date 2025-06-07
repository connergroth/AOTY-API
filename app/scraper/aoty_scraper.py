import asyncio
import urllib.parse
from typing import Optional, List, Dict, Tuple, Any
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Page
from fastapi import HTTPException

from ..config import BASE_URL, PLAYWRIGHT_HEADLESS, PLAYWRIGHT_TIMEOUT
from ..models.aoty_models import (
    Album, 
    Track, 
    CriticReview, 
    AlbumUserReview, 
    ProfileUserReview,
    UserProfile, 
    BuyLink, 
    SearchResult,
    AlbumMetadata,
    UserStats
)

# Cache for the Playwright browser instance
_browser = None
_browser_context = None


async def get_browser():
    """Get or create a shared Playwright browser instance"""
    global _browser, _browser_context
    
    if _browser is None:
        playwright = await async_playwright().start()
        _browser = await playwright.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        
    if _browser_context is None:
        _browser_context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
    
    return _browser_context


async def new_page():
    """Create a new page from the browser context"""
    context = await get_browser()
    return await context.new_page()


def parse_number(text: str | int) -> int:
    """Convert string numbers with commas to integers"""
    if isinstance(text, int):
        return text
    
    # Remove commas and other non-numeric characters
    clean_text = ''.join(c for c in str(text) if c.isdigit())
    return int(clean_text) if clean_text else 0


async def get_album_url(artist: str, album: str) -> Optional[Tuple[str, str, str]]:
    """
    Search for an album and return its URL, artist name, and album title.
    """
    search_query = urllib.parse.quote(f"{artist} {album}")
    url = f"{BASE_URL}/search/albums/?q={search_query}"

    try:
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for search results to load
            await page.wait_for_selector(".albumBlock", timeout=PLAYWRIGHT_TIMEOUT)
            
            # Check if any album blocks exist
            album_blocks = await page.query_selector_all(".albumBlock")
            if not album_blocks or len(album_blocks) == 0:
                return None
                
            # Get the first album block
            album_block = album_blocks[0]
            
            # Extract album URL
            album_link = await album_block.query_selector(".image a")
            if not album_link:
                return None
                
            href = await album_link.get_attribute("href")
            album_url = f"{BASE_URL}{href}"
            
            # Extract artist name
            artist_elem = await album_block.query_selector(".artistTitle")
            artist_name = await artist_elem.text_content() if artist_elem else ""
            
            # Extract album title
            title_elem = await album_block.query_selector(".albumTitle")
            album_title = await title_elem.text_content() if title_elem else ""
            
            if artist_name and album_title:
                return (album_url, artist_name.strip(), album_title.strip())
                
            return None
            
        finally:
            await page.close()
    except PlaywrightTimeoutError:
        raise HTTPException(status_code=503, detail="Timeout searching for album")
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Error searching for album: {str(e)}"
        )


async def extract_album_metadata(page: Page) -> AlbumMetadata:
    """Extract additional album metadata using Playwright selectors"""
    metadata = AlbumMetadata()
    
    try:
        # Extract genres
        genre_elements = await page.query_selector_all(".albumGenres a")
        metadata.genres = []
        for genre_elem in genre_elements:
            genre_text = await genre_elem.text_content()
            metadata.genres.append(genre_text.strip())
        
        # Extract additional metadata from album details
        detail_rows = await page.query_selector_all(".albumDetails .detailRow")
        for row in detail_rows:
            label_elem = await row.query_selector(".detailLabel")
            value_elem = await row.query_selector(".detailValue")
            
            if label_elem and value_elem:
                label_text = await label_elem.text_content()
                value_text = await value_elem.text_content()
                
                if label_text and value_text:
                    label_text = label_text.strip().lower()
                    value_text = value_text.strip()
                    
                    if "release date" in label_text:
                        metadata.release_date = value_text
                    elif "label" in label_text:
                        metadata.record_label = value_text
                    elif "type" in label_text:
                        metadata.album_type = value_text
                    elif "runtime" in label_text or "length" in label_text:
                        metadata.runtime = value_text
        
        # Check if album is marked as "must hear"
        must_hear = await page.query_selector(".mustHearButton")
        metadata.is_must_hear = must_hear is not None
        
    except Exception as e:
        print(f"Error extracting metadata: {str(e)}")
        
    return metadata


async def parse_tracks(page: Page) -> List[Track]:
    """Extract track information using Playwright selectors"""
    tracks = []
    
    try:
        track_rows = await page.query_selector_all(".trackListTable tr")
        
        for row in track_rows:
            try:
                # Extract track number
                number_elem = await row.query_selector(".trackNumber")
                if not number_elem:
                    continue
                    
                number_text = await number_elem.text_content()
                number = int(number_text.strip())
                
                # Extract track title
                title_elem = await row.query_selector(".trackTitle a")
                if not title_elem:
                    continue
                    
                title = await title_elem.text_content()
                
                # Extract track length
                length_elem = await row.query_selector(".length")
                length = await length_elem.text_content() if length_elem else ""
                
                # Extract track rating
                rating = None
                rating_elem = await row.query_selector(".trackRating span")
                if rating_elem:
                    try:
                        rating_text = await rating_elem.text_content()
                        rating = int(rating_text.strip())
                    except ValueError:
                        pass
                
                # Extract featured artists
                featured_artists = []
                featured_elem = await row.query_selector(".featuredArtists")
                if featured_elem:
                    featured_artist_elems = await featured_elem.query_selector_all("a")
                    for artist_elem in featured_artist_elems:
                        artist_name = await artist_elem.text_content()
                        if artist_name:
                            featured_artists.append(artist_name.strip())
                
                tracks.append(Track(
                    number=number,
                    title=title.strip(),
                    length=length.strip(),
                    rating=rating,
                    featured_artists=featured_artists
                ))
                
            except Exception as e:
                print(f"Error parsing track: {str(e)}")
                continue
                
    except Exception as e:
        print(f"Error parsing tracks: {str(e)}")
        
    return tracks


async def parse_critic_reviews(page: Page) -> List[CriticReview]:
    """Extract critic reviews using Playwright selectors"""
    reviews = []
    
    try:
        # Check if critics tab exists and click it
        critics_tab = await page.query_selector('a[data-target="#critics"]')
        if critics_tab:
            # Click the critics tab to ensure content is loaded
            await critics_tab.click()
            await page.wait_for_selector("#critics .albumReviewRow", timeout=5000)
        
        # Get all critic review rows
        review_rows = await page.query_selector_all("#critics .albumReviewRow")
        
        for row in review_rows:
            try:
                # Extract author
                author_elem = await row.query_selector(".author a")
                author = await author_elem.text_content() if author_elem else "Unknown"
                
                # Extract publication
                pub_elem = await row.query_selector(".publication a")
                publication = await pub_elem.text_content() if pub_elem else "Unknown"
                
                # Extract rating
                rating = 0
                rating_elem = await row.query_selector(".albumReviewRating")
                if rating_elem:
                    rating_text = await rating_elem.text_content()
                    try:
                        rating = int(rating_text.strip()) if rating_text.strip().isdigit() else 0
                    except ValueError:
                        pass
                
                # Extract review text
                text_elem = await row.query_selector(".albumReviewText")
                text = await text_elem.text_content() if text_elem else ""
                
                reviews.append(
                    CriticReview(
                        author=author.strip(),
                        publication=publication.strip(),
                        rating=rating,
                        text=text.strip(),
                    )
                )
            except Exception as e:
                print(f"Error parsing critic review: {str(e)}")
                continue
    except Exception as e:
        print(f"Error parsing critic reviews: {str(e)}")
        
    return reviews


async def parse_user_reviews(page: Page, section_id: str) -> List[AlbumUserReview]:
    """Extract user reviews using Playwright selectors"""
    reviews = []
    
    try:
        # Check if user tab exists and click it
        users_tab = await page.query_selector(f'a[data-target="#{section_id}"]')
        if users_tab:
            # Click the users tab to ensure content is loaded
            await users_tab.click()
            await page.wait_for_selector(f"#{section_id} .albumReviewRow", timeout=5000)
        
        # Get all user review rows
        review_rows = await page.query_selector_all(f"#{section_id} .albumReviewRow")
        
        for row in review_rows:
            try:
                # Extract author
                author_elem = await row.query_selector(".userReviewName a")
                if not author_elem:
                    continue
                    
                author = await author_elem.text_content()
                
                # Extract rating
                rating = None
                rating_elem = await row.query_selector(".rating")
                if rating_elem:
                    rating_text = await rating_elem.text_content()
                    if rating_text and rating_text.strip() != "NR" and rating_text.strip().isdigit():
                        rating = int(rating_text.strip())
                
                # Extract review text
                text_elem = await row.query_selector(".albumReviewText")
                text = await text_elem.text_content() if text_elem else ""
                
                # Extract likes
                likes = 0
                likes_elem = await row.query_selector(".review_likes a")
                if likes_elem:
                    likes_text = await likes_elem.text_content()
                    try:
                        likes = parse_number(likes_text.strip())
                    except ValueError:
                        pass
                
                reviews.append(
                    AlbumUserReview(
                        author=author.strip(),
                        rating=rating,
                        text=text.strip(),
                        likes=likes,
                    )
                )
            except Exception as e:
                print(f"Error parsing user review: {str(e)}")
                continue
    except Exception as e:
        print(f"Error parsing user reviews: {str(e)}")
        
    return reviews


async def parse_buy_links(page: Page) -> List[BuyLink]:
    """Extract buy links using Playwright selectors"""
    buy_links = []
    
    try:
        link_elements = await page.query_selector_all(".buyButtons a")
        
        for link_elem in link_elements:
            try:
                platform = await link_elem.get_attribute("title")
                url = await link_elem.get_attribute("href")
                
                if platform and url:
                    buy_links.append(BuyLink(platform=platform.strip(), url=url.strip()))
            except Exception:
                continue
    except Exception as e:
        print(f"Error parsing buy links: {str(e)}")
        
    return buy_links


async def scrape_album(url: str, artist: str, title: str) -> Album:
    """Scrape album information using Playwright"""
    try:
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for album page to load
            await page.wait_for_selector(".albumPage", timeout=PLAYWRIGHT_TIMEOUT)
            
            # Extract cover image URL
            cover_image = None
            img_elem = await page.query_selector(".albumImage img")
            if img_elem:
                cover_image = await img_elem.get_attribute("src")
            
            # Extract user score
            user_score = None
            score_elem = await page.query_selector(".albumUserScore a")
            if score_elem:
                score_title = await score_elem.get_attribute("title")
                if score_title:
                    try:
                        user_score = float(score_title)
                    except ValueError:
                        pass
            
            # Extract critic score
            critic_score = None
            critic_elem = await page.query_selector(".albumCriticScore")
            if critic_elem:
                critic_text = await critic_elem.text_content()
                try:
                    if critic_text and critic_text.strip() != "NR":
                        critic_score = float(critic_text.strip())
                except ValueError:
                    pass
            
            # Extract number of ratings
            num_ratings = 0
            ratings_elem = await page.query_selector(".numReviews strong")
            if ratings_elem:
                try:
                    ratings_text = await ratings_elem.text_content()
                    num_ratings = parse_number(ratings_text.strip())
                except ValueError:
                    pass
            
            # Extract number of reviews (user + critic)
            num_reviews = 0
            review_tabs = await page.query_selector_all(".reviewsContainer .tabButton")
            for tab in review_tabs:
                try:
                    tab_text = await tab.text_content()
                    if tab_text and "(" in tab_text and ")" in tab_text:
                        count_str = tab_text.split("(")[1].split(")")[0]
                        num_reviews += parse_number(count_str)
                except Exception:
                    continue
            
            # Run extraction tasks concurrently
            metadata_task = asyncio.create_task(extract_album_metadata(page))
            tracks_task = asyncio.create_task(parse_tracks(page))
            critic_reviews_task = asyncio.create_task(parse_critic_reviews(page))
            user_reviews_task = asyncio.create_task(parse_user_reviews(page, "users"))
            buy_links_task = asyncio.create_task(parse_buy_links(page))
            
            # Wait for all tasks to complete
            metadata = await metadata_task
            tracks = await tracks_task
            critic_reviews = await critic_reviews_task
            popular_reviews = await user_reviews_task
            buy_links = await buy_links_task
            
            return Album(
                title=title,
                artist=artist,
                url=url,
                cover_image=cover_image,
                user_score=user_score,
                critic_score=critic_score,
                num_ratings=num_ratings,
                num_reviews=num_reviews,
                metadata=metadata,
                tracks=tracks,
                critic_reviews=critic_reviews,
                popular_reviews=popular_reviews,
                buy_links=buy_links,
            )
            
        finally:
            await page.close()
    except PlaywrightTimeoutError:
        raise HTTPException(status_code=503, detail="Timeout scraping album")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Error scraping album: {str(e)}"
        )


async def get_similar_albums(url: str, limit: int = 5) -> List[Album]:
    """Get similar albums from an album page"""
    try:
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for similar albums section
            await page.wait_for_selector(".similarAlbums", timeout=PLAYWRIGHT_TIMEOUT)
            
            similar_albums = []
            similar_blocks = await page.query_selector_all(".similarAlbums .albumBlock")
            
            for block in similar_blocks[:limit]:
                try:
                    # Extract album URL
                    album_link = await block.query_selector(".image a")
                    if not album_link:
                        continue
                        
                    href = await album_link.get_attribute("href")
                    album_url = f"{BASE_URL}{href}"
                    
                    # Extract artist name
                    artist_elem = await block.query_selector(".artistTitle")
                    artist_name = await artist_elem.text_content() if artist_elem else ""
                    
                    # Extract album title
                    title_elem = await block.query_selector(".albumTitle")
                    album_title = await title_elem.text_content() if title_elem else ""
                    
                    # Extract cover image
                    cover_elem = await block.query_selector(".image img")
                    cover_image = await cover_elem.get_attribute("src") if cover_elem else None
                    
                    # Extract score
                    score = None
                    score_elem = await block.query_selector(".albumScore")
                    if score_elem:
                        score_text = await score_elem.text_content()
                        try:
                            score = float(score_text.strip()) if score_text.strip() != "NR" else None
                        except ValueError:
                            pass
                    
                    if artist_name and album_title:
                        similar_albums.append(Album(
                            title=album_title.strip(),
                            artist=artist_name.strip(),
                            url=album_url,
                            cover_image=cover_image,
                            user_score=score
                        ))
                        
                except Exception as e:
                    print(f"Error parsing similar album: {str(e)}")
                    continue
            
            return similar_albums
            
        finally:
            await page.close()
    except PlaywrightTimeoutError:
        raise HTTPException(status_code=503, detail="Timeout getting similar albums")
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Error getting similar albums: {str(e)}"
        )


async def search_albums(query: str, limit: int = 10) -> List[SearchResult]:
    """Search for albums and return results"""
    search_query = urllib.parse.quote(query)
    url = f"{BASE_URL}/search/albums/?q={search_query}"

    try:
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for search results to load
            await page.wait_for_selector(".albumBlock", timeout=PLAYWRIGHT_TIMEOUT)
            
            results = []
            album_blocks = await page.query_selector_all(".albumBlock")
            
            for block in album_blocks[:limit]:
                try:
                    # Extract album URL
                    album_link = await block.query_selector(".image a")
                    if not album_link:
                        continue
                        
                    href = await album_link.get_attribute("href")
                    album_url = f"{BASE_URL}{href}"
                    
                    # Extract artist name
                    artist_elem = await block.query_selector(".artistTitle")
                    artist_name = await artist_elem.text_content() if artist_elem else ""
                    
                    # Extract album title
                    title_elem = await block.query_selector(".albumTitle")
                    album_title = await title_elem.text_content() if title_elem else ""
                    
                    # Extract cover image
                    cover_elem = await block.query_selector(".image img")
                    cover_image = await cover_elem.get_attribute("src") if cover_elem else None
                    
                    # Extract year
                    year = None
                    year_elem = await block.query_selector(".albumYear")
                    if year_elem:
                        year_text = await year_elem.text_content()
                        try:
                            year = int(year_text.strip()) if year_text.strip().isdigit() else None
                        except ValueError:
                            pass
                    
                    # Extract score
                    score = None
                    score_elem = await block.query_selector(".albumScore")
                    if score_elem:
                        score_text = await score_elem.text_content()
                        try:
                            score = float(score_text.strip()) if score_text.strip() != "NR" else None
                        except ValueError:
                            pass
                    
                    if artist_name and album_title:
                        results.append(SearchResult(
                            title=album_title.strip(),
                            artist=artist_name.strip(),
                            url=album_url,
                            cover_image=cover_image,
                            year=year,
                            score=score
                        ))
                        
                except Exception as e:
                    print(f"Error parsing search result: {str(e)}")
                    continue
            
            return results
            
        finally:
            await page.close()
    except PlaywrightTimeoutError:
        raise HTTPException(status_code=503, detail="Timeout searching albums")
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Error searching albums: {str(e)}"
        )


async def extract_user_profile_info(page: Page) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract basic user profile information"""
    try:
        # Extract about text
        about_elem = await page.query_selector(".userAbout")
        about_text = await about_elem.text_content() if about_elem else None
        
        # Extract location
        location_elem = await page.query_selector(".userLocation")
        location_text = await location_elem.text_content() if location_elem else None
        
        # Extract member since date
        member_elem = await page.query_selector(".memberSince")
        member_since = await member_elem.text_content() if member_elem else None
        
        return about_text, location_text, member_since
        
    except Exception as e:
        print(f"Error extracting user profile info: {str(e)}")
        return None, None, None


async def extract_user_stats(page: Page) -> UserStats:
    """Extract user statistics"""
    try:
        stats = UserStats()
        
        # Extract ratings count
        ratings_elem = await page.query_selector(".userStats .ratings strong")
        if ratings_elem:
            ratings_text = await ratings_elem.text_content()
            stats.ratings = parse_number(ratings_text.strip())
        
        # Extract reviews count
        reviews_elem = await page.query_selector(".userStats .reviews strong")
        if reviews_elem:
            reviews_text = await reviews_elem.text_content()
            stats.reviews = parse_number(reviews_text.strip())
        
        # Extract lists count
        lists_elem = await page.query_selector(".userStats .lists strong")
        if lists_elem:
            lists_text = await lists_elem.text_content()
            stats.lists = parse_number(lists_text.strip())
        
        # Extract followers count
        followers_elem = await page.query_selector(".userStats .followers strong")
        if followers_elem:
            followers_text = await followers_elem.text_content()
            stats.followers = parse_number(followers_text.strip())
        
        return stats
        
    except Exception as e:
        print(f"Error extracting user stats: {str(e)}")
        return UserStats()


async def extract_rating_distribution(page: Page) -> Dict[str, int]:
    """Extract user's rating distribution"""
    try:
        distribution = {}
        
        rating_bars = await page.query_selector_all(".ratingDistribution .ratingBar")
        for bar in rating_bars:
            rating_elem = await bar.query_selector(".rating")
            count_elem = await bar.query_selector(".count")
            
            if rating_elem and count_elem:
                rating = await rating_elem.text_content()
                count_text = await count_elem.text_content()
                count = parse_number(count_text.strip())
                distribution[rating.strip()] = count
        
        return distribution
        
    except Exception as e:
        print(f"Error extracting rating distribution: {str(e)}")
        return {}


async def extract_user_reviews(page: Page) -> List[ProfileUserReview]:
    """Extract user's recent reviews"""
    try:
        reviews = []
        
        review_rows = await page.query_selector_all(".userReviews .reviewRow")
        for row in review_rows:
            try:
                # Extract album title
                title_elem = await row.query_selector(".albumTitle a")
                album_title = await title_elem.text_content() if title_elem else ""
                
                # Extract artist
                artist_elem = await row.query_selector(".artistTitle a")
                album_artist = await artist_elem.text_content() if artist_elem else ""
                
                # Extract rating
                rating = 0
                rating_elem = await row.query_selector(".rating")
                if rating_elem:
                    rating_text = await rating_elem.text_content()
                    try:
                        rating = int(rating_text.strip()) if rating_text.strip().isdigit() else 0
                    except ValueError:
                        pass
                
                # Extract review text
                text_elem = await row.query_selector(".reviewText")
                review_text = await text_elem.text_content() if text_elem else ""
                
                # Extract likes
                likes = 0
                likes_elem = await row.query_selector(".likes")
                if likes_elem:
                    likes_text = await likes_elem.text_content()
                    likes = parse_number(likes_text.strip())
                
                # Extract timestamp
                timestamp_elem = await row.query_selector(".timestamp")
                timestamp = await timestamp_elem.text_content() if timestamp_elem else ""
                
                if album_title and album_artist:
                    reviews.append(ProfileUserReview(
                        album_title=album_title.strip(),
                        album_artist=album_artist.strip(),
                        rating=rating,
                        review_text=review_text.strip(),
                        likes=likes,
                        timestamp=timestamp.strip()
                    ))
                    
            except Exception as e:
                print(f"Error parsing user review: {str(e)}")
                continue
        
        return reviews
        
    except Exception as e:
        print(f"Error extracting user reviews: {str(e)}")
        return []


async def extract_favorite_albums(page: Page) -> List[Dict[str, str]]:
    """Extract user's favorite albums"""
    try:
        favorites = []
        
        album_blocks = await page.query_selector_all(".favoriteAlbums .albumBlock")
        for block in album_blocks:
            try:
                # Extract album URL
                album_link = await block.query_selector(".image a")
                if not album_link:
                    continue
                    
                href = await album_link.get_attribute("href")
                album_url = f"{BASE_URL}{href}"
                
                # Extract artist name
                artist_elem = await block.query_selector(".artistTitle")
                artist_name = await artist_elem.text_content() if artist_elem else ""
                
                # Extract album title
                title_elem = await block.query_selector(".albumTitle")
                album_title = await title_elem.text_content() if title_elem else ""
                
                # Extract cover image
                cover_elem = await block.query_selector(".image img")
                cover_image = await cover_elem.get_attribute("src") if cover_elem else ""
                
                if artist_name and album_title:
                    favorites.append({
                        "title": album_title.strip(),
                        "artist": artist_name.strip(),
                        "url": album_url,
                        "cover_image": cover_image
                    })
                    
            except Exception as e:
                print(f"Error parsing favorite album: {str(e)}")
                continue
        
        return favorites
        
    except Exception as e:
        print(f"Error extracting favorite albums: {str(e)}")
        return []


async def extract_social_links(page: Page) -> Dict[str, str]:
    """Extract user's social media links"""
    try:
        social_links = {}
        
        link_elements = await page.query_selector_all(".socialLinks a")
        for link_elem in link_elements:
            try:
                platform = await link_elem.get_attribute("title")
                url = await link_elem.get_attribute("href")
                
                if platform and url:
                    social_links[platform.strip().lower()] = url.strip()
                    
            except Exception:
                continue
        
        return social_links
        
    except Exception as e:
        print(f"Error extracting social links: {str(e)}")
        return {}


async def get_user_profile(username: str) -> UserProfile:
    """Get complete user profile information"""
    url = f"{BASE_URL}/user/{username}/"
    
    try:
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for user profile to load
            await page.wait_for_selector(".userProfile", timeout=PLAYWRIGHT_TIMEOUT)
            
            # Run extraction tasks concurrently
            basic_info_task = asyncio.create_task(extract_user_profile_info(page))
            stats_task = asyncio.create_task(extract_user_stats(page))
            distribution_task = asyncio.create_task(extract_rating_distribution(page))
            reviews_task = asyncio.create_task(extract_user_reviews(page))
            favorites_task = asyncio.create_task(extract_favorite_albums(page))
            socials_task = asyncio.create_task(extract_social_links(page))
            
            # Wait for all tasks to complete
            about_text, location_text, member_since = await basic_info_task
            stats = await stats_task
            rating_distribution = await distribution_task
            reviews = await reviews_task
            favorites = await favorites_task
            social_links = await socials_task
            
            return UserProfile(
                username=username,
                location=location_text,
                about=about_text,
                member_since=member_since,
                stats=stats,
                rating_distribution=rating_distribution,
                favorite_albums=favorites,
                recent_reviews=reviews,
                social_links=social_links,
            )
            
        finally:
            await page.close()
            
    except PlaywrightTimeoutError:
        raise HTTPException(status_code=503, detail="Timeout accessing user profile")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Error accessing user profile: {str(e)}"
        )


async def close_browser():
    """Close the shared browser instance"""
    global _browser, _browser_context
    
    if _browser_context:
        await _browser_context.close()
        _browser_context = None
        
    if _browser:
        await _browser.close()
        _browser = None

