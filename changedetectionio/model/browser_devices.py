"""Device presets for browser profiles (FetcherConfig.device).

Copied from Playwright's device descriptors (playwright/driver/package/lib/server/
deviceDescriptorsSource.json) rather than read from it at runtime: that file is an internal path
of the driver package, pyppeteer ships a different and older list, and the profile form needs the
same choices whichever engine is installed. Refresh the numbers from a newer Playwright when
adding devices.

`category` ('phone' / 'tablet') groups the profile form's device list.

The descriptor's device_scale_factor is kept for reference only - FetcherConfig applies 1 unless
the profile sets its own, because a factor of 3 makes every screenshot 9x the pixels for no
difference in layout.
"""

DEVICE_PRESETS = {
    'iPhone 15 Pro': {
        'category': 'phone',
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1',
        'viewport': {'width': 393, 'height': 659},
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
    'iPhone 15 Pro Max': {
        'category': 'phone',
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1',
        'viewport': {'width': 430, 'height': 739},
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
    'iPhone 13 Mini': {
        'category': 'phone',
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1',
        'viewport': {'width': 375, 'height': 629},
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
    'Pixel 7': {
        'category': 'phone',
        'user_agent': 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7390.37 Mobile Safari/537.36',
        'viewport': {'width': 412, 'height': 839},
        'device_scale_factor': 2.625,
        'is_mobile': True,
        'has_touch': True,
    },
    'Galaxy S24': {
        'category': 'phone',
        'user_agent': 'Mozilla/5.0 (Linux; Android 14; SM-S921U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7390.37 Mobile Safari/537.36',
        'viewport': {'width': 360, 'height': 780},
        'device_scale_factor': 3,
        'is_mobile': True,
        'has_touch': True,
    },
    'Galaxy A55': {
        'category': 'phone',
        'user_agent': 'Mozilla/5.0 (Linux; Android 14; SM-A556B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7390.37 Mobile Safari/537.36',
        'viewport': {'width': 480, 'height': 1040},
        'device_scale_factor': 2.25,
        'is_mobile': True,
        'has_touch': True,
    },
    'iPad (gen 11)': {
        'category': 'tablet',
        'user_agent': 'Mozilla/5.0 (iPad; CPU OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/19E241 Safari/604.1',
        'viewport': {'width': 656, 'height': 944},
        'device_scale_factor': 2.5,
        'is_mobile': True,
        'has_touch': True,
    },
    'iPad Mini': {
        'category': 'tablet',
        'user_agent': 'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1',
        'viewport': {'width': 768, 'height': 1024},
        'device_scale_factor': 2,
        'is_mobile': True,
        'has_touch': True,
    },
    'iPad Pro 11': {
        'category': 'tablet',
        'user_agent': 'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1',
        'viewport': {'width': 834, 'height': 1194},
        'device_scale_factor': 2,
        'is_mobile': True,
        'has_touch': True,
    },
    'Galaxy Tab S9': {
        'category': 'tablet',
        'user_agent': 'Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7390.37 Safari/537.36',
        'viewport': {'width': 640, 'height': 1024},
        'device_scale_factor': 2.5,
        'is_mobile': True,
        'has_touch': True,
    },
}

