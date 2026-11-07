"""Tests for user-agent parsing utility."""
import pytest
from app.utils.user_agent import parse_user_agent, DeviceInfo


class TestParseUserAgent:
    """Test user-agent string parsing."""

    def test_chrome_on_macos(self):
        """Test parsing Chrome on macOS."""
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        result = parse_user_agent(ua)

        assert result.browser_name == "Chrome"
        assert result.browser_version == "120.0"
        assert result.os_name == "macOS"
        assert result.device_type == "desktop"
        assert "Chrome" in result.display_name
        assert "macOS" in result.display_name

    def test_safari_on_iphone(self):
        """Test parsing Safari on iPhone."""
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
        result = parse_user_agent(ua)

        assert result.browser_name == "Safari"
        assert result.os_name == "iOS"
        assert result.device_type == "mobile"
        assert "Safari" in result.display_name
        assert "iPhone" in result.display_name

    def test_chrome_on_windows(self):
        """Test parsing Chrome on Windows 10."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        result = parse_user_agent(ua)

        assert result.browser_name == "Chrome"
        assert result.os_name == "Windows 10"
        assert result.device_type == "desktop"
        assert "Chrome" in result.display_name
        assert "Windows" in result.display_name

    def test_firefox_on_linux(self):
        """Test parsing Firefox on Linux."""
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        result = parse_user_agent(ua)

        assert result.browser_name == "Firefox"
        assert result.os_name == "Linux"
        assert result.device_type == "desktop"
        assert "Firefox" in result.display_name

    def test_chrome_on_android(self):
        """Test parsing Chrome on Android."""
        ua = "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36"
        result = parse_user_agent(ua)

        assert result.browser_name == "Chrome"
        assert result.os_name == "Android"
        assert result.device_type == "mobile"
        assert "Chrome" in result.display_name
        assert "Android" in result.display_name

    def test_safari_on_ipad(self):
        """Test parsing Safari on iPad."""
        ua = "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
        result = parse_user_agent(ua)

        assert result.browser_name == "Safari"
        assert result.os_name == "iPadOS"
        assert result.device_type == "tablet"
        assert "iPad" in result.display_name

    def test_edge_on_windows(self):
        """Test parsing Edge on Windows."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.91"
        result = parse_user_agent(ua)

        assert result.browser_name == "Edge"
        assert result.os_name == "Windows 10"
        assert result.device_type == "desktop"

    def test_empty_user_agent(self):
        """Test parsing empty user-agent."""
        result = parse_user_agent("")

        assert result.browser_name is None
        assert result.os_name is None
        assert result.device_type == "desktop"
        assert result.display_name == "Unknown Device"

    def test_none_user_agent(self):
        """Test parsing None user-agent."""
        result = parse_user_agent(None)

        assert result.browser_name is None
        assert result.os_name is None
        assert result.display_name == "Unknown Device"

    def test_display_name_format_desktop(self):
        """Test display name format for desktop browsers."""
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        result = parse_user_agent(ua)

        # Should be format: "Browser Version on OS"
        assert "Chrome 120 on macOS" in result.display_name

    def test_display_name_format_mobile(self):
        """Test display name format for mobile browsers."""
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
        result = parse_user_agent(ua)

        # Should mention device type for mobile
        assert "Safari" in result.display_name
        assert "iPhone" in result.display_name

    def test_opera_detection(self):
        """Test that Opera is detected correctly (not Chrome)."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0"
        result = parse_user_agent(ua)

        assert result.browser_name == "Opera"

    def test_brave_detection(self):
        """Test that Brave is detected if present."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Brave/120"
        result = parse_user_agent(ua)

        assert result.browser_name == "Brave"
