import json
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import hashlib
import platform


class LicenseAPIError(Exception):
    """Base exception for License API errors"""

    def __init__(self, message: str, status_code: int = None, response_data: Dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class LicenseClient:
    """Client for SLAVA Licensing API"""

    def __init__(self, base_url: str, timeout: int = 10, jwks_url: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.jwks_url = jwks_url
        self._session = None
        self._token: Optional[str] = None
        self._device_fingerprint = self._generate_device_fingerprint()

    def _get_session(self) -> requests.Session:
        """Get or create HTTP session with retry strategy"""
        if self._session is None:
            self._session = requests.Session()

            # Configure retry strategy for 429 errors
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429],
                allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
            )

            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

        return self._session

    def _generate_device_fingerprint(self) -> str:
        """Generate device fingerprint for license binding"""
        # Simple fingerprint based on platform info
        info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
        return hashlib.sha256(info.encode()).hexdigest()[:32]

    def _make_request(self, method: str, endpoint: str, data: Dict = None, auth_required: bool = True) -> Dict:
        """Make HTTP request with proper error handling"""
        url = f"{self.base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}

        if auth_required and self._token:
            headers['Authorization'] = f'Bearer {self._token}'

        session = self._get_session()

        try:
            response = session.request(
                method=method,
                url=url,
                json=data,
                headers=headers,
                timeout=self.timeout
            )

            # Handle different status codes
            if response.status_code == 401:
                raise LicenseAPIError("Unauthorized - token expired or invalid", 401, response.json() if response.text else {})
            elif response.status_code == 402:
                raise LicenseAPIError("Payment required - insufficient quota", 402, response.json() if response.text else {})
            elif response.status_code == 409:
                raise LicenseAPIError("Conflict - operation already performed", 409, response.json() if response.text else {})
            elif response.status_code == 422:
                raise LicenseAPIError("Validation error", 422, response.json() if response.text else {})
            elif response.status_code == 429:
                raise LicenseAPIError("Too many requests - rate limited", 429, response.json() if response.text else {})
            elif response.status_code >= 500:
                raise LicenseAPIError(f"Server error: {response.status_code}", response.status_code, response.json() if response.text else {})
            elif not response.ok:
                raise LicenseAPIError(f"HTTP {response.status_code}: {response.text}", response.status_code, response.json() if response.text else {})

            return response.json() if response.text else {}

        except requests.exceptions.RequestException as e:
            raise LicenseAPIError(f"Network error: {str(e)}") from e

    def login(self, email: str, password: str) -> Tuple[str, Dict]:
        """Login and get JWT token

        Returns:
            Tuple of (token, user_data)
        """
        data = {
            'email': email,
            'password': password,
            'device_fingerprint': self._device_fingerprint
        }

        response = self._make_request('POST', '/auth/login', data, auth_required=False)
        token = response['token']
        user = response['user']

        self._token = token
        return token, user

    def get_license(self) -> Dict:
        """Get current license and quota information"""
        return self._make_request('GET', '/license')

    def reserve(self, messages: int, correlation_id: str = None) -> Dict:
        """Reserve quota for messages

        Args:
            messages: Number of messages to reserve
            correlation_id: Optional correlation ID (will be generated if not provided)

        Returns:
            Dict with reservation_id, reserved, remaining
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())

        data = {
            'messages': messages,
            'correlation_id': correlation_id
        }

        return self._make_request('POST', '/usage/reserve', data)

    def commit(self, reservation_id: str, used: int) -> Dict:
        """Commit used quota

        Args:
            reservation_id: Reservation ID from reserve() call
            used: Actual number of messages used (0 or more)
        """
        data = {
            'reservation_id': reservation_id,
            'used': used
        }

        return self._make_request('POST', '/usage/commit', data)

    def rollback(self, reservation_id: str) -> Dict:
        """Rollback reservation (if not committed)"""
        data = {
            'reservation_id': reservation_id
        }

        return self._make_request('POST', '/usage/rollback', data)

    def set_token(self, token: str):
        """Set JWT token for authenticated requests"""
        self._token = token

    def get_token(self) -> Optional[str]:
        """Get current JWT token"""
        return self._token

    def clear_token(self):
        """Clear JWT token"""
        self._token = None


class LicenseStorage:
    """Storage for license token and metadata"""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def save_token(self, token: str, expires_at: Optional[str] = None):
        """Save token to storage"""
        data = {
            'token': token,
            'expires_at': expires_at,
            'saved_at': time.time()
        }

        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def load_token(self) -> Optional[Dict]:
        """Load token from storage

        Returns:
            Dict with token, expires_at, saved_at or None if not found/expired
        """
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Check if token is expired
            if data.get('expires_at'):
                # For now, we don't validate JWT expiration on client side
                # This will be added in stage 6 with JWKS validation
                pass

            return data

        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def clear_token(self):
        """Remove token from storage"""
        try:
            self.storage_path.unlink()
        except FileNotFoundError:
            pass
