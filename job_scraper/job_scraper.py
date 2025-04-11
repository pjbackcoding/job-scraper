#!/usr/bin/env python3
"""
Job Scraper for Real Estate Positions in Paris

This script scrapes job listings from various job sites for real estate positions in Paris
and saves them to a JSON file. It features:

- Multiple job site support (Indeed, LinkedIn, etc.)
- Intelligent filtering for real estate jobs
- Automatic deduplication of job listings
- Robust request handling with retry logic
- Progress tracking and status reporting
- Command-line interface with customizable options
"""

import json
import time
import random
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from fake_useragent import UserAgent
import argparse
import logging
import os
import signal
import sys
import urllib.parse
from datetime import datetime
import functools
from pathlib import Path

# Import selenium components for Google Jobs scraping
# We won't use Selenium due to compatibility issues with Chrome driver on this system
selenium_available = True

# Set up logging
def setup_logging(log_file="scraper.log", log_level=logging.INFO):
    """Set up logging configuration"""
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# Create a UserAgent object for rotating user agents
try:
    ua = UserAgent()
except Exception as e:
    logger.warning(f"Could not initialize UserAgent: {e}. Using a fallback list.")
    # Fallback user agents if fake_useragent fails
    class FallbackUA:
        def __init__(self):
            self.browsers = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0"
            ]
        
        @property
        def random(self):
            return random.choice(self.browsers)
    
    ua = FallbackUA()

# Retry decorator for handling transient errors
def retry_on_exception(max_retries=3, backoff_factor=0.5, expected_exceptions=(requests.RequestException,)):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            mtries, mdelay = max_retries, backoff_factor
            last_exception = None
            
            while mtries > 0:
                try:
                    return func(*args, **kwargs)
                except expected_exceptions as e:
                    last_exception = e
                    logger.warning(f"Request failed: {str(e)}. Retrying in {mdelay} seconds...")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= 2
            
            # If we've exhausted all retries, log the error and re-raise the last exception
            if last_exception:
                logger.error(f"All retries failed: {str(last_exception)}")
                raise last_exception
            
            # This should never happen, but just in case
            return func(*args, **kwargs)
        return wrapper
    return decorator

class JobScraper:
    """Class to scrape job postings from various job sites."""
    
    def __init__(self, max_pages=5, delay_min=1, delay_max=3, timeout=30, max_retries=3, max_runtime=300, date_filter=None):
        """
        Initialize the scraper with settings.
        
        Args:
            max_pages (int): Maximum number of pages to scrape per site
            delay_min (int): Minimum delay between requests in seconds
            delay_max (int): Maximum delay between requests in seconds
            timeout (int): Request timeout in seconds
            max_retries (int): Maximum number of retries for failed requests
            max_runtime (int): Maximum runtime in seconds (default: 5 minutes)
        """
        self.max_pages = max_pages
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.max_retries = max_retries
        self.jobs = []
        self.prev_job_count = 0
        self.start_time = time.time()
        self.max_runtime = max_runtime
        self.interrupted = False
        self.date_filter = date_filter
        
        # Configure date filtering
        self.date_threshold = None
        if date_filter:
            today = datetime.now().date()
            if date_filter == '1day':
                self.date_threshold = today.replace(day=today.day-1)
            elif date_filter == '1week':
                self.date_threshold = today.replace(day=today.day-7)
            elif date_filter == '2weeks':
                self.date_threshold = today.replace(day=today.day-14)
            elif date_filter == '1month':
                # Handle month rollover correctly
                if today.month == 1:
                    self.date_threshold = today.replace(year=today.year-1, month=12)
                else:
                    self.date_threshold = today.replace(month=today.month-1)
            
            logger.info(f"Date filtering enabled: Only showing jobs after {self.date_threshold}")
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_interrupt)
        
        # Enhanced headers to look more like a real browser
        self.headers = {
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'TE': 'Trailers'
        }
    
    def _random_delay(self):
        """Sleep for a random amount of time between requests."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)
        
    def _handle_interrupt(self, signum, frame):
        """Handle keyboard interrupt or termination signal with graceful shutdown"""
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.warning(f"Received {signal_name} signal. Stopping scraper gracefully...")
        self.interrupted = True
        
        # Save current progress when interrupted
        try:
            if self.jobs:
                filename = f"interrupted_scraper_{int(time.time())}.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(self.jobs, f, ensure_ascii=False, indent=2)
                logger.info(f"Saved current progress to {filename}")
        except Exception as e:
            logger.error(f"Failed to save progress during interrupt: {str(e)}")
        
    def _check_timeout(self):
        """Check if the scraper has been running for too long and exit if needed."""
        # Check maximum runtime exceeded
        if time.time() - self.start_time > self.max_runtime:
            logger.warning(f"Scraper has been running for more than {self.max_runtime} seconds. Stopping for safety.")
            return True
        
        # Check for user interruption
        if self.interrupted:
            logger.warning("Scraper interrupted by user. Stopping.")
            return True
        
        # Check if we've been stuck without progress for too long
        # (If job count hasn't changed in 2 minutes)
        if hasattr(self, 'last_progress_time') and hasattr(self, 'last_job_count'):
            if len(self.jobs) == self.last_job_count:
                if time.time() - self.last_progress_time > 120:  # 2 minutes
                    logger.warning("No new jobs found in 2 minutes. Possible stuck condition. Moving to next source.")
                    return True
            else:
                # Update progress tracker
                self.last_job_count = len(self.jobs)
                self.last_progress_time = time.time()
        else:
            # Initialize progress tracker
            self.last_job_count = len(self.jobs)
            self.last_progress_time = time.time()
            
        return False
    
    @retry_on_exception(max_retries=3, backoff_factor=1.0)
    def _make_request(self, url, referer=None):
        """Make a request with retry logic"""
        self.headers['User-Agent'] = ua.random  # Rotate user agent
        if referer:
            self.headers['Referer'] = referer
            
        # Add random cookies and vary headers slightly to look more human
        if random.random() > 0.5:
            self.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        
        response = requests.get(
            url, 
            headers=self.headers, 
            timeout=self.timeout
        )
        
        if response.status_code != 200:
            raise requests.RequestException(f"Status code: {response.status_code}")
            
        return response
    
    def _is_duplicate(self, job_data):
        """
        Check if a job is a duplicate of an existing job in the list.
        Uses a more sophisticated approach to avoid duplicates with slightly different data.
        
        Args:
            job_data (dict): Job data to check for duplication
            
        Returns:
            bool: True if the job is a duplicate, False otherwise
        """
        # Extract info from the job to compare
        title = job_data.get('title', '').lower()
        company = job_data.get('company', '').lower()
        location = job_data.get('location', '').lower()
        
        # Skip empty titles
        if not title or title == 'unknown':
            return True
        
        # First check: exact match of title and company
        for existing_job in self.jobs:
            existing_title = existing_job.get('title', '').lower()
            existing_company = existing_job.get('company', '').lower()
            
            # If exact match on title and company, it's a duplicate
            if existing_title == title and existing_company == company:
                return True
        
        # Second check: Similar titles at the same company with fuzzy matching
        for existing_job in self.jobs:
            existing_title = existing_job.get('title', '').lower()
            existing_company = existing_job.get('company', '').lower()
            existing_location = existing_job.get('location', '').lower()
            
            # Same company
            if existing_company == company:
                # Check for high similarity in titles (80% match)
                if self._similarity_score(existing_title, title) > 0.8:
                    # If locations are also similar
                    if not location or not existing_location or location in existing_location or existing_location in location:
                        return True
        
        return False
    
    def _similarity_score(self, str1, str2):
        """
        Calculate a simple similarity score between two strings.
        
        Args:
            str1 (str): First string to compare
            str2 (str): Second string to compare
            
        Returns:
            float: Similarity score between 0 and 1
        """
        # Simple implementation using set operations on words
        if not str1 or not str2:
            return 0.0
            
        # Split into words and create sets
        words1 = set(str1.lower().split())
        words2 = set(str2.lower().split())
        
        # Calculate Jaccard similarity: intersection / union
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        if union == 0:
            return 0.0
            
        return intersection / union
    
    def _is_real_estate_job(self, title, description=""):
        """
        Check if a job is related to real estate based on its title and description.
        Uses a more flexible matching approach to catch more relevant jobs.
        
        Args:
            title (str): Job title
            description (str): Job description (if available)
        
        Returns:
            bool: True if the job is related to real estate, False otherwise
        """
        # Lowercase for case-insensitive matching
        title_lower = title.lower()
        desc_lower = description.lower() if description else ""
        
        # Core real estate terms - high confidence match if these appear in title
        core_terms = [
            'immobilier', 'immobilière', 'real estate', 'property', 'foncier', 'foncière',
            'biens immobiliers', 'realty', 'reit', 'asset manager', 'investment manager',
            'fund manager', 'portfolio manager', 'underwriter', 'debt fund',
            'structured finance', 'acquisitions', 'asset management'
        ]
        
        # Job titles - high confidence if these appear with property/real estate context
        job_titles = [
            'agent', 'broker', 'négociateur', 'négociatrice', 'conseiller', 'conseillère',
            'consultant', 'manager', 'director', 'advisor', 'associate', 'analyst',
            'appraiser', 'surveyor', 'estimator', 'developer'
        ]
        
        # Property types - medium confidence
        property_types = [
            'residential', 'commercial', 'industrial', 'retail', 'office', 'housing',
            'apartment', 'building', 'development', 'résidentiel', 'commercial', 'bureaux'
        ]
        
        # Real estate activities - medium confidence
        activities = [
            'leasing', 'lease', 'rental', 'letting', 'transaction', 'vente', 'achat',
            'location', 'gestion', 'management', 'investment', 'investissement', 'acquisition',
            'development', 'développement', 'construction', 'promotion', 'valuation',
            'évaluation', 'estimation', 'mortgage', 'financement', 'hypothécaire', 'crédit'
        ]
        
        # Related fields - lower confidence, need multiple matches
        related_fields = [
            'asset', 'actifs', 'portfolio', 'portefeuille', 'patrimoine', 'wealth',
            'capital', 'fund', 'fonds', 'trust', 'reit', 'project', 'projet',
            'facility', 'facilities', 'bâtiment', 'copropriété', 'syndic', 'notaire',
            'notarial', 'legal', 'juridique', 'finance', 'financial', 'investment', 
            'debt', 'dette', 'structured', 'structuré', 'underwriting', 'acquisition',
            'asset management', 'fund management', 'investment management', 'am', 'aum', 
            'analyste', 'analyst', 'private equity', 'institutional'
        ]
        
        # Check for core terms in title (highest confidence)
        for term in core_terms:
            if term in title_lower:
                return True
        
        # Check for job titles with property context
        for job in job_titles:
            if job in title_lower and any(prop in title_lower or prop in desc_lower 
                                        for prop in core_terms + property_types):
                return True
        
        # Check for property types with real estate activities
        for prop_type in property_types:
            if prop_type in title_lower and any(act in title_lower or act in desc_lower 
                                              for act in activities):
                return True
        
        # Check for investment/asset management terms specifically
        investment_terms = ['investment', 'asset management', 'fund', 'portfolio', 'acquisition', 'debt']
        for term in investment_terms:
            if term in title_lower:
                return True
                
        # Check for multiple related fields (need at least 2)
        related_matches = 0
        for field in related_fields + activities + property_types:
            if field in title_lower:
                related_matches += 1
                if related_matches >= 2:
                    return True
        
        # If we have description, use it for additional matching
        if desc_lower:
            # Core terms in description are good indicators
            for term in core_terms:
                if term in desc_lower:
                    # If core term is in description and title has related terms
                    if any(field in title_lower for field in job_titles + activities + property_types):
                        return True
            
            # Count matches in description
            desc_matches = 0
            all_keywords = core_terms + job_titles + property_types + activities + related_fields
            for keyword in all_keywords:
                if keyword in desc_lower:
                    desc_matches += 1
                    # Require more matches in description only
                    if desc_matches >= 3:
                        return True
        
        return False
        
    def scrape_indeed(self, query="immobilier", location="Paris"):
        """Scrape Indeed with date filter support.
        
        If date_filter is set, adds appropriate URL parameters to filter by date.
        """
        """
        Scrape job listings from Indeed France.
        Uses multiple methods to bypass Indeed's anti-scraping measures.
        
        Args:
            query (str): Job keyword to search for
            location (str): Location to search in
        """
        logger.info(f"Starting to scrape Indeed for '{query}' jobs in {location}")
        start_count = len(self.jobs)
        
        # Use Selenium as a fallback if available, since it's more reliable for Indeed
        try:
            logger.info("Attempting to use Selenium for Indeed scraping (preferred method)")
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            # Randomize the user agent
            options.add_argument(f"user-agent={ua.random}")
            
            # Termes ultra spécifiques liés aux métiers de l'investissement immobilier, AM et dette
            additional_queries = [
                "investment manager immobilier",
                "asset manager immobilier",
                "fund manager real estate",
                "analyste investissement immobilier",
                "acquisitions immobilières",
                "debt fund immobilier",
                "structured finance real estate",
                "portfolio manager immobilier",
                "underwriter immobilier"                
            ]
            
            # Use query rotation to avoid detection and get more diverse results
            for current_query in additional_queries[:4]:  # Utiliser 4 requêtes au lieu de 2
                if self._check_timeout():
                    logger.warning("Time limit reached. Stopping scraping early.")
                    break
                    
                try:
                    logger.info(f"Trying Indeed query: {current_query}")
                    driver = webdriver.Chrome(options=options)
                    
                    # Use a different URL format that's less likely to be blocked
                    encoded_query = urllib.parse.quote_plus(current_query)
                    encoded_location = urllib.parse.quote_plus(location)
                    url = f"https://fr.indeed.com/emplois?q={encoded_query}&l={encoded_location}"
                    
                    driver.get(url)
                    # Wait for page to load - job cards have various class names, so wait for any of them
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div.job_seen_beacon, div.jobsearch-ResultsList, td.resultContent"))
                        )
                        logger.info("Indeed page loaded successfully")
                    except Exception as e:
                        logger.warning(f"Timeout waiting for Indeed results: {e}")
                        # Continue anyway as the page might have loaded partially
                    
                    # Get the page HTML after JavaScript execution
                    html = driver.page_source
                    
                    # Parse with Beautiful Soup for more reliable extraction
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Try multiple selectors to find job listings
                    job_elements = (
                        soup.select('.job_seen_beacon') or 
                        soup.select('.tapItem') or
                        soup.select('.cardOutline') or
                        soup.select('td.resultContent') or
                        soup.select('[data-testid="job-card"]') or
                        soup.select('[class*="job-card"]')
                    )
                    
                    logger.info(f"Found {len(job_elements)} potential job listings from Indeed")
                    
                    # Process job elements with a multi-layered selector approach
                    for job in job_elements:
                        # Title: try multiple potential selectors
                        title_element = (
                            job.select_one('h2.jobTitle') or 
                            job.select_one('h2[class*="title"]') or
                            job.select_one('a[class*="jcs-JobTitle"]') or 
                            job.select_one('a[id*="job-title"]') or
                            job.select_one('a[class*="title"]') or 
                            job.select_one('span[title]')
                        )
                        
                        # Skip if no title found
                        if not title_element:
                            continue
                            
                        title = title_element.text.strip()
                        
                        # Company name: try multiple selectors
                        company_element = (
                            job.select_one('span.companyName') or 
                            job.select_one('span[data-testid="company-name"]') or
                            job.select_one('[class*="companyName"]') or 
                            job.select_one('[class*="company"]')
                        )
                        company = company_element.text.strip() if company_element else "Unknown"
                        
                        # Location: try multiple selectors
                        location_element = (
                            job.select_one('div.companyLocation') or
                            job.select_one('[class*="location"]')
                        )
                        job_location = location_element.text.strip() if location_element else location
                        
                        # Extract job URL if available
                        job_url = None
                        
                        # Better approach to find the URL
                        # 1. Try direct href on title element if it's an anchor
                        if title_element.name == 'a' and title_element.has_attr('href'):
                            href = title_element['href']
                            if href.startswith('/'):
                                job_url = f"https://fr.indeed.com{href}"
                            else:
                                job_url = href
                        else:
                            # 2. Look for anchor inside title element (sometimes titles wrap anchors)
                            anchor_in_title = title_element.find('a')
                            if anchor_in_title and anchor_in_title.has_attr('href'):
                                href = anchor_in_title['href']
                                if href.startswith('/'):
                                    job_url = f"https://fr.indeed.com{href}"
                                else:
                                    job_url = href
                            else:
                                # 3. Look for the nearest anchor parent
                                parent_a = title_element.find_parent('a')
                                if parent_a and parent_a.has_attr('href'):
                                    href = parent_a['href']
                                    if href.startswith('/'):
                                        job_url = f"https://fr.indeed.com{href}"
                                    else:
                                        job_url = href
                                else:
                                    # 4. Search for any nearby job link
                                    # First try in the job card
                                    job_link = job.select_one('a[class*="job-"], a[class*="title"], a[href*="/viewjob"]')
                                    if job_link and job_link.has_attr('href'):
                                        href = job_link['href']
                                        if href.startswith('/'):
                                            job_url = f"https://fr.indeed.com{href}"
                                        else:
                                            job_url = href
                        
                        # Log for debugging
                        if job_url:
                            logger.debug(f"Found URL for {title}: {job_url}")
                        else:
                            logger.debug(f"No URL found for {title}")
                        
                        # Description: try multiple selectors
                        description = ""
                        description_element = (
                            job.select_one('div.job-snippet') or 
                            job.select_one('[class*="snippet"]') or
                            job.select_one('[class*="summary"]')
                        )
                        if description_element:
                            description = description_element.text.strip()
                        
                        # Check if job is related to real estate
                        if self._is_real_estate_job(title, description):
                            job_data = {
                                'title': title,
                                'company': company,
                                'location': job_location,
                                'description': description if description else None,
                                'source': 'Indeed',
                                'scraped_date': datetime.now().strftime('%Y-%m-%d')
                            }
                            
                            if job_url:
                                job_data['url'] = job_url
                            
                            # Check for duplicates
                            if not self._is_duplicate(job_data):
                                self.jobs.append(job_data)
                                logger.info(f"Added job: {title} at {company}")
                    
                    # Clean up
                    driver.quit()
                    
                    # Use a variable delay between queries
                    time.sleep(random.uniform(3, 6))
                    
                except Exception as e:
                    logger.error(f"Error during Selenium scraping of Indeed: {str(e)}")
                    if 'driver' in locals():
                        driver.quit()
            
        except ImportError:
            logger.warning("Selenium not available. Falling back to HTTP requests method.")
            
            # --- FALLBACK METHOD: Try with requests ---
            # Termes ultra spécifiques liés aux métiers de l'investissement immobilier, AM et dette
            additional_queries = [
                "investment manager immobilier",
                "asset manager immobilier",
                "fund manager real estate",
                "analyste investissement immobilier",
                "acquisitions immobilières",
                "debt fund immobilier",
                "structured finance real estate",
                "portfolio manager immobilier",
                "underwriter immobilier"                
            ]
            
            for current_query in additional_queries[:4]:  # Utiliser 4 requêtes au lieu de 2
                if self._check_timeout():
                    logger.warning("Time limit reached. Stopping scraping early.")
                    break
                    
                # Try using an RSS feed which is less likely to be blocked
                encoded_query = urllib.parse.quote_plus(current_query)
                encoded_location = urllib.parse.quote_plus(location)
                
                # Indeed job RSS feed URL (more reliable than HTML scraping)
                rss_url = f"https://fr.indeed.com/rss?q={encoded_query}&l={encoded_location}"
                
                try:
                    # Use a session with custom headers
                    session = requests.Session()
                    session.headers.update({
                        'User-Agent': ua.random,
                        'Accept': 'application/rss+xml,application/xml',
                        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7'
                    })
                    
                    response = session.get(rss_url, timeout=15)
                    
                    if response.status_code == 200:
                        # Parse RSS feed
                        soup = BeautifulSoup(response.text, 'xml')
                        items = soup.find_all('item')
                        
                        logger.info(f"Found {len(items)} jobs in Indeed RSS feed for query '{current_query}'")
                        
                        for item in items:
                            title_elem = item.find('title')
                            link_elem = item.find('link')
                            description_elem = item.find('description')
                            date_elem = item.find('pubDate')
                            
                            if title_elem:
                                title = title_elem.text.strip()
                                # Extract company from title - format is usually "Job Title - Company"                                
                                title_parts = title.split(' - ', 1)
                                actual_title = title_parts[0].strip()
                                company = title_parts[1].strip() if len(title_parts) > 1 else "Unknown"
                                
                                # Description might contain location
                                description = description_elem.text if description_elem else ""
                                job_location = location
                                
                                # Extract location from description if possible
                                location_match = re.search(r'Location: ([^<]+)', description)
                                if location_match:
                                    job_location = location_match.group(1).strip()
                                
                                # Check if job is related to real estate
                                if self._is_real_estate_job(actual_title, description):
                                    job_data = {
                                        'title': actual_title,
                                        'company': company,
                                        'location': job_location,
                                        'description': description,
                                        'source': 'Indeed (RSS)',
                                        'scraped_date': datetime.now().strftime('%Y-%m-%d')
                                    }
                                    
                                    if link_elem:
                                        job_data['url'] = link_elem.text.strip()
                                    
                                    # Check for duplicates
                                    if not self._is_duplicate(job_data):
                                        self.jobs.append(job_data)
                                        logger.info(f"Added job from RSS: {actual_title} at {company}")
                        
                    else:
                        logger.warning(f"Failed to retrieve Indeed RSS feed: Status code {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"Error scraping Indeed RSS for query '{current_query}': {str(e)}")
                
                # Use a reasonable delay between queries
                time.sleep(random.uniform(2, 4))
                
        # Final fallback: If we couldn't get any jobs, try the Indeed API through RapidAPI
        if len(self.jobs) - start_count == 0:
            try:
                logger.info("Attempting to use Indeed API through RapidAPI")
                # Note: This requires an API key and is subject to rate limits and costs
                # This is just a placeholder - you would need to sign up for RapidAPI and
                # get an API key for the Indeed API
                
                # Example code (commented out since it requires an API key):
                '''
                api_key = "YOUR_RAPIDAPI_KEY"  # Store this securely!
                
                rapidapi_url = "https://indeed-indeed.p.rapidapi.com/apisearch"
                rapidapi_headers = {
                    "x-rapidapi-key": api_key,
                    "x-rapidapi-host": "indeed-indeed.p.rapidapi.com"
                }
                
                querystring = {
                    "publisher": "indeed-indeed",
                    "v": "2",
                    "format": "json",
                    "callback": "",
                    "q": query,
                    "l": location,
                    "sort": "date",
                    "radius": "25",
                    "co": "fr"
                }
                
                response = requests.get(rapidapi_url, headers=rapidapi_headers, params=querystring)
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    
                    for job in results:
                        title = job.get('jobtitle', '')
                        company = job.get('company', 'Unknown')
                        job_location = job.get('formattedLocation', location)
                        description = job.get('snippet', '')
                        
                        if self._is_real_estate_job(title, description):
                            job_data = {
                                'title': title,
                                'company': company,
                                'location': job_location,
                                'description': description,
                                'source': 'Indeed (API)',
                                'scraped_date': datetime.now().strftime('%Y-%m-%d'),
                                'url': job.get('url', None)
                            }
                            
                            if not self._is_duplicate(job_data):
                                self.jobs.append(job_data)
                                logger.info(f"Added job from API: {title} at {company}")
                '''
                pass
                
            except Exception as e:
                logger.error(f"Error using RapidAPI for Indeed: {str(e)}")
        
        jobs_found = len(self.jobs) - start_count
        logger.info(f"Completed Indeed scrape. Total Indeed jobs: {jobs_found}")
        
        # If we still didn't find any jobs, add a dummy job for testing
        if jobs_found == 0 and os.environ.get('DEBUG_MODE') == '1':
            logger.warning("No jobs found from Indeed - adding a test job for debugging")
            test_job = {
                'title': "Agent Immobilier (TEST)",
                'company': "Indeed Test Company",
                'location': location,
                'description': "This is a test job added when Indeed scraping fails",
                'source': 'Indeed (Test)',
                'scraped_date': datetime.now().strftime('%Y-%m-%d')
            }
            self.jobs.append(test_job)
    
    def scrape_welcome_to_jungle(self, query="immobilier", location="Paris"):
        """Scrape Welcome to the Jungle with date filter support.
        
        WTTJ doesn't directly support date filtering in URL, but we can filter results after fetching.
        """
        """
        Scrape job listings from Welcome to the Jungle.
        This scraper targets one of the most popular tech and startup job platforms in France.
        Uses requests-based fallback if Selenium fails.
        
        Args:
            query (str): Job keyword to search for
            location (str): Location to search in
            
        Returns:
            int: Number of jobs found
        """
        logger.info(f"Starting Welcome to the Jungle scrape for '{query}' jobs in {location}")
        start_count = len(self.jobs)
        jobs_found = 0
        processed_urls = set()
        
        # Encode query and location for the URL
        encoded_query = urllib.parse.quote(query)
        encoded_location = urllib.parse.quote(location)
        
        # Format the URL for Welcome to the Jungle search
        base_url = f"https://www.welcometothejungle.com/fr/jobs?query={encoded_query}&page=1&aroundQuery={encoded_location}"
        logger.info(f"Scraping Welcome to the Jungle: {base_url}")
        
        # PRIMARY METHOD: Try with Selenium first for better results
        selenium_success = False
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.common.exceptions import TimeoutException, WebDriverException
            
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument(f"user-agent={ua.random}")
            options.add_argument("--window-size=1920,1080")
            
            # Add some browser-like characteristics to avoid detection
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            try:
                driver = webdriver.Chrome(options=options)
                # Set up a page load timeout
                driver.set_page_load_timeout(30)
                
                # Try different user agents if the first one fails
                for attempt in range(2):  # Try up to 2 times with different user agents
                    try:
                        driver.get(base_url)
                        
                        # Wait for any job-related content (more general selectors)
                        try:
                            # First try the specific selectors
                            WebDriverWait(driver, 15).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='job-card'], .job-card, .ais-Hits-item, article"))
                            )
                            
                            # Give a little more time for all cards to load
                            time.sleep(3)
                            
                            # Try multiple selectors to find job cards
                            job_cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='job-card']") or \
                                       driver.find_elements(By.CSS_SELECTOR, ".job-card") or \
                                       driver.find_elements(By.CSS_SELECTOR, ".ais-Hits-item") or \
                                       driver.find_elements(By.CSS_SELECTOR, "article")
                            
                            if job_cards:
                                logger.info(f"Found {len(job_cards)} potential job listings on Welcome to the Jungle")
                                
                                # Process each job card
                                for job_card in job_cards:
                                    try:
                                        # Try multiple selectors for job title
                                        title_element = None
                                        for selector in ["h3", "[data-testid='job-card-title']", ".job-title", ".title"]:
                                            try:
                                                title_element = job_card.find_element(By.CSS_SELECTOR, selector)
                                                if title_element:
                                                    break
                                            except Exception:
                                                continue
                                        
                                        if not title_element:
                                            continue
                                            
                                        title = title_element.text.strip()
                                        
                                        if not title or not self._is_real_estate_job(title):
                                            continue
                                        
                                        # Try multiple selectors for company name
                                        company_element = None
                                        for selector in ["[data-testid='job-card-company']", ".company-name", ".company"]:
                                            try:
                                                company_element = job_card.find_element(By.CSS_SELECTOR, selector)
                                                if company_element:
                                                    break
                                            except Exception:
                                                continue
                                        
                                        company = company_element.text.strip() if company_element else "Unknown"
                                        
                                        # Try multiple selectors for location
                                        location_element = None
                                        for selector in ["[data-testid='job-card-location']", ".location", ".sc-fzqARJ"]:
                                            try:
                                                location_element = job_card.find_element(By.CSS_SELECTOR, selector)
                                                if location_element:
                                                    break
                                            except Exception:
                                                continue
                                        
                                        job_location = location_element.text.strip() if location_element else location
                                        
                                        # Get URL - try to find a link
                                        url_element = None
                                        try:
                                            url_element = job_card.find_element(By.TAG_NAME, "a")
                                        except Exception:
                                            # If no direct link found, look for onclick attributes or other clues
                                            try:
                                                url_element = job_card
                                            except Exception:
                                                pass
                                        
                                        if not url_element:
                                            continue
                                            
                                        relative_url = url_element.get_attribute("href") if url_element.get_attribute("href") else None
                                        
                                        if not relative_url:
                                            continue
                                            
                                        # Convert relative URL to absolute if needed
                                        job_url = relative_url if relative_url.startswith('http') else f"https://www.welcometothejungle.com{relative_url}"
                                        
                                        # Skip if already processed
                                        if job_url in processed_urls:
                                            continue
                                        
                                        processed_urls.add(job_url)
                                        
                                        # Create job entry
                                        job_data = {
                                            'title': title,
                                            'company': company,
                                            'location': job_location,
                                            'source': 'Welcome to the Jungle',
                                            'url': job_url,
                                            'scraped_date': datetime.now().strftime('%Y-%m-%d')
                                        }
                                        
                                        # Add if not a duplicate
                                        if not self._is_duplicate(job_data):
                                            self.jobs.append(job_data)
                                            jobs_found += 1
                                            logger.info(f"Added job from Welcome to the Jungle: {title} at {company}")
                                    
                                    except Exception as e:
                                        logger.debug(f"Error processing a Welcome to the Jungle job: {str(e)}")
                                        continue
                                
                                selenium_success = True
                                break  # Success, no need to try with different user agent
                                
                            else:
                                logger.warning("No job cards found on Welcome to the Jungle with Selenium - retrying")
                                
                        except TimeoutException:
                            logger.warning("Timeout waiting for Welcome to the Jungle job cards to load")
                        
                        # If we couldn't find job cards with the current user agent, try with a different one
                        if not selenium_success and attempt < 1:  # Only change user agent and retry if not the last attempt
                            logger.info("Retrying with a different user agent...")
                            options.add_argument(f"user-agent={ua.random}")
                            driver.quit()
                            driver = webdriver.Chrome(options=options)
                    
                    except Exception as inner_e:
                        logger.warning(f"Error with Selenium attempt {attempt+1}: {str(inner_e)}")
                        if attempt < 1:  # Only retry if not the last attempt
                            options.add_argument(f"user-agent={ua.random}")
                            driver.quit()
                            driver = webdriver.Chrome(options=options)
                
                # Clean up
                driver.quit()
                    
            except (WebDriverException, Exception) as e:
                logger.warning(f"Error setting up Chrome driver: {str(e)}")
            
        except ImportError as e:
            logger.warning(f"Selenium not available: {str(e)}")
        
        # FALLBACK METHOD: Use requests if Selenium failed
        if not selenium_success:
            logger.info("Falling back to requests-based scraping for Welcome to the Jungle")
            try:
                # Use a browser-like user agent
                headers = {
                    'User-Agent': ua.random,
                    'Accept': 'text/html,application/xhtml+xml,application/xml',
                    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Referer': 'https://www.welcometothejungle.com/fr',
                    'Cache-Control': 'no-cache'
                }
                
                response = requests.get(base_url, headers=headers, timeout=20)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Try various selectors that might identify job listings
                    job_elements = soup.select('[data-testid="job-card"]') or \
                                 soup.select('.job-card') or \
                                 soup.select('article') or \
                                 soup.select('.ais-Hits-item')
                    
                    if job_elements:
                        logger.info(f"Found {len(job_elements)} potential job listings via requests method")
                        
                        for job in job_elements:
                            try:
                                # Try multiple selectors for title
                                title_element = job.select_one('h3') or \
                                              job.select_one('[data-testid="job-card-title"]') or \
                                              job.select_one('.job-title') or \
                                              job.select_one('.title')
                                              
                                if not title_element:
                                    continue
                                    
                                title = title_element.text.strip()
                                
                                if not title or not self._is_real_estate_job(title):
                                    continue
                                
                                # Try to get company name
                                company_element = job.select_one('[data-testid="job-card-company"]') or \
                                                job.select_one('.company-name') or \
                                                job.select_one('.company')
                                company = company_element.text.strip() if company_element else "Unknown"
                                
                                # Try to get location
                                location_element = job.select_one('[data-testid="job-card-location"]') or \
                                                 job.select_one('.location') or \
                                                 job.select_one('.sc-fzqARJ')
                                job_location = location_element.text.strip() if location_element else location
                                
                                # Get URL
                                url_element = job.select_one('a')  
                                if not url_element or not url_element.has_attr('href'):
                                    continue
                                    
                                relative_url = url_element['href']
                                
                                # Convert relative URL to absolute if needed
                                job_url = relative_url if relative_url.startswith('http') else f"https://www.welcometothejungle.com{relative_url}"
                                
                                # Skip if already processed
                                if job_url in processed_urls:
                                    continue
                                    
                                processed_urls.add(job_url)
                                
                                # Create job entry
                                job_data = {
                                    'title': title,
                                    'company': company,
                                    'location': job_location,
                                    'source': 'Welcome to the Jungle',
                                    'url': job_url,
                                    'scraped_date': datetime.now().strftime('%Y-%m-%d')
                                }
                                
                                # Add if not a duplicate
                                if not self._is_duplicate(job_data):
                                    self.jobs.append(job_data)
                                    jobs_found += 1
                                    logger.info(f"Added job from Welcome to the Jungle (requests): {title} at {company}")
                                
                            except Exception as e:
                                logger.debug(f"Error processing job element from requests: {str(e)}")
                                continue
                    else:
                        logger.warning("No job elements found in the requests response")
                else:
                    logger.warning(f"Failed to get Welcome to the Jungle page: Status code {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error in requests-based fallback: {str(e)}")
        
        # SECOND FALLBACK: If no real jobs found, add some fake examples for testing
        # Commented out for production, but can be enabled for debugging
        # if jobs_found == 0 and False:  # Disabled by default
        #     logger.warning("Adding sample real estate jobs from Welcome to the Jungle for testing")
        #     test_jobs = [
        #         {
        #             'title': 'Conseiller immobilier senior',
        #             'company': 'Agence Paris Luxury',
        #             'location': 'Paris',
        #             'source': 'Welcome to the Jungle (Example)',
        #             'url': 'https://www.welcometothejungle.com/fr/jobs/example-1',
        #             'scraped_date': datetime.now().strftime('%Y-%m-%d')
        #         },
        #         {
        #             'title': 'Agent immobilier indépendant',
        #             'company': 'Propriétés Parisiennes',
        #             'location': 'Paris',
        #             'source': 'Welcome to the Jungle (Example)',
        #             'url': 'https://www.welcometothejungle.com/fr/jobs/example-2',
        #             'scraped_date': datetime.now().strftime('%Y-%m-%d')
        #         }
        #     ]
        #     for job in test_jobs:
        #         if not self._is_duplicate(job):
        #             self.jobs.append(job)
        #             jobs_found += 1
        
        # Log results
        if jobs_found == 0:
            logger.warning("No real estate jobs found on Welcome to the Jungle")
            
        total_jobs = len(self.jobs) - start_count
        logger.info(f"Completed Welcome to the Jungle scrape. Total jobs found: {total_jobs}")
        return total_jobs
    

    
    def scrape_linkedin(self, query="real estate", location="Paris"):
        """Scrape LinkedIn with date filter support.
        
        If date_filter is set, adds appropriate URL parameters to filter by date.
        """
        """
        Scrape job listings from LinkedIn.
        
        Note: LinkedIn is challenging to scrape directly. This implementation may not work consistently
        as LinkedIn has mechanisms to prevent scraping.
        
        Args:
            query (str): Job keyword to search for
            location (str): Location to search in
        """
        logger.info(f"Starting to scrape LinkedIn for '{query}' jobs in {location}")
        
        query_formatted = query.replace(' ', '%20')
        location_formatted = location.replace(' ', '%20')
        
        for page in tqdm(range(0, self.max_pages * 25, 25), desc="LinkedIn Pages"):
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={query_formatted}&location={location_formatted}&start={page}"
            
            try:
                self.headers['User-Agent'] = ua.random  # Rotate user agent
                response = requests.get(url, headers=self.headers)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to retrieve LinkedIn page {page//25 + 1}: Status code {response.status_code}")
                    continue
                
                soup = BeautifulSoup(response.text, 'lxml')
                job_elements = soup.select('div.job-search-card')
                
                if not job_elements:
                    logger.info(f"No more job listings found on LinkedIn page {page//25 + 1}. Stopping LinkedIn scrape.")
                    break
                
                for job in job_elements:
                    title_element = job.select_one('h3.base-search-card__title')
                    company_element = job.select_one('h4.base-search-card__subtitle')
                    location_element = job.select_one('span.job-search-card__location')
                    
                    if title_element:
                        title = title_element.text.strip()
                        company = company_element.text.strip() if company_element else "Unknown"
                        job_location = location_element.text.strip() if location_element else location
                        
                        # Extract job URL
                        job_url = None
                        link_element = job.select_one('a.base-card__full-link') or job.select_one('a.job-search-card__link')
                        if link_element and link_element.has_attr('href'):
                            job_url = link_element['href']
                        
                        job_data = {
                            'title': title,
                            'company': company,
                            'location': job_location,
                            'source': 'LinkedIn',
                            'scraped_date': datetime.now().strftime('%Y-%m-%d')
                        }
                        
                        if job_url:
                            job_data['url'] = job_url
                        
                        self.jobs.append(job_data)
                        logger.debug(f"Added job: {title} at {company}")
                
                logger.info(f"Scraped {len(job_elements)} jobs from LinkedIn page {page//25 + 1}")
                self._random_delay()
                
            except Exception as e:
                logger.error(f"Error scraping LinkedIn page {page//25 + 1}: {str(e)}")
        
        logger.info(f"Completed LinkedIn scrape. Total LinkedIn jobs: {len(self.jobs) - self.prev_job_count}")
    
    def scrape_apec(self, query="immobilier", location="Paris"):
        """Scrape APEC with date filter support.
        
        If date_filter is set, adds appropriate URL parameters to filter by date.
        """
        """
        Scrape job listings from APEC.fr (French executive job site).
        This site is more reliable for scraping and specifically French-focused.
        
        Args:
            query (str): Job keyword to search for
            location (str): Location to search in
        """
        logger.info(f"Starting to scrape APEC for '{query}' jobs in {location}")
        start_count = len(self.jobs)
        
        # Try different query variations to improve results
        query_variations = [
            query, 
            f"{query} agent", 
            f"{query} conseiller", 
            f"{query} manager",
            f"{query} négociateur",
            f"{query} transaction",
            f"{query} vente"
        ]
        
        for current_query in query_variations:
            if self._check_timeout():
                logger.warning("Time limit reached. Stopping scraping early.")
                break
                
            # APEC has a reliable URL structure
            url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={current_query}&localisation={location}"
            
            try:
                # Simple request approach
                self.headers['User-Agent'] = ua.random
                response = requests.get(url, headers=self.headers, timeout=self.timeout)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to retrieve APEC page for query '{current_query}': Status code {response.status_code}")
                    continue
                
                soup = BeautifulSoup(response.text, 'lxml')
                
                # APEC has a consistent structure
                job_elements = soup.select('div.card-body') or soup.select('div.job-result-card')
                
                if not job_elements:
                    logger.info(f"No job listings found for APEC query '{current_query}'. Trying next query.")
                    continue
                
                logger.info(f"Found {len(job_elements)} potential job listings for APEC query '{current_query}'")
                
                for job in job_elements:
                    # Extract job details
                    title_element = job.select_one('h2.card-title') or job.select_one('h2.job-name')
                    company_element = job.select_one('div.card-offer__company') or job.select_one('div.company-name')
                    location_element = job.select_one('div.card-offer__location') or job.select_one('div.location')
                    description_element = job.select_one('div.card-offer__description') or job.select_one('div.description')
                    
                    if title_element:
                        title = title_element.text.strip()
                        company = company_element.text.strip() if company_element else "Unknown"
                        job_location = location_element.text.strip() if location_element else location
                        description = description_element.text.strip() if description_element else ""
                        
                        # Extract URL from title element or its parent
                        job_url = None
                        # Check if title_element is within an <a> tag or has an <a> parent
                        parent_a = title_element.find_parent('a')
                        if parent_a and parent_a.get('href'):
                            href = parent_a.get('href')
                            if href.startswith('/'):
                                job_url = f"https://www.apec.fr{href}"
                            else:
                                job_url = href
                        # If not found, look for any anchor within the job card
                        else:
                            card_anchor = job.find('a')
                            if card_anchor and card_anchor.get('href'):
                                href = card_anchor.get('href')
                                if href.startswith('/'):
                                    job_url = f"https://www.apec.fr{href}"
                                else:
                                    job_url = href
                        
                        # Use our improved keyword matching with both title and description
                        if self._is_real_estate_job(title, description):
                            job_data = {
                                'title': title,
                                'company': company,
                                'location': job_location,
                                'description': description,
                                'source': 'APEC',
                                'scraped_date': datetime.now().strftime('%Y-%m-%d')
                            }
                            
                            if job_url:
                                job_data['url'] = job_url
                            
                            # Avoid duplicates
                            if not any(job['title'] == title and job['company'] == company for job in self.jobs):
                                self.jobs.append(job_data)
                                logger.info(f"Added job: {title} at {company}")
                
                # Use a reasonable delay
                time.sleep(random.uniform(1.5, 3))
                
            except Exception as e:
                logger.error(f"Error scraping APEC for query '{current_query}': {str(e)}")
        
        jobs_found = len(self.jobs) - start_count
        logger.info(f"Completed APEC scrape. Total APEC jobs: {jobs_found}")
    
    def save_to_json(self, filename="real_estate_jobs_paris.json"):
        """
        Save the scraped job data to a JSON file.
        
        Args:
            filename (str): Name of the JSON file to save data to
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.jobs, f, ensure_ascii=False, indent=2)
            logger.info(f"Successfully saved {len(self.jobs)} jobs to {filename}")
        except Exception as e:
            logger.error(f"Error saving jobs to {filename}: {str(e)}")

def main():
    """Main function to run the job scraper."""
    parser = argparse.ArgumentParser(
        description='Job Scraper for Real Estate Positions in Paris',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Add a version number
    parser.add_argument('--version', action='version', version='Job Scraper v1.3.0')
    
    # Group arguments by category for better organization
    output_group = parser.add_argument_group('Output Options')
    output_group.add_argument('--output', type=str, default='real_estate_jobs_paris.json', 
                       help='Output JSON filename')
    output_group.add_argument('--backup-interval', type=int, default=60, 
                       help='Backup interval in seconds')
    output_group.add_argument('--report', action='store_true',
                       help='Generate a summary report after scraping')
                       
    scraper_group = parser.add_argument_group('Scraper Behavior')
    scraper_group.add_argument('--pages', type=int, default=5, 
                        help='Maximum number of pages to scrape per site')
    scraper_group.add_argument('--min-delay', type=float, default=1.5, 
                        help='Minimum delay between requests in seconds')
    scraper_group.add_argument('--max-delay', type=float, default=4.0, 
                        help='Maximum delay between requests in seconds')
    scraper_group.add_argument('--timeout', type=int, default=300, 
                        help='Maximum runtime in seconds')
    scraper_group.add_argument('--req-timeout', type=int, default=30, 
                        help='HTTP request timeout in seconds')
    scraper_group.add_argument('--retries', type=int, default=3, 
                        help='Number of retries for failed requests')
    
    query_group = parser.add_argument_group('Search Queries')
    query_group.add_argument('--query-fr', type=str, default='immobilier', 
                      help='French query term for real estate')
    query_group.add_argument('--query-en', type=str, default='real estate', 
                      help='English query term for real estate')
    query_group.add_argument('--additional-terms', type=str, 
                      help='Additional search terms to try beyond the default ones (comma-separated)')
    query_group.add_argument('--exclude', type=str, 
                      help='Keywords to exclude (comma-separated)')
    
    sites_group = parser.add_argument_group('Sites to Scrape')
    sites_group.add_argument('--skip-indeed', action='store_true', 
                      help='Skip Indeed scraping')
    sites_group.add_argument('--skip-apec', action='store_true', 
                      help='Skip APEC scraping')

    sites_group.add_argument('--skip-linkedin', action='store_true', 
                      help='Skip LinkedIn scraping')
    sites_group.add_argument('--skip-wttj', action='store_true', 
                      help='Skip Welcome to the Jungle scraping')
    sites_group.add_argument('--all-sites', action='store_true',
                      help='Scrape all available sites (overrides skip arguments)')
    
    args = parser.parse_args()
    
    # Create scraper with improved parameters
    scraper = JobScraper(
        max_pages=args.pages, 
        delay_min=args.min_delay, 
        delay_max=args.max_delay,
        timeout=args.req_timeout,
        max_retries=args.retries,
        max_runtime=args.timeout
    )
    
    # Track start time for backups
    start_time = time.time()
    last_backup = start_time
    
    # Failsafe file to recover data in case of crash
    failsafe_file = f"failsafe_{args.output}"
    
    # Try to load previous data if failsafe file exists
    try:
        if os.path.exists(failsafe_file):
            with open(failsafe_file, 'r', encoding='utf-8') as f:
                scraper.jobs = json.load(f)
                logger.info(f"Loaded {len(scraper.jobs)} jobs from failsafe file")
    except Exception as e:
        logger.error(f"Error loading failsafe file: {str(e)}")
    
    try:
        # Scrape Indeed (uses French)
        if not args.skip_indeed:
            scraper.scrape_indeed(query=args.query_fr, location="Paris")
            # Periodic backup after each site
            with open(failsafe_file, 'w', encoding='utf-8') as f:
                json.dump(scraper.jobs, f, ensure_ascii=False, indent=2)
        
        # Store count to track jobs from each source
        scraper.prev_job_count = len(scraper.jobs)
        
        # Scrape APEC (French site, more reliable)
        if not args.skip_apec:
            scraper.scrape_apec(query=args.query_fr, location="Paris")
            # Periodic backup
            with open(failsafe_file, 'w', encoding='utf-8') as f:
                json.dump(scraper.jobs, f, ensure_ascii=False, indent=2)
        
        # Update count for next source
        scraper.prev_job_count = len(scraper.jobs)
        
        # Update count for next source
        scraper.prev_job_count = len(scraper.jobs)
        
        # Try LinkedIn (may not work consistently due to scraping protections)
        if not args.skip_linkedin:
            try:
                # Try with primary query
                scraper.scrape_linkedin(query=args.query_en, location="Paris")
                
                # Default additional terms to try (always run these unless max runtime is reached)
                default_terms = [
                    "property management",
                    "asset management",
                    "real estate investment",
                    "property development",
                    "immobilier paris",
                    "gestion immobilière"
                ]
                
                # Add user-specified terms if provided
                if args.additional_terms:
                    additional_terms = [term.strip() for term in args.additional_terms.split(',')]
                    all_terms = default_terms + additional_terms
                else:
                    all_terms = default_terms
                
                # Search for all terms
                for term in all_terms:
                    if scraper._check_timeout():
                        logger.warning(f"Maximum runtime reached. Skipping remaining search terms.")
                        break
                    try:
                        logger.info(f"Trying additional LinkedIn search term: {term}")
                        scraper.scrape_linkedin(query=term, location="Paris")
                    except Exception as term_error:
                        logger.error(f"Error searching LinkedIn with term '{term}': {str(term_error)}")
                # Periodic backup
                with open(failsafe_file, 'w', encoding='utf-8') as f:
                    json.dump(scraper.jobs, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"LinkedIn scraping failed: {str(e)}")
                
        # Try Welcome to the Jungle (good source for French tech jobs)
        if not args.skip_wttj:
            try:
                # Try with primary query
                scraper.scrape_welcome_to_jungle(query=args.query_fr, location="Paris")
                
                # Try with English query too
                scraper.scrape_welcome_to_jungle(query=args.query_en, location="Paris")
                
                # Try with additional terms
                wttj_terms = [
                    "immobilier transaction",
                    "immobilier développement",
                    "property management paris",
                    "asset management immobilier",
                    "real estate investment paris"
                ]
                
                # Add user-specified terms if provided
                if args.additional_terms:
                    additional_terms = [term.strip() for term in args.additional_terms.split(',')]
                    wttj_terms.extend(additional_terms)
                
                # Limit to 3 additional terms to avoid long runtime
                wttj_terms = wttj_terms[:3]  # Just use the first few terms
                
                # Search for all terms
                for term in wttj_terms:
                    if scraper._check_timeout():
                        logger.warning(f"Maximum runtime reached. Skipping remaining Welcome to the Jungle search terms.")
                        break
                    try:
                        logger.info(f"Trying additional Welcome to the Jungle search term: {term}")
                        scraper.scrape_welcome_to_jungle(query=term, location="Paris")
                    except Exception as term_error:
                        logger.error(f"Error searching Welcome to the Jungle with term '{term}': {str(term_error)}")
                        
                # Periodic backup after Welcome to the Jungle
                with open(failsafe_file, 'w', encoding='utf-8') as f:
                    json.dump(scraper.jobs, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error in Welcome to the Jungle scraping: {str(e)}")
        
        # Regular backups during long operations
        current_time = time.time()
        if current_time - last_backup > args.backup_interval:
            with open(failsafe_file, 'w', encoding='utf-8') as f:
                json.dump(scraper.jobs, f, ensure_ascii=False, indent=2)
            last_backup = current_time
            logger.info(f"Periodic backup saved with {len(scraper.jobs)} jobs")
        
        # Check for duplicates and clean up data with a more robust approach
        original_count = len(scraper.jobs)
        
        # Create a more sophisticated job key that includes multiple fields
        # and normalizes text to better match duplicates
        unique_jobs = []
        seen_jobs = set()
        
        for job in scraper.jobs:
            # Create a more comprehensive key for better deduplication
            title = job.get('title', '').lower().strip()
            company = job.get('company', '').lower().strip()
            
            # Remove common words that don't help differentiate jobs
            for word in ['le', 'la', 'les', 'de', 'du', 'des', 'en', 'à', 'et', 'the', 'a', 'an', 'in', 'for', 'of']:
                title = title.replace(f' {word} ', ' ')
            
            # Create a key using both fields
            job_key = f"{title}|{company}"
            
            if job_key not in seen_jobs:
                seen_jobs.add(job_key)
                unique_jobs.append(job)
        
        # Update with deduplicated list
        scraper.jobs = unique_jobs
        duplicates_removed = original_count - len(unique_jobs)
        logger.info(f"Removed {duplicates_removed} duplicate jobs")
        
        # Save all collected jobs to JSON file
        scraper.save_to_json(filename=args.output)
        
        # If successful, clean up temporary files
        if os.path.exists(failsafe_file):
            try:
                os.remove(failsafe_file)
                logger.info(f"Removed temporary failsafe file: {failsafe_file}")
            except Exception as e:
                logger.warning(f"Failed to remove failsafe file: {str(e)}")
                
        # Clean up any interrupted files older than 7 days
        try:
            current_time = time.time()
            for filename in os.listdir('.'):
                if filename.startswith("interrupted_") and filename.endswith(".json"):
                    file_path = os.path.join('.', filename)
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > 7 * 24 * 60 * 60:  # 7 days in seconds
                        os.remove(file_path)
                        logger.info(f"Removed old interrupted file: {filename}")
        except Exception as e:
            logger.warning(f"Failed to clean up old files: {str(e)}")
        
        # Generate summary report if requested or if more than 50 jobs found
        if args.report or len(scraper.jobs) > 50:
            report_file = f"report_{os.path.splitext(args.output)[0]}.txt"
            try:
                with open(report_file, 'w') as f:
                    f.write(f"Job Scraping Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"==========================================================\n\n")
                    f.write(f"Total jobs collected: {len(scraper.jobs)}\n")
                    
                    # Source breakdown
                    sources = {}
                    for job in scraper.jobs:
                        source = job.get('source', 'Unknown')
                        sources[source] = sources.get(source, 0) + 1
                    
                    f.write("\nJobs by source:\n")
                    for source, count in sources.items():
                        f.write(f"  - {source}: {count} jobs\n")
                    
                    # Common keywords analysis
                    title_words = {}
                    for job in scraper.jobs:
                        for word in job.get('title', '').lower().split():
                            if len(word) > 3:  # Skip very short words
                                title_words[word] = title_words.get(word, 0) + 1
                    
                    f.write("\nMost common keywords in job titles:\n")
                    top_keywords = sorted(title_words.items(), key=lambda x: x[1], reverse=True)[:15]
                    for word, count in top_keywords:
                        f.write(f"  - {word}: {count} occurrences\n")
                    
                    f.write(f"\nTotal runtime: {time.time() - start_time:.2f} seconds\n")
                
                logger.info(f"Generated summary report: {report_file}")
            except Exception as e:
                logger.error(f"Failed to generate report: {str(e)}")
        
        logger.info(f"Job scraping completed. Total jobs collected: {len(scraper.jobs)}")
        logger.info(f"Total runtime: {time.time() - start_time:.2f} seconds")
        
    except KeyboardInterrupt:
        logger.warning("Job scraping interrupted by user")
        # Save what we have so far
        scraper.save_to_json(filename=f"interrupted_{args.output}")
        logger.info(f"Saved {len(scraper.jobs)} jobs to interrupted_{args.output}")
    except Exception as e:
        logger.error(f"Error during scraping: {str(e)}")
        # Save what we have so far
        scraper.save_to_json(filename=f"error_{args.output}")
        logger.info(f"Saved {len(scraper.jobs)} jobs to error_{args.output}")
    
if __name__ == "__main__":
    main()
