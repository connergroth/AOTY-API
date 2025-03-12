from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


class Track(BaseModel):
    number: int
    title: str
    length: str
    rating: Optional[int] = None
    featured_artists: List[str] = []


class CriticReview(BaseModel):
    author: str
    publication: str
    rating: int
    text: str


class AlbumUserReview(BaseModel):
    author: str
    rating: Optional[int] = None
    text: str
    likes: int = 0


class ProfileUserReview(BaseModel):
    album_title: str
    album_artist: str
    rating: int
    review_text: str
    likes: int
    timestamp: str


class BuyLink(BaseModel):
    platform: str
    url: str


class AlbumMetadata(BaseModel):
    """Extended metadata for albums"""
    genres: List[str] = []
    release_date: Optional[str] = None
    record_label: Optional[str] = None
    album_type: Optional[str] = None
    runtime: Optional[str] = None
    is_must_hear: bool = False


class Album(BaseModel):
    title: str
    artist: str
    url: str = ""
    cover_image: Optional[str] = None
    user_score: Optional[float] = None
    critic_score: Optional[float] = None
    num_ratings: int = 0
    num_reviews: int = 0
    metadata: AlbumMetadata = Field(default_factory=AlbumMetadata)
    tracks: List[Track] = []
    critic_reviews: List[CriticReview] = []
    popular_reviews: List[AlbumUserReview] = []
    buy_links: List[BuyLink] = []
    
    class Config:
        schema_extra = {
            "example": {
                "title": "OK Computer",
                "artist": "Radiohead",
                "url": "https://www.albumoftheyear.org/album/5620-radiohead-ok-computer.php",
                "cover_image": "https://e.snmc.io/i/300/s/0eaad3b5d5f5e3cded10e2046e4c9ab7/5620",
                "user_score": 89.4,
                "critic_score": 92.3,
                "num_ratings": 24683,
                "num_reviews": 842,
                "metadata": {
                    "genres": ["Alternative Rock", "Art Rock"],
                    "release_date": "May 21, 1997",
                    "record_label": "XL Recordings",
                    "album_type": "Studio Album",
                    "runtime": "53:21",
                    "is_must_hear": True
                },
                "tracks": [
                    {"number": 1, "title": "Airbag", "length": "4:44", "rating": 88},
                    {"number": 2, "title": "Paranoid Android", "length": "6:23", "rating": 95}
                ]
            }
        }


class UserStats(BaseModel):
    ratings: int = 0
    reviews: int = 0
    lists: int = 0
    followers: int = 0


class UserProfile(BaseModel):
    username: str
    location: Optional[str] = None
    about: Optional[str] = None
    member_since: Optional[str] = None
    stats: UserStats = Field(default_factory=UserStats)
    favorite_albums: List[Dict[str, str]] = []
    recent_reviews: List[ProfileUserReview] = []
    social_links: Dict[str, str] = {}
    rating_distribution: Dict[str, int] = {}


class SearchResult(BaseModel):
    """Search result model for album searches"""
    title: str
    artist: str
    url: str
    cover_image: Optional[str] = None
    year: Optional[int] = None
    score: Optional[float] = None