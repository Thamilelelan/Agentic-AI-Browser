#!/usr/bin/env python3
"""
Unit test for click functionality with ARIA labels across multiple real websites.
Tests the _click_via_selector function with various real websites and ARIA labels.
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright

# Add the project root to path
sys.path.insert(0, '/home/cosmic/Documents/careerShit/fyproject')

from action_layer import _click_via_selector


def test_click_functionality():
    """Test click functionality across multiple real websites."""
    
    test_results = {
        'passed': 0,
        'failed': 0,
        'details': []
    }
    
    test_cases = [
        {
            'name': 'Amazon India - Add to Cart button',
            'url': 'https://www.amazon.in/s?k=iphone+15+pro',
            'selectors_to_try': [
                ('[aria-label="Add to cart"]', 'Add to cart (aria-label)'),
                ('[aria-label*="Add to cart"]', 'Add to cart (partial aria-label)'),
                ('button:has-text("Add to cart")', 'Add to cart (button text)'),
                ('#a-autoid-1', 'Add to cart (Amazon ID pattern)'),
            ],
            'expected_on_page': 'Amazon',
        },
        {
            'name': 'Amazon.com - Add to Cart',
            'url': 'https://www.amazon.com/s?k=laptop',
            'selectors_to_try': [
                ('[aria-label="Add to Cart"]', 'Add to Cart (aria-label)'),
                ('[aria-label*="Add to Cart"]', 'Add to Cart (partial aria-label)'),
                ('#add-to-cart-button', 'Add to Cart (ID)'),
                ('#add-to-cart-button', 'Add to Cart (alt ID)'),
            ],
            'expected_on_page': 'Amazon',
        },
        {
            'name': 'GitHub - Sign in button',
            'url': 'https://github.com',
            'selectors_to_try': [
                ('[aria-label="Sign in"]', 'Sign in (aria-label)'),
                ('[href="/login"]', 'Sign in (href)'),
                ('a[href="/login"]', 'Sign in (href)'),
            ],
            'expected_on_page': 'GitHub',
        },
        {
            'name': 'GitHub - Sign up button',
            'url': 'https://github.com',
            'selectors_to_try': [
                ('[aria-label="Sign up for GitHub"]', 'Sign up (aria-label)'),
                ('a[href="/signup"]', 'Sign up (href)'),
            ],
            'expected_on_page': 'GitHub',
        },
        {
            'name': 'DuckDuckGo - Search button',
            'url': 'https://duckduckgo.com',
            'selectors_to_try': [
                ('[aria-label="Search"]', 'Search (aria-label)'),
                ('input[type="submit"][value="Search"]', 'Search (input submit)'),
                ('button[type="submit"]', 'Search (button submit)'),
            ],
            'expected_on_page': 'DuckDuckGo',
        },
        {
            'name': 'Wikipedia - Search button',
            'url': 'https://www.wikipedia.org',
            'selectors_to_try': [
                ('[aria-label="Search Wikipedia"]', 'Search Wikipedia (aria-label)'),
                ('button[type="submit"]', 'Search (button submit)'),
                ('button.pure-button-primary-progressive', 'Search (class)'),
            ],
            'expected_on_page': 'Wikipedia',
        },
    ]
    
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        contexts = browser.contexts
        
        if not contexts:
            print("❌ No browser contexts found. Make sure Helium/Chrome is running with --remote-debugging-port=9222")
            return
            
        context = browser.contexts[0]
        pages = context.pages
        
        if not pages:
            print("❌ No pages found in browser context")
            browser.close()
            return
            
        page = pages[0]
        
        for test_case in test_cases:
            print(f"\n{'='*60}")
            print(f"Testing: {test_case['name']}")
            print(f"URL: {test_case['url']}")
            print("-" * 60)
            
            try:
                # Navigate to the test URL
                page.goto(test_case['url'], wait_until='domcontentloaded', timeout=30000)
                page.wait_for_load_state('networkidle', timeout=10000)
                page.wait_for_timeout(3000)
                
                print(f"  Current URL: {page.url}")
                print(f"  Page title: {page.title()}")
                
                # Verify we're on the expected site
                page_title = page.title().lower()
                expected = test_case['expected_on_page'].lower()
                if expected not in page.url.lower() and expected not in page_title.lower():
                    print(f"  ⚠️  Warning: May not be on expected page ({test_case['expected_on_page']})")
                
                # Try each selector
                success = False
                for selector, description in test_case['selectors_to_try']:
                    print(f"\n  Trying selector: {selector} ({description})")
                    try:
                        # Try the click function
                        result = _click_via_selector(page, '', description)
                        if result:
                            print(f"  ✅ SUCCESS: Clicked '{description}' using selector: {selector}")
                            page.wait_for_timeout(2000)
                            test_results['passed'] += 1
                            test_results['details'].append({
                                'test': test_case['name'],
                                'selector': selector,
                                'description': description,
                                'status': 'PASSED'
                            })
                            break
                        else:
                            print(f"  ❌ Click returned False for selector: {selector}")
                    except Exception as e:
                        print(f"  ❌ Error with selector '{selector}': {e}")
                    
                if not any(detail['test'] == test_case['name'] and detail['status'] == 'PASSED' 
                          for detail in test_results['details'] if detail['test'] == test_case['name']):
                    print(f"  ❌ All selectors failed for {test_case['name']}")
                    test_results['failed'] += 1
                    test_results['details'].append({
                        'test': test_case['name'],
                        'selectors_tried': [s for s, _ in test_case['selectors_to_try']],
                        'status': 'FAILED'
                    })
                    
            except Exception as e:
                print(f"  ❌ Navigation/Setup error: {e}")
                test_results['failed'] += 1
                test_results['details'].append({
                    'test': test_case['name'],
                    'error': str(e),
                    'status': 'ERROR'
                })
        
        browser.close()
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Total Passed: {test_results['passed']}")
    print(f"Total Failed: {test_results['failed']}")
    print(f"Total Tests: {test_results['passed'] + test_results['failed']}")
    
    print("\nDetailed Results:")
    for detail in test_results['details']:
        status_icon = "✅" if detail['status'] == 'PASSED' else "❌"
        if 'selector' in detail:
            print(f"  {status_icon} {detail['test']} - {detail['selector']} ({detail['description']})")
        else:
            print(f"  {status_icon} {detail['test']} - {detail.get('error', detail.get('status', 'UNKNOWN'))}")
    
    return test_results


if __name__ == '__main__':
    print("="*60)
    print("CLICK FUNCTIONALITY UNIT TESTS")
    print("="*60)
    print("Testing click functionality across multiple real websites")
    print("Using CDP connection to existing browser at localhost:9222")
    print()
    
    # Check if browser is running
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222', timeout=5000)
            browser.close()
        print("✅ CDP connection successful")
    except Exception as e:
        print(f"❌ Cannot connect to browser at localhost:9222: {e}")
        print("Please start browser with: /opt/helium-browser-bin/helium --remote-debugging-port=9222 --user-data-dir=\"$HOME/.config/helium-browser\"")
        sys.exit(1)
    
    print("\nStarting tests...\n")
    results = test_click_functionality()
    
    # Exit code based on results
    if results['failed'] > 0:
        print(f"\n❌ Some tests failed ({results['failed']} failed)")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)