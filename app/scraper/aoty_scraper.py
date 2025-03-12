import asyncio
import urllib.parse
from typing import Optional, List, Dict, Tuple, Any
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Page
from fastapi import HTTPException

from ..config import BASE_URL, PLAYWRIGHT_HEADLESS, PLAYWRIGHT_TIMEOUT
from ..models import (
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
                        artist_text = await artist_elem.text_content()
                        featured_artists.append(artist_text.strip())
                
                tracks.append(
                    Track(
                        number=number,
                        title=title.strip(),
                        length=length.strip(),
                        rating=rating,
                        featured_artists=featured_artists,
                    )
                )
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
        # Check if critics tab exists
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
.append(
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
                tab_text = await tab.text_content()
                if "Reviews" in tab_text and "(" in tab_text and ")" in tab_text:
                    try:
                        num_part = tab_text.split("(")[1].split(")")[0]
                        num_reviews += parse_number(num_part)
                    except (IndexError, ValueError):
                        pass
            
            # Create tasks for extracting different parts of the album
            metadata_task = asyncio.create_task(extract_album_metadata(page))
            tracks_task = asyncio.create_task(parse_tracks(page))
            critic_reviews_task = asyncio.create_task(parse_critic_reviews(page))
            user_reviews_task = asyncio.create_task(parse_user_reviews(page, "users"))
            buy_links_task = asyncio.create_task(parse_buy_links(page))
            
            # Wait for all tasks to complete
            metadata, tracks, critic_reviews, user_reviews, buy_links = await asyncio.gather(
                metadata_task, tracks_task, critic_reviews_task, user_reviews_task, buy_links_task
            )
            
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
                popular_reviews=user_reviews,
                buy_links=buy_links,
            )
            
        finally:
            await page.close()
            
    except PlaywrightTimeoutError:
        raise HTTPException(status_code=503, detail="Timeout scraping album")
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Error scraping album: {str(e)}"
        )


async def get_similar_albums(url: str, limit: int = 5) -> List[Album]:
    """Get similar albums using Playwright"""
    try:
        if not url.endswith("/"):
            url += "/"
        similar_url = f"{url}similar/"
        
        page = await new_page()
        try:
            await page.goto(similar_url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for album blocks to load
            await page.wait_for_selector(".albumBlock", timeout=PLAYWRIGHT_TIMEOUT)
            
            # Get all album blocks
            album_blocks = await page.query_selector_all(".albumBlock")
            
            # Limit the number of albums to process
            album_blocks = album_blocks[:limit] if limit > 0 else album_blocks
            
            similar_albums = []
            for album_block in album_blocks:
                try:
                    # Extract album link
                    album_link = await album_block.query_selector(".image a")
                    if not album_link:
                        continue
                        
                    href = await album_link.get_attribute("href")
                    album_url = f"{BASE_URL}{href}"
                    
                    # Extract artist and title
                    artist_elem = await album_block.query_selector(".artistTitle")
                    title_elem = await album_block.query_selector(".albumTitle")
                    
                    if not artist_elem or not title_elem:
                        continue
                        
                    artist_name = await artist_elem.text_content()
                    album_title = await title_elem.text_content()
                    
                    # Scrape the full album details
                    album = await scrape_album(album_url, artist_name.strip(), album_title.strip())
                    similar_albums.append(album)
                except Exception as e:
                    print(f"Error processing similar album: {str(e)}")
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
    """Search for albums using Playwright"""
    try:
        search_query = urllib.parse.quote(query)
        url = f"{BASE_URL}/search/albums/?q={search_query}"
        
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Wait for search results to load
            await page.wait_for_selector(".albumBlock", timeout=PLAYWRIGHT_TIMEOUT)
            
            # Get all album blocks
            album_blocks = await page.query_selector_all(".albumBlock")
            
            # Limit the number of results
            album_blocks = album_blocks[:limit] if limit > 0 else album_blocks
            
            results = []
            for album_block in album_blocks:
                try:
                    # Extract album URL
                    album_link = await album_block.query_selector(".image a")
                    if not album_link:
                        continue
                        
                    href = await album_link.get_attribute("href")
                    album_url = f"{BASE_URL}{href}"
                    
                    # Extract artist and title
                    artist_elem = await album_block.query_selector(".artistTitle")
                    title_elem = await album_block.query_selector(".albumTitle")
                    
                    if not artist_elem or not title_elem:
                        continue
                        
                    artist = await artist_elem.text_content()
                    title = await title_elem.text_content()
                    
                    # Extract cover image
                    cover_image = None
                    img_elem = await album_block.query_selector(".image img")
                    if img_elem:
                        cover_image = await img_elem.get_attribute("src")
                    
                    # Extract year
                    year = None
                    details_elem = await album_block.query_selector(".details")
                    if details_elem:
                        details_text = await details_elem.text_content()
                        if "•" in details_text:
                            year_text = details_text.split("•")[0].strip()
                            try:
                                year = int(year_text)
                            except ValueError:
                                pass
                    
                    # Extract score
                    score = None
                    score_elem = await album_block.query_selector(".scoreValue")
                    if score_elem:
                        score_text = await score_elem.text_content()
                        try:
                            score = float(score_text.strip())
                        except ValueError:
                            pass
                    
                    results.append(
                        SearchResult(
                            title=title.strip(),
                            artist=artist.strip(),
                            url=album_url,
                            cover_image=cover_image,
                            year=year,
                            score=score,
                        )
                    )
                except Exception as e:
                    print(f"Error processing search result: {str(e)}")
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
    """Extract basic user profile information using Playwright"""
    about = None
    location = None
    member_since = None
    
    try:
        # Extract about text
        about_elem = await page.query_selector(".aboutUser")
        if about_elem:
            about = await about_elem.text_content()
        
        # Extract location
        location_elem = await page.query_selector(".profileLocation")
        if location_elem:
            location = await location_elem.text_content()
        
        # Extract member since
        info_elements = await page.query_selector_all(".rightBox div")
        for elem in info_elements:
            elem_text = await elem.text_content()
            if elem_text and elem_text.startswith("Member since"):
                member_since = elem_text.replace("Member since", "").strip()
                break
    except Exception as e:
        print(f"Error extracting user profile info: {str(e)}")
    
    return about, location, member_since


async def extract_user_stats(page: Page) -> UserStats:
    """Extract user statistics using Playwright"""
    stats = UserStats()
    
    try:
        stat_containers = await page.query_selector_all(".profileStatContainer")
        if len(stat_containers) >= 4:
            # Extract stats in order: ratings, reviews, lists, followers
            for idx, key in enumerate(["ratings", "reviews", "lists", "followers"]):
                if idx < len(stat_containers):
                    stat_elem = await stat_containers[idx].query_selector(".profileStat")
                    if stat_elem:
                        stat_text = await stat_elem.text_content()
                        try:
                            setattr(stats, key, parse_number(stat_text.strip()))
                        except ValueError:
                            pass
    except Exception as e:
        print(f"Error extracting user stats: {str(e)}")
    
    return stats


async def extract_rating_distribution(page: Page) -> Dict[str, int]:
    """Extract rating distribution using Playwright"""
    distribution = {}
    
    try:
        dist_rows = await page.query_selector_all(".dist .distRow")
        for row in dist_rows:
            label_elem = await row.query_selector(".distLabel")
            count_elem = await row.query_selector(".distCount")
            
            if label_elem and count_elem:
                label_text = await label_elem.text_content()
                count_text = await count_elem.text_content()
                
                if label_text and count_text:
                    try:
                        count = parse_number(count_text.strip())
                        distribution[label_text.strip()] = count
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Error extracting rating distribution: {str(e)}")
    
    return distribution


async def extract_user_reviews(page: Page) -> List[ProfileUserReview]:
    """Extract user reviews from profile page using Playwright"""
    reviews = []
    
    try:
        review_rows = await page.query_selector_all(".albumReviewRow")
        
        for row in review_rows:
            try:
                # Extract album title and artist
                album_title_elem = await row.query_selector(".albumTitle")
                album_artist_elem = await row.query_selector(".artistTitle")
                
                if not album_title_elem or not album_artist_elem:
                    continue
                
                album_title = await album_title_elem.text_content()
                album_artist = await album_artist_elem.text_content()
                
                # Extract rating
                rating_elem = await row.query_selector(".rating")
                if not rating_elem:
                    continue
                
                rating_text = await rating_elem.text_content()
                try:
                    rating = int(rating_text.strip())
                except ValueError:
                    continue
                
                # Extract review text
                text_elem = await row.query_selector(".albumReviewText")
                review_text = await text_elem.text_content() if text_elem else ""
                
                # Extract likes
                likes = 0
                likes_elem = await row.query_selector(".review_likes")
                if likes_elem:
                    likes_text = await likes_elem.text_content()
                    try:
                        likes = parse_number(likes_text.strip())
                    except ValueError:
                        pass
                
                # Extract timestamp
                timestamp = ""
                timestamp_elem = await row.query_selector(".actionContainer[title]")
                if timestamp_elem:
                    timestamp = await timestamp_elem.text_content()
                
                reviews.append(
                    ProfileUserReview(
                        album_title=album_title.strip(),
                        album_artist=album_artist.strip(),
                        rating=rating,
                        review_text=review_text.strip(),
                        likes=likes,
                        timestamp=timestamp.strip(),
                    )
                )
            except Exception as e:
                print(f"Error extracting user review: {str(e)}")
                continue
    except Exception as e:
        print(f"Error extracting user reviews: {str(e)}")
    
    return reviews


async def extract_favorite_albums(page: Page) -> List[Dict[str, str]]:
    """Extract favorite albums using Playwright"""
    favorites = []
    
    try:
        album_blocks = await page.query_selector_all("#favAlbumsBlock .albumBlock")
        
        for block in album_blocks:
            try:
                # Extract album title and artist
                title_elem = await block.query_selector(".albumTitle")
                artist_elem = await block.query_selector(".artistTitle")
                
                if title_elem and artist_elem:
                    title = await title_elem.text_content()
                    artist = await artist_elem.text_content()
                    
                    # Extract cover image if available
                    cover_image = None
                    img_elem = await block.query_selector(".image img")
                    if img_elem:
                        cover_image = await img_elem.get_attribute("src")
                    
                    # Extract album URL
                    url = None
                    link_elem = await block.query_selector(".image a")
                    if link_elem:
                        href = await link_elem.get_attribute("href")
                        url = f"{BASE_URL}{href}" if href else None
                    
                    favorites.append({
                        "title": title.strip(),
                        "artist": artist.strip(),
                        "cover_image": cover_image,
                        "url": url
                    })
            except Exception as e:
                print(f"Error extracting favorite album: {str(e)}")
                continue
    except Exception as e:
        print(f"Error extracting favorite albums: {str(e)}")
    
    return favorites


async def extract_social_links(page: Page) -> Dict[str, str]:
    """Extract social media links using Playwright"""
    socials = {}
    
    try:
        link_elements = await page.query_selector_all(".profileLink")
        
        for link_elem in link_elements:
            try:
                # Extract platform from icon
                icon_elem = await link_elem.query_selector(".logo i")
                url_elem = await link_elem.query_selector("a")
                
                if icon_elem and url_elem:
                    class_attr = await icon_elem.get_attribute("class")
                    href = await url_elem.get_attribute("href")
                    
                    if class_attr and href:
                        # Extract platform name from class (e.g., "fa fa-twitter" -> "twitter")
                        classes = class_attr.split()
                        for cls in classes:
                            if cls.startswith("fa-") and cls != "fa-fw":
                                platform = cls.replace("fa-", "")
                                socials[platform] = href
                                break
            except Exception:
                continue
    except Exception as e:
        print(f"Error extracting social links: {str(e)}")
    
    return socials


async def get_user_profile(username: str) -> UserProfile:
    """Get user profile using Playwright"""
    url = f"{BASE_URL}/user/{username}/"
    
    try:
        page = await new_page()
        try:
            await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
            
            # Check if user exists
            profile_elem = await page.query_selector(".profileHeadLeft")
            if not profile_elem:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found")
            
            # Create tasks for extracting different parts of the profile
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


async def extract_favorite_albums(page: Page) -> List[Dict[str, str]]:
    """Extract favorite albums using Playwright"""
    favorites = []
    
    try:
        album_blocks = await page.query_selector_all("#favAlbumsBlock .albumBlock")
        
        for block in album_blocks:
            try:
                # Extract album title and artist
                title_elem = await block.query_selector(".albumTitle")
                artist_elem = await block.query_selector(".artistTitle")
                
                if title_elem and artist_elem:
                    title = await title_elem.text_content()
                    artist = await artist_elem.text_content()
                    
                    # Extract cover image if available
                    cover_image = None
                    img_elem = await block.query_selector(".image img")
                    if img_elem:
                        cover_image = await img_elem.get_attribute("src")
                    
                    # Extract album URL
                    url = None
                    link_elem = await block.query_selector(".image a")
                    if link_elem:
                        href = await link_elem.get_attribute("href")
                        url = f"{BASE_URL}{href}" if href else None
                    
                    favorites.append({
                        "title": title.strip(),
                        "artist": artist.strip(),
                        "cover_image": cover_image,
                        "url": url
                    })
            except Exception as e:
                print(f"Error extracting favorite album: {str(e)}")
                continue
    except Exception as e:
        print(f"Error extracting favorite albums: {str(e)}")
    
    return favorites


async def extract_social_links(page: Page) -> Dict[str, str]:
    """Extract social media links using Playwright"""
    socials = {}
    
    try:
        link_elements = await page.query_selector_all(".profileLink")
        
        for link_elem in link_elements:
            try:
                # Extract platform from icon
                icon_elem = await link_elem.query_selector(".logo i")
                url_elem = await link_elem.query_selector("a")
                
                if icon_elem and url_elem:
                    class_attr = await icon_elem.get_attribute("class")
                    href = await url_elem.get_attribute("href")
                    
                    if class_attr and href:
                        # Extract platform name from class (e.g., "fa fa-twitter" -> "twitter")
                        classes = class_attr.split()
                        for cls in classes:
                            if cls.startswith("fa-") and cls != "fa-fw":
                                platform = cls.replace("fa-", "")
                                socials[platform] = href
                                break
            except Exception:
                continue
    except Exception as e:
        print(f"Error extracting social links: {str(e)}")
    
    return socials


