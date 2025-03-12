import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict


@dataclass
class Metrics:
    """Holds API usage metrics data"""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: int = 0
    avg_response_time: float = 0.0
    max_response_time: float = 0.0
    last_reset: datetime = datetime.now()
    
    # Endpoint-specific metrics
    endpoint_hits: Dict[str, int] = None
    
    def __post_init__(self):
        if self.endpoint_hits is None:
            self.endpoint_hits = {
                "album": 0,
                "similar": 0,
                "search": 0,
                "user": 0,
                "metrics": 0,
            }
    
    def to_dict(self):
        """Convert to dictionary with ISO format datetime"""
        result = asdict(self)
        result["last_reset"] = self.last_reset.isoformat()
        return result


class MetricsCollector:
    """Collects and manages API metrics"""
    
    def __init__(self):
        self._metrics = Metrics()
        self._lock = threading.Lock()
        
    def record_request(self, cache_hit: bool = False, endpoint: str = None) -> None:
        """Record a new request"""
        with self._lock:
            self._metrics.total_requests += 1
            if cache_hit:
                self._metrics.cache_hits += 1
            else:
                self._metrics.cache_misses += 1
                
            # Record endpoint hit if provided
            if endpoint and endpoint in self._metrics.endpoint_hits:
                self._metrics.endpoint_hits[endpoint] += 1

    def record_error(self) -> None:
        """Record an error"""
        with self._lock:
            self._metrics.errors += 1

    def record_response_time(self, duration: float) -> None:
        """Record response time for a request"""
        with self._lock:
            # Update rolling average
            current_avg = self._metrics.avg_response_time
            total = current_avg * (self._metrics.total_requests - 1)
            self._metrics.avg_response_time = (
                total + duration
            ) / self._metrics.total_requests
            
            # Update max response time if needed
            if duration > self._metrics.max_response_time:
                self._metrics.max_response_time = duration

    def get_metrics(self) -> Dict:
        """Get current metrics as a dictionary"""
        with self._lock:
            return self._metrics.to_dict()

    def reset(self) -> None:
        """Reset all metrics"""
        with self._lock:
            self._metrics = Metrics()


# Singleton instance
metrics = MetricsCollector()