"""User-Agent parsing utilities for session management.

Parses user-agent strings into human-friendly device information.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceInfo:
    """Parsed device information from user-agent string."""
    browser_name: Optional[str] = None
    browser_version: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    device_type: str = "desktop"  # desktop, mobile, tablet
    display_name: str = "Unknown Device"


# Browser patterns (order matters - more specific first)
_BROWSER_PATTERNS = [
    # Edge must come before Chrome (contains "Chrome" in UA)
    (r"Edg(?:e|A|iOS)?[/ ](\d+(?:\.\d+)?)", "Edge"),
    # Opera must come before Chrome (contains "Chrome" in UA)
    (r"OPR[/ ](\d+(?:\.\d+)?)", "Opera"),
    (r"Opera[/ ](\d+(?:\.\d+)?)", "Opera"),
    # Brave must come before Chrome (contains "Chrome" in UA)
    (r"Brave[/ ](\d+(?:\.\d+)?)", "Brave"),
    # Chrome variants
    (r"Chrome[/ ](\d+(?:\.\d+)?)", "Chrome"),
    (r"CriOS[/ ](\d+(?:\.\d+)?)", "Chrome"),  # Chrome on iOS
    # Firefox
    (r"Firefox[/ ](\d+(?:\.\d+)?)", "Firefox"),
    (r"FxiOS[/ ](\d+(?:\.\d+)?)", "Firefox"),  # Firefox on iOS
    # Safari (must come after Chrome since Chrome includes "Safari")
    (r"Version[/ ](\d+(?:\.\d+)?).*Safari", "Safari"),
    (r"Safari[/ ](\d+(?:\.\d+)?)", "Safari"),
    # Mobile browsers
    (r"SamsungBrowser[/ ](\d+(?:\.\d+)?)", "Samsung Browser"),
    (r"UCBrowser[/ ](\d+(?:\.\d+)?)", "UC Browser"),
    # IE
    (r"MSIE (\d+(?:\.\d+)?)", "Internet Explorer"),
    (r"Trident.*rv:(\d+(?:\.\d+)?)", "Internet Explorer"),
]

# OS patterns
_OS_PATTERNS = [
    # Mobile first
    (r"iPhone OS (\d+[_\d]*)", "iOS", "mobile"),
    (r"iPad.*OS (\d+[_\d]*)", "iPadOS", "tablet"),
    (r"Android (\d+(?:\.\d+)?)", "Android", "mobile"),
    # Desktop
    (r"Windows NT 10\.0", "Windows 10", "desktop"),
    (r"Windows NT 11\.0", "Windows 11", "desktop"),
    (r"Windows NT 6\.3", "Windows 8.1", "desktop"),
    (r"Windows NT 6\.2", "Windows 8", "desktop"),
    (r"Windows NT 6\.1", "Windows 7", "desktop"),
    (r"Mac OS X (\d+[_\d]*)", "macOS", "desktop"),
    (r"Macintosh", "macOS", "desktop"),
    (r"Linux", "Linux", "desktop"),
    (r"CrOS", "ChromeOS", "desktop"),
    (r"Ubuntu", "Ubuntu", "desktop"),
]


def _extract_version(version_str: Optional[str]) -> Optional[str]:
    """Extract major version or major.minor from version string."""
    if not version_str:
        return None
    # Replace underscores with dots (iOS uses underscores)
    version_str = version_str.replace("_", ".")
    parts = version_str.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0] if parts else None


def parse_user_agent(ua_string: Optional[str]) -> DeviceInfo:
    """
    Parse a user-agent string into meaningful device information.

    Args:
        ua_string: The user-agent string from the HTTP request

    Returns:
        DeviceInfo with parsed browser, OS, device type, and display name

    Examples:
        >>> info = parse_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        >>> info.display_name
        'Chrome 120 on macOS'

        >>> info = parse_user_agent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1")
        >>> info.display_name
        'Safari on iPhone'
    """
    if not ua_string:
        return DeviceInfo()

    browser_name = None
    browser_version = None
    os_name = None
    os_version = None
    device_type = "desktop"

    # Parse browser
    for pattern, name in _BROWSER_PATTERNS:
        match = re.search(pattern, ua_string, re.IGNORECASE)
        if match:
            browser_name = name
            browser_version = _extract_version(match.group(1) if match.lastindex else None)
            break

    # Parse OS
    for pattern, name, dtype in _OS_PATTERNS:
        match = re.search(pattern, ua_string, re.IGNORECASE)
        if match:
            os_name = name
            device_type = dtype
            # Extract version if captured
            if match.lastindex:
                os_version = _extract_version(match.group(1))
            break

    # Detect tablets that might not match OS patterns
    if "tablet" in ua_string.lower() or "ipad" in ua_string.lower():
        device_type = "tablet"
    elif any(m in ua_string.lower() for m in ["mobile", "android", "iphone"]):
        if device_type != "tablet":
            device_type = "mobile"

    # Build display name
    display_name = _build_display_name(
        browser_name, browser_version, os_name, os_version, device_type, ua_string
    )

    return DeviceInfo(
        browser_name=browser_name,
        browser_version=browser_version,
        os_name=os_name,
        os_version=os_version,
        device_type=device_type,
        display_name=display_name,
    )


def _build_display_name(
    browser_name: Optional[str],
    browser_version: Optional[str],
    os_name: Optional[str],
    os_version: Optional[str],
    device_type: str,
    ua_string: str,
) -> str:
    """Build a human-friendly display name from parsed components."""
    parts = []

    # Browser part
    if browser_name:
        if browser_version:
            # Only include major version for cleaner display
            major_version = browser_version.split(".")[0]
            parts.append(f"{browser_name} {major_version}")
        else:
            parts.append(browser_name)

    # OS/device part
    os_part = None
    if device_type == "mobile":
        if "iPhone" in ua_string:
            os_part = "iPhone"
        elif "Android" in ua_string:
            os_part = "Android"
        else:
            os_part = os_name or "Mobile"
    elif device_type == "tablet":
        if "iPad" in ua_string:
            os_part = "iPad"
        else:
            os_part = os_name or "Tablet"
    else:
        if os_name:
            if os_version and os_name not in ("Windows 10", "Windows 11", "Windows 8.1", "Windows 8", "Windows 7"):
                # Include version for macOS, etc.
                major_os_version = os_version.split(".")[0]
                os_part = f"{os_name} {major_os_version}"
            else:
                os_part = os_name

    # Combine parts
    if parts and os_part:
        return f"{parts[0]} on {os_part}"
    elif parts:
        return parts[0]
    elif os_part:
        return os_part
    else:
        return "Unknown Device"
