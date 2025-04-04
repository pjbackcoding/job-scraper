#!/usr/bin/env python3
"""
Job Scraper GUI Application

A modern, user-friendly GUI for the job scraper built with customtkinter.
Allows configuration of scraping parameters and displays results.
"""

import os
import json
import time
import threading
import tkinter as tk
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging
import pandas as pd

# Import the customtkinter library for modern UI
import customtkinter as ctk
from PIL import Image, ImageTk

# Import the JobScraper class from job_scraper.py
from job_scraper import JobScraper, setup_logging

# Set appearance mode and default color theme
ctk.set_appearance_mode("System")  # Modes: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"

# Configure logging
logger = setup_logging(log_file="gui_scraper.log")

class ScrollableJobFrame(ctk.CTkScrollableFrame):
    """A scrollable frame to display job listings with filtering capabilities."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.job_frames = []
        self.current_filter = ""
        
    def clear_jobs(self):
        """Clear all job listings from the frame."""
        for frame in self.job_frames:
            frame.destroy()
        self.job_frames = []
        
    def add_job(self, job: Dict[str, Any]):
        """Add a job listing to the scrollable frame."""
        # Create a frame for the job with a border
        job_frame = ctk.CTkFrame(self, fg_color=("gray90", "gray20"), corner_radius=10)
        job_frame.pack(fill="x", padx=10, pady=5, expand=True)
        
        # Job title (bold)
        title_label = ctk.CTkLabel(
            job_frame, 
            text=job.get("title", "Unknown Title"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        title_label.pack(anchor="w", padx=10, pady=(10, 0))
        
        # Company name
        company_label = ctk.CTkLabel(
            job_frame, 
            text=f"Company: {job.get('company', 'Unknown Company')}",
            font=ctk.CTkFont(size=12)
        )
        company_label.pack(anchor="w", padx=10, pady=(5, 0))
        
        # Location
        location_label = ctk.CTkLabel(
            job_frame, 
            text=f"Location: {job.get('location', 'Unknown Location')}",
            font=ctk.CTkFont(size=12)
        )
        location_label.pack(anchor="w", padx=10, pady=(5, 0))
        
        # Source and date
        source_date_label = ctk.CTkLabel(
            job_frame, 
            text=f"Source: {job.get('source', 'Unknown')} | Date: {job.get('scraped_date', 'Unknown')}",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray70")
        )
        source_date_label.pack(anchor="w", padx=10, pady=(5, 10))
        
        # Store this frame with the job data for filtering
        job_frame.job_data = job
        self.job_frames.append(job_frame)
        
    def filter_jobs(self, filter_text: str):
        """Filter job listings based on the search text."""
        self.current_filter = filter_text.lower()
        
        # Show/hide job frames based on filter
        for frame in self.job_frames:
            job_data = frame.job_data
            title = job_data.get("title", "").lower()
            company = job_data.get("company", "").lower()
            location = job_data.get("location", "").lower()
            
            # Check if filter text appears in any field
            if (self.current_filter in title or 
                self.current_filter in company or 
                self.current_filter in location):
                frame.pack(fill="x", padx=10, pady=5, expand=True)
            else:
                frame.pack_forget()


class JobScraperApp(ctk.CTk):
    """Main application window for the Job Scraper GUI."""
    
    def __init__(self):
        super().__init__()
        
        # Configure the window
        self.title("Job Scraper - Real Estate Paris")
        self.geometry("900x700")
        self.minsize(800, 600)
        
        # Initialize scraper state
        self.scraper = None
        self.scraping_thread = None
        self.is_scraping = False
        self.job_data = []
        
        # Create the UI components
        self.create_ui()
        
        # Try to load the most recent job data if available
        self.try_load_recent_jobs()
        
    def create_ui(self):
        """Create the UI components for the application."""
        # Main container that uses a grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header doesn't expand
        self.grid_rowconfigure(1, weight=1)  # Content area expands
        self.grid_rowconfigure(2, weight=0)  # Status bar doesn't expand
        
        # Create header frame
        self.create_header()
        
        # Create main content area with left sidebar and right content
        self.create_content_area()
        
        # Create status bar
        self.create_status_bar()
    
    def create_header(self):
        """Create the header section of the UI."""
        header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 0))
        
        # App title
        title_label = ctk.CTkLabel(
            header_frame, 
            text="Real Estate Job Scraper", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title_label.pack(side="left", padx=10)
        
        # Version info
        version_label = ctk.CTkLabel(
            header_frame,
            text="v1.3.0",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray70")
        )
        version_label.pack(side="left", padx=5, pady=5)
        
        # Search bar
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        
        search_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        search_frame.pack(side="right", padx=10)
        
        search_label = ctk.CTkLabel(search_frame, text="Search:")
        search_label.pack(side="left", padx=(0, 5))
        
        search_entry = ctk.CTkEntry(search_frame, width=200, textvariable=self.search_var)
        search_entry.pack(side="left")
    
    def create_content_area(self):
        """Create the main content area with sidebar and job listing area."""
        content_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        content_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        content_frame.grid_columnconfigure(0, weight=0)  # Sidebar doesn't expand
        content_frame.grid_columnconfigure(1, weight=1)  # Main content expands
        content_frame.grid_rowconfigure(0, weight=1)     # Both expand vertically
        
        # Create sidebar with controls
        self.create_sidebar(content_frame)
        
        # Create job listings area
        self.create_job_listings(content_frame)
    
    def create_sidebar(self, parent):
        """Create the sidebar with scraper controls."""
        sidebar = ctk.CTkFrame(parent, width=250)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 20))
        
        # Settings label
        settings_label = ctk.CTkLabel(
            sidebar, 
            text="Scraper Settings",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        settings_label.pack(anchor="w", padx=15, pady=(15, 10))
        
        # Query terms
        query_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        query_frame.pack(fill="x", padx=15, pady=5)
        
        query_label = ctk.CTkLabel(query_frame, text="Query (FR):")
        query_label.grid(row=0, column=0, sticky="w", pady=5)
        
        self.query_fr_var = tk.StringVar(value="immobilier")
        query_fr_entry = ctk.CTkEntry(query_frame, textvariable=self.query_fr_var)
        query_fr_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        query_en_label = ctk.CTkLabel(query_frame, text="Query (EN):")
        query_en_label.grid(row=1, column=0, sticky="w", pady=5)
        
        self.query_en_var = tk.StringVar(value="real estate")
        query_en_entry = ctk.CTkEntry(query_frame, textvariable=self.query_en_var)
        query_en_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        query_frame.grid_columnconfigure(1, weight=1)
        
        # Location
        location_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        location_frame.pack(fill="x", padx=15, pady=5)
        
        location_label = ctk.CTkLabel(location_frame, text="Location:")
        location_label.grid(row=0, column=0, sticky="w", pady=5)
        
        self.location_var = tk.StringVar(value="Paris")
        location_entry = ctk.CTkEntry(location_frame, textvariable=self.location_var)
        location_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        location_frame.grid_columnconfigure(1, weight=1)
        
        # Maximum pages
        pages_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        pages_frame.pack(fill="x", padx=15, pady=5)
        
        pages_label = ctk.CTkLabel(pages_frame, text="Max Pages:")
        pages_label.grid(row=0, column=0, sticky="w", pady=5)
        
        self.max_pages_var = tk.IntVar(value=5)
        pages_slider = ctk.CTkSlider(
            pages_frame, 
            from_=1, 
            to=10, 
            number_of_steps=9,
            variable=self.max_pages_var,
            command=self._update_pages_label
        )
        pages_slider.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        self.pages_value_label = ctk.CTkLabel(pages_frame, text="5")
        self.pages_value_label.grid(row=0, column=2, padx=(5, 0), pady=5)
        
        pages_frame.grid_columnconfigure(1, weight=1)
        
        # Sites to scrape
        sites_label = ctk.CTkLabel(
            sidebar, 
            text="Sites to Scrape:",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        sites_label.pack(anchor="w", padx=15, pady=(15, 5))
        
        # Create checkboxes for each site
        self.indeed_var = tk.BooleanVar(value=True)
        indeed_cb = ctk.CTkCheckBox(
            sidebar, 
            text="Indeed", 
            variable=self.indeed_var,
            onvalue=True, 
            offvalue=False
        )
        indeed_cb.pack(anchor="w", padx=20, pady=5)
        
        self.apec_var = tk.BooleanVar(value=True)
        apec_cb = ctk.CTkCheckBox(
            sidebar, 
            text="APEC", 
            variable=self.apec_var,
            onvalue=True, 
            offvalue=False
        )
        apec_cb.pack(anchor="w", padx=20, pady=5)
        
        self.linkedin_var = tk.BooleanVar(value=True)
        linkedin_cb = ctk.CTkCheckBox(
            sidebar, 
            text="LinkedIn", 
            variable=self.linkedin_var,
            onvalue=True, 
            offvalue=False
        )
        linkedin_cb.pack(anchor="w", padx=20, pady=5)
        
        self.wttj_var = tk.BooleanVar(value=True)
        wttj_cb = ctk.CTkCheckBox(
            sidebar, 
            text="Welcome to the Jungle", 
            variable=self.wttj_var,
            onvalue=True, 
            offvalue=False
        )
        wttj_cb.pack(anchor="w", padx=20, pady=5)
        
        # Action buttons
        button_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        button_frame.pack(fill="x", padx=15, pady=(20, 15))
        
        # Start scraping button
        self.start_button = ctk.CTkButton(
            button_frame, 
            text="Start Scraping",
            command=self.start_scraping,
            fg_color=("green4", "green4"),
            hover_color=("green3", "green3")
        )
        self.start_button.pack(fill="x", pady=(0, 5))
        
        # Stop scraping button (disabled by default)
        self.stop_button = ctk.CTkButton(
            button_frame, 
            text="Stop Scraping",
            command=self.stop_scraping,
            fg_color=("firebrick3", "firebrick3"),
            hover_color=("firebrick2", "firebrick2"),
            state="disabled"
        )
        self.stop_button.pack(fill="x", pady=(0, 5))
        
        # Load results button
        self.load_button = ctk.CTkButton(
            button_frame, 
            text="Load Results",
            command=self.load_results,
            fg_color=("royalblue3", "royalblue3"),
            hover_color=("royalblue2", "royalblue2")
        )
        self.load_button.pack(fill="x", pady=(0, 5))
        
        # Export to Excel button
        self.export_button = ctk.CTkButton(
            button_frame, 
            text="Export to Excel",
            command=self.export_to_excel,
            fg_color=("darkorchid3", "darkorchid3"),
            hover_color=("darkorchid2", "darkorchid2")
        )
        self.export_button.pack(fill="x", pady=(0, 5))
    
    def create_job_listings(self, parent):
        """Create the area for displaying job listings."""
        # Container frame
        listings_frame = ctk.CTkFrame(parent)
        listings_frame.grid(row=0, column=1, sticky="nsew")
        listings_frame.grid_columnconfigure(0, weight=1)
        listings_frame.grid_rowconfigure(0, weight=0)  # Header 
        listings_frame.grid_rowconfigure(1, weight=1)  # Listings area
        
        # Results header
        results_header = ctk.CTkFrame(listings_frame, fg_color="transparent")
        results_header.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        
        self.results_label = ctk.CTkLabel(
            results_header, 
            text="Job Listings (0 results)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.results_label.pack(side="left")
        
        # Job listings scrollable frame
        self.jobs_frame = ScrollableJobFrame(listings_frame)
        self.jobs_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
    
    def create_status_bar(self):
        """Create the status bar at the bottom of the UI."""
        status_bar = ctk.CTkFrame(self, height=25, corner_radius=0)
        status_bar.grid(row=2, column=0, sticky="ew")
        
        self.status_label = ctk.CTkLabel(
            status_bar, 
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray70")
        )
        self.status_label.pack(side="left", padx=10)
        
        # Progress bar for scraping
        self.progress_bar = ctk.CTkProgressBar(status_bar, width=200)
        self.progress_bar.pack(side="right", padx=10, pady=5)
        self.progress_bar.set(0)  # Initially at 0
    
    def _update_pages_label(self, value):
        """Update the pages value label when the slider changes."""
        pages = int(value)
        self.pages_value_label.configure(text=str(pages))
    
    def _on_search_changed(self, *args):
        """Handle changes to the search bar."""
        search_text = self.search_var.get()
        self.jobs_frame.filter_jobs(search_text)
    
    def update_status(self, message, is_progress=False, progress_value=None):
        """Update the status bar with a message and optionally the progress bar."""
        self.status_label.configure(text=message)
        
        if is_progress and progress_value is not None:
            self.progress_bar.set(progress_value)
        
        # Force update of the UI
        self.update_idletasks()
    
    def try_load_recent_jobs(self):
        """Try to load the most recent job data file if available."""
        default_file = "real_estate_jobs_paris.json"
        if os.path.exists(default_file):
            try:
                with open(default_file, 'r', encoding='utf-8') as f:
                    jobs = json.load(f)
                    self.job_data = jobs
                    self.update_job_listings(jobs)
                    self.update_status(f"Loaded {len(jobs)} jobs from {default_file}")
            except Exception as e:
                logger.error(f"Error loading recent jobs: {str(e)}")
                self.update_status(f"Error loading recent jobs: {str(e)}")
    
    def update_job_listings(self, jobs: List[Dict[str, Any]]):
        """Update the job listings display with the provided job data."""
        # Clear existing listings
        self.jobs_frame.clear_jobs()
        
        # Update results count
        self.results_label.configure(text=f"Job Listings ({len(jobs)} results)")
        
        # Add each job to the scrollable frame
        for job in jobs:
            self.jobs_frame.add_job(job)
    
    def start_scraping(self):
        """Start the job scraping process."""
        if self.is_scraping:
            return
        
        # Get settings from UI
        query_fr = self.query_fr_var.get()
        query_en = self.query_en_var.get()
        location = self.location_var.get()
        max_pages = self.max_pages_var.get()
        
        # Check which sites to scrape
        sites_to_scrape = {
            "indeed": self.indeed_var.get(),
            "apec": self.apec_var.get(),
            "linkedin": self.linkedin_var.get(),
            "wttj": self.wttj_var.get()
        }
        
        # Validate input
        if not query_fr and not query_en:
            self.update_status("Error: Please enter at least one search query.")
            return
        
        if not location:
            self.update_status("Error: Please enter a location.")
            return
        
        if not any(sites_to_scrape.values()):
            self.update_status("Error: Please select at least one site to scrape.")
            return
        
        # Update UI state for scraping
        self.is_scraping = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.load_button.configure(state="disabled")
        
        # Update status
        self.update_status("Starting scraper...", is_progress=True, progress_value=0.05)
        
        # Start scraping in a separate thread
        self.scraping_thread = threading.Thread(
            target=self._run_scraper, 
            args=(query_fr, query_en, location, max_pages, sites_to_scrape)
        )
        self.scraping_thread.daemon = True
        self.scraping_thread.start()
    
    def _run_scraper(self, query_fr, query_en, location, max_pages, sites_to_scrape):
        """Run the scraper in a background thread to avoid blocking the UI."""
        try:
            # In a thread, we need to avoid using signals, but still use the real scraping functionality
            import copy
            
            # Create a thread-safe wrapper around the JobScraper class
            # that removes signal handlers but keeps all the scraping functionality
            class ThreadSafeJobScraper(JobScraper):
                def __init__(self, **kwargs):
                    # Initialize with parent class, but override signal setup
                    # Call the parent's __init__ but capture and modify its behavior
                    # Save original signal module functions
                    import signal
                    self._original_signal = signal.signal
                    
                    # Override signal.signal temporarily to prevent it from being used
                    def dummy_signal(sig, handler):
                        # Just log that we're skipping signal setup
                        logging.debug(f"Skipping signal setup for {sig} in threaded context")
                        return None
                    
                    # Replace signal.signal with our dummy version
                    signal.signal = dummy_signal
                    
                    try:
                        # Call parent constructor with the dummy signal handler
                        super().__init__(**kwargs)
                    finally:
                        # Restore original signal.signal function
                        signal.signal = self._original_signal
                    
                    # Set interrupted flag that we'll check instead of using signals
                    self.interrupted = False
                
                # Override _handle_interrupt to avoid using signals
                def _handle_interrupt(self, *args):
                    logging.info("Scraper interrupted")
                    self.interrupted = True
                    
                    # Still save progress when interrupted
                    try:
                        if self.jobs:
                            filename = f"interrupted_scraper_{int(time.time())}.json"
                            with open(filename, 'w', encoding='utf-8') as f:
                                json.dump(self.jobs, f, ensure_ascii=False, indent=2)
                            logging.info(f"Saved current progress to {filename}")
                    except Exception as e:
                        logging.error(f"Failed to save progress during interrupt: {str(e)}")
            
            # Create our thread-safe scraper instance with the real scraping functionality
            self.scraper = ThreadSafeJobScraper(
                max_pages=max_pages, 
                delay_min=1.5, 
                delay_max=4.0,
                timeout=30,
                max_retries=3,
                max_runtime=3600  # 1 hour max runtime
            )
            
            # Create a counter for progress tracking
            total_sites = sum(1 for enabled in sites_to_scrape.values() if enabled)
            sites_completed = 0
            
            # Run scraping operations based on selected sites
            if sites_to_scrape["indeed"] and not self.scraper.interrupted:
                self._update_ui_status(f"Scraping Indeed for '{query_fr}' in {location}...", 
                                      progress=sites_completed / total_sites)
                self.scraper.scrape_indeed(query=query_fr, location=location)
                sites_completed += 1
            
            if sites_to_scrape["apec"] and not self.scraper.interrupted:
                self._update_ui_status(f"Scraping APEC for '{query_fr}' in {location}...", 
                                      progress=sites_completed / total_sites)
                self.scraper.scrape_apec(query=query_fr, location=location)
                sites_completed += 1
            
            if sites_to_scrape["linkedin"] and not self.scraper.interrupted:
                self._update_ui_status(f"Scraping LinkedIn for '{query_en}' in {location}...", 
                                      progress=sites_completed / total_sites)
                self.scraper.scrape_linkedin(query=query_en, location=location)
                sites_completed += 1
            
            if sites_to_scrape["wttj"] and not self.scraper.interrupted:
                self._update_ui_status(f"Scraping Welcome to the Jungle for '{query_fr}' in {location}...", 
                                      progress=sites_completed / total_sites)
                self.scraper.scrape_welcome_to_jungle(query=query_fr, location=location)
                sites_completed += 1
            
            # Save the results
            self._update_ui_status("Saving results...", progress=0.95)
            output_file = f"real_estate_jobs_{location.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.json"
            self.scraper.save_to_json(filename=output_file)
            
            # Get the results and update UI
            self.job_data = self.scraper.jobs
            self._update_ui_after_scraping(output_file)
            
        except Exception as e:
            logger.error(f"Error during scraping: {str(e)}")
            self._update_ui_status(f"Error during scraping: {str(e)}", progress=0)
            self._update_ui_after_error()
    
    def _update_ui_status(self, message, progress=None):
        """Update the UI status from the background thread."""
        if self.is_scraping:
            self.after(0, lambda: self.update_status(message, is_progress=True, progress_value=progress))
    
    def _update_ui_after_scraping(self, output_file):
        """Update the UI after scraping is complete."""
        def update():
            self.is_scraping = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.load_button.configure(state="normal")
            
            # Update the job listings
            self.update_job_listings(self.job_data)
            
            # Update status with final message
            self.update_status(
                f"Scraping completed. Found {len(self.job_data)} jobs. Saved to {output_file}",
                is_progress=True,
                progress_value=1.0
            )
        
        self.after(0, update)
    
    def _update_ui_after_error(self):
        """Update the UI after an error occurs."""
        def update():
            self.is_scraping = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.load_button.configure(state="normal")
            self.progress_bar.set(0)
        
        self.after(0, update)
    
    def stop_scraping(self):
        """Stop the ongoing scraping process."""
        if self.is_scraping and self.scraper:
            self.update_status("Stopping scraper...", is_progress=True, progress_value=0.5)
            self.scraper.interrupted = True
            
            # Wait for the thread to complete in a non-blocking way
            self.after(100, self._check_thread_completion)
    
    def _check_thread_completion(self):
        """Check if the scraping thread has completed after stopping."""
        if self.scraping_thread and self.scraping_thread.is_alive():
            # Still running, check again in 100ms
            self.after(100, self._check_thread_completion)
        else:
            # Thread has stopped
            self.is_scraping = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.load_button.configure(state="normal")
            self.update_status("Scraper stopped by user", is_progress=True, progress_value=0)
    
    def load_results(self):
        """Load job results from a JSON file."""
        try:
            # Simple file dialog to choose a file
            import tkinter.filedialog as filedialog
            
            file_path = filedialog.askopenfilename(
                title="Select Job Data File",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
                initialdir=os.getcwd()
            )
            
            if file_path:
                with open(file_path, 'r', encoding='utf-8') as f:
                    jobs = json.load(f)
                    self.job_data = jobs
                    self.update_job_listings(jobs)
                    self.update_status(f"Loaded {len(jobs)} jobs from {os.path.basename(file_path)}")
        except Exception as e:
            logger.error(f"Error loading job data: {str(e)}")
            self.update_status(f"Error loading job data: {str(e)}")
    
    def export_to_excel(self):
        """Export job data to Excel format."""
        try:
            # Check if we have job data to export
            if not self.job_data:
                self.update_status("No job data to export. Please load or scrape jobs first.")
                return
            
            # Create a file dialog to select where to save the Excel file
            import tkinter.filedialog as filedialog
            
            default_filename = f"job_listings_{datetime.now().strftime('%Y%m%d')}.xlsx"
            file_path = filedialog.asksaveasfilename(
                title="Save Excel File",
                defaultextension=".xlsx",
                filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")],
                initialdir=os.getcwd(),
                initialfile=default_filename
            )
            
            if not file_path:
                # User cancelled the dialog
                return
            
            # Update status
            self.update_status("Exporting to Excel...", is_progress=True, progress_value=0.2)
            
            # Convert job data to DataFrame
            df = pd.DataFrame(self.job_data)
            
            # Ensure we have all expected columns, add empty ones if missing
            expected_columns = ['title', 'company', 'location', 'description', 'url', 'source', 'scraped_date']
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = ""
            
            # Reorder columns for better readability
            ordered_columns = [
                'title', 'company', 'location', 'source', 'scraped_date', 'description', 'url'
            ]
            # Only include columns that exist in the DataFrame
            ordered_columns = [col for col in ordered_columns if col in df.columns]
            # Add any additional columns that weren't in our expected list
            remaining_columns = [col for col in df.columns if col not in ordered_columns]
            final_columns = ordered_columns + remaining_columns
            
            # Reorder the DataFrame columns
            df = df[final_columns]
            
            # Update progress
            self.update_status("Formatting Excel file...", is_progress=True, progress_value=0.5)
            
            # Export to Excel with nice formatting
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Job Listings')
                
                # Get the worksheet to apply formatting
                worksheet = writer.sheets['Job Listings']
                
                # Auto-adjust column widths based on content
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    # Skip description column as it can be very long
                    if column[0].value == 'description':
                        worksheet.column_dimensions[column_letter].width = 50
                        continue
                    
                    for cell in column:
                        if cell.value:
                            max_length = max(max_length, len(str(cell.value)))
                    
                    # Set width with some padding
                    adjusted_width = max(max_length + 2, 10)
                    # Cap width to avoid excessively wide columns
                    worksheet.column_dimensions[column_letter].width = min(adjusted_width, 40)
                
                # Format the header row
                for cell in worksheet[1]:
                    cell.font = writer.book.create_font(bold=True)
            
            # Update status with completion message
            self.update_status(
                f"Successfully exported {len(self.job_data)} jobs to {os.path.basename(file_path)}",
                is_progress=True,
                progress_value=1.0
            )
            
            # Reset progress bar after a delay
            self.after(3000, lambda: self.progress_bar.set(0))
            
        except Exception as e:
            logger.error(f"Error exporting to Excel: {str(e)}")
            self.update_status(f"Error exporting to Excel: {str(e)}")
            self.progress_bar.set(0)


if __name__ == "__main__":
    app = JobScraperApp()
    app.mainloop()
