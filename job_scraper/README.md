# Real Estate Job Scraper for Paris

An enhanced Python-based web scraper that collects real estate job listings in Paris from multiple job search websites and saves them to a JSON file. This scraper includes several reliability and safety features to ensure successful data collection and prevent issues.

## Features

- Scrapes real estate job listings from multiple sources:
  - Indeed France
  - LinkedIn
  - APEC.fr (France-specific job site for managers/executives)
  - Welcome to the Jungle (French tech job platform)
- Enhanced anti-detection mechanisms:
  - Smart rotating user agents with fallback mechanism
  - Realistic browser headers
  - Random delays between requests
  - Cookie collection by visiting homepages first
- Robust error handling and recovery:
  - Automatic retry with exponential backoff
  - Multiple URL format attempts
  - Multiple HTML selector attempts as websites change
  - Graceful termination with SIGINT/SIGTERM handling
- Safety features:
  - Runtime timeout to prevent overlong runs
  - Automatic backups during scraping
  - Recovery from previous interrupted runs
  - Failsafe to save data even on errors
  - Graceful exit handling for clean termination
- Intelligent job filtering and deduplication:
  - Advanced filtering with keyword matching
  - Sophisticated deduplication algorithm
  - Option to exclude specific keywords
- Detailed logging and reporting:
  - Comprehensive console and file logging
  - Optional summary report generation

## Installation

1. Make sure you have Python 3.6+ installed
2. Install required packages:

```bash
pip install -r requirements.txt
```

## Usage

Basic usage:

```bash
python job_scraper.py
```

This will scrape real estate jobs in Paris and save them to `real_estate_jobs_paris.json`.

### Advanced Options

```bash
python job_scraper.py --pages 5 --min-delay 2 --max-delay 5 --timeout 600 --output my_jobs.json --report
```

Command line arguments are organized into categories:

#### Output Options

- `--output`: Output JSON filename (default: real_estate_jobs_paris.json)
- `--backup-interval`: Interval in seconds for periodic backups (default: 60)
- `--report`: Generate a summary report after scraping

#### Scraper Behavior

- `--pages`: Maximum number of pages to scrape per site (default: 3)
- `--min-delay`: Minimum delay between requests in seconds (default: 1.5)
- `--max-delay`: Maximum delay between requests in seconds (default: 4.0)
- `--timeout`: Maximum runtime in seconds (default: 300)
- `--req-timeout`: HTTP request timeout in seconds (default: 30)
- `--retries`: Number of retries for failed requests (default: 3)

#### Search Queries

- `--query-fr`: French query term for real estate (default: immobilier)
- `--query-en`: English query term for real estate (default: real estate)
- `--exclude`: Keywords to exclude from results (comma-separated)

### Selective Scraping

You can choose to skip specific sites if they're causing issues:

```bash
python job_scraper.py --skip-indeed --skip-wttj
```

Sites options:
- `--skip-indeed`: Skip Indeed scraping
- `--skip-wttj`: Skip Welcome to the Jungle scraping
- `--skip-linkedin`: Skip LinkedIn scraping
- `--skip-apec`: Skip APEC.fr scraping
- `--all-sites`: Scrape all available sites (overrides skip arguments)

### Example Commands

```bash
# Scrape all sites with increased delay between requests
python job_scraper.py --min-delay 3 --max-delay 6

# Scrape only Indeed and APEC with a specific output file
python job_scraper.py --skip-linkedin --skip-wttj --output real_estate_jobs_custom.json

# Generate a report after scraping
python job_scraper.py --report

# Exclude jobs containing certain keywords
python job_scraper.py --exclude "stagiaire,stage,internship"
```

## Crash Recovery

If the scraper crashes or is interrupted, it saves data incrementally:

1. Periodic backups are automatically created during execution
2. If interrupted, a failsafe file is created with current progress
3. On next run, the scraper will automatically resume from the last backup

## Important Notes

- Web scraping may be against the terms of service of some websites
- Use responsibly and at your own risk
- The script implements multiple safeguards to avoid overloading target websites
- If the script is interrupted, it will create a backup file that will be automatically loaded on the next run
- The scraper includes a built-in failsafe timeout to prevent indefinite hanging
- All errors are logged to the scraper.log file for troubleshooting
