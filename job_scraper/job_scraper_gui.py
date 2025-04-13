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
from typing import List, Dict, Any, Optional, Tuple
import logging
import pandas as pd
import openai
import webbrowser

# Import the customtkinter library for modern UI
import customtkinter as ctk
from PIL import Image, ImageTk

# Import the JobScraper class from job_scraper.py
from job_scraper import JobScraper, setup_logging

# Set appearance mode and default color theme
ctk.set_appearance_mode("System")  # Modes: "System", "Dark", "Light"
ctk.set_default_color_theme("green")  # Using green theme for a fresher look

# Configure logging
logger = setup_logging(log_file="gui_scraper.log")

# OpenAI client configuration
openai_client = None

def setup_openai_client(api_key=None):
    """Setup OpenAI client with API key from environment variable or provided key.
    
    Args:
        api_key: Optional API key to use. If not provided, will check environment variable.
        
    Returns:
        True if client was successfully setup, False otherwise.
    """
    global openai_client
    
    # Use provided API key or check environment variable
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    
    if api_key:
        try:
            openai_client = openai.OpenAI(api_key=api_key)
            # Save the API key to environment variable for future use
            os.environ["OPENAI_API_KEY"] = api_key
            return True
        except Exception as e:
            logger.error(f"Error setting up OpenAI client: {str(e)}")
            return False
    
    return False

# Check for API key in a local config file (not committed to Git)
try:
    config_file = os.path.join(os.path.dirname(__file__), '.api_config')
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith('OPENAI_API_KEY='):
                    os.environ["OPENAI_API_KEY"] = line.split('=', 1)[1].strip()
                    break
except Exception as e:
    logger.warning(f"Could not load API key from config file: {str(e)}")

# Setup OpenAI client with the environment variable
setup_openai_client()


def evaluate_salary(job_title: str, company: str) -> Tuple[float, str]:
    """Evaluate salary for a job using OpenAI API.
    
    Args:
        job_title: The job title to evaluate
        company: The company offering the job
        
    Returns:
        Tuple containing the estimated salary as float and the currency
    """
    global openai_client
    
    if not openai_client:
        if not setup_openai_client():
            return (0, "EUR")
    
    try:
        # Prompt the model to estimate the salary with more specific instructions
        prompt = f"Je suis en France. Estime le salaire annuel en euros pour un poste de '{job_title}' chez '{company}' à Paris, France. Donne seulement le montant numérique sans texte. Par exemple: 45000"
        
        # Call OpenAI API with gpt-4o-mini model
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Using the correct model name
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # Lower temperature for more predictable/factual responses
            max_tokens=10  # Only need a short response with the salary
        )
        
        # Log the full response for debugging
        logger.info(f"Full API response: {response}")
        
        # Extract the salary from the response
        salary_text = response.choices[0].message.content.strip()
        logger.info(f"Salary response content: {salary_text}")
        
        # Try to parse the salary as a number
        # Remove any non-numeric characters except decimal point
        salary_text = ''.join([c for c in salary_text if c.isdigit() or c == '.'])
        
        # Check if we have a valid number
        if not salary_text:
            logger.error(f"No valid salary numbers found in response: {response.choices[0].message.content}")
            return (0, "EUR")
            
        salary = float(salary_text)
        
        return (salary, "EUR")
        
    except Exception as e:
        logger.error(f"Error evaluating salary: {str(e)}")
        return (0, "EUR")

class ScrollableJobFrame(ctk.CTkScrollableFrame):
    """A scrollable frame to display job listings with filtering capabilities."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.job_frames = []
        self.current_filter = ""
        self.sort_key = "scraped_date"  # Default sort key
        self.sort_ascending = False  # Default sort order (newest first)
        self.collapsed_view = False  # Default expanded view
        self.evaluating_all = False  # Flag to track if we're currently evaluating all jobs
        self.date_filter = None  # Date filter (None = show all dates)
        
    def clear_jobs(self):
        """Clear all job listings from the frame."""
        for frame in self.job_frames:
            frame.destroy()
        self.job_frames = []
        
    def add_job(self, job: Dict[str, Any]):
        """Add a job listing to the scrollable frame."""
        # Create a frame for the job with improved visual styling
        job_frame = ctk.CTkFrame(self, fg_color=("gray95", "gray17"), corner_radius=12, border_width=1, border_color=("gray80", "gray30"))
        job_frame.pack(fill="x", padx=12, pady=7, expand=True)
        
        # Create top row with title and evaluate button
        top_row = ctk.CTkFrame(job_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=10, pady=(10, 0))
        top_row.grid_columnconfigure(0, weight=1)  # Make title expand
        
        # Job title (bold) with clickable link
        job_url = job.get("url", "")
        title_text = job.get("title", "Unknown Title")
        
        title_label = ctk.CTkLabel(
            top_row, 
            text=title_text,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            cursor="hand2" if job_url else "arrow"
        )
        title_label.grid(row=0, column=0, sticky="w")
        
        # Add click binding to the title if URL exists
        if job_url:
            title_label.bind("<Button-1>", lambda e, url=job_url: self._open_job_url(url))
            # Add underline to indicate clickable
            title_label.configure(text_color=("blue", "light blue"))
        
        # Evaluate button with improved styling
        evaluate_button = ctk.CTkButton(
            top_row,
            text="💰 Evaluate",  # Added emoji for visual indicator
            command=lambda j=job, f=job_frame: self._evaluate_job(j, f),
            width=90,
            height=28,
            fg_color=("#3a7ebf", "#1f538d"),  # Better color contrast
            hover_color=("#2d6db5", "#1a477a"),
            corner_radius=8,
            border_width=0,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        evaluate_button.grid(row=0, column=1, padx=(5, 5))
        
        # Add URL button if URL exists
        if job_url:
            url_button = ctk.CTkButton(
                top_row,
                text="🔗 Voir l'annonce",  # Added emoji for visual indicator
                command=lambda url=job_url: self._open_job_url(url),
                width=120,
                height=28,
                fg_color=("#2e8b57", "#1e5631"),  # Better color contrast
                hover_color=("#227346", "#19472a"),
                corner_radius=8,
                border_width=0,
                font=ctk.CTkFont(size=12, weight="bold")
            )
            url_button.grid(row=0, column=2, padx=(0, 0))
        
        # Store reference to evaluate button
        job_frame.evaluate_button = evaluate_button
        
        # Company name
        company_label = ctk.CTkLabel(
            job_frame, 
            text=f"Company: {job.get('company', 'Unknown Company')}",
            font=ctk.CTkFont(size=12)
        )
        company_label.pack(anchor="w", padx=10, pady=(5, 0))
        
        # These widgets will be shown/hidden based on collapsed view
        detail_widgets = []
        
        # Location
        location_label = ctk.CTkLabel(
            job_frame, 
            text=f"Location: {job.get('location', 'Unknown Location')}",
            font=ctk.CTkFont(size=12)
        )
        location_label.pack(anchor="w", padx=10, pady=(5, 0))
        detail_widgets.append(location_label)
        
        # Source and date
        source_date_label = ctk.CTkLabel(
            job_frame, 
            text=f"Source: {job.get('source', 'Unknown')} | Date: {job.get('scraped_date', 'Unknown')}",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray70")
        )
        source_date_label.pack(anchor="w", padx=10, pady=(5, 0))
        detail_widgets.append(source_date_label)
        
        # Salary estimation placeholder (initially hidden)
        salary_frame = ctk.CTkFrame(job_frame, fg_color="transparent")
        salary_frame.pack(fill="x", padx=10, pady=(5, 10))
        job_frame.salary_frame = salary_frame
        
        # Store this frame with the job data and its detail widgets for filtering and collapsing
        job_frame.job_data = job
        job_frame.detail_widgets = detail_widgets
        job_frame.has_salary = False  # Flag to track if salary has been evaluated
        self.job_frames.append(job_frame)
        
        # Check if job already has salary data (from previous evaluation)
        if 'estimated_salary' in job and 'estimated_fee' in job:
            # Job already has salary data, display it
            job_frame.has_salary = True
            salary_label = ctk.CTkLabel(
                job_frame.salary_frame,
                text=f"Estimated Salary: {job['estimated_salary']:,.2f} EUR",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("green4", "green3")
            )
            salary_label.pack(anchor="w")
            
            fee_label = ctk.CTkLabel(
                job_frame.salary_frame,
                text=f"Estimated Fee (25%): {job['estimated_fee']:,.2f} EUR",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("royalblue3", "royalblue2")
            )
            fee_label.pack(anchor="w")
        
        return job_frame
        
    def filter_jobs(self, filter_text=None, date_filter=None):
        """Filter job listings based on search text and/or date filter.
        
        Args:
            filter_text: Text to search for in job fields (if None, uses current filter)
            date_filter: Date filter option (e.g., "Last week", "Last month")
        """
        # Update filters if provided
        if filter_text is not None:
            self.current_filter = filter_text.lower()
            
        if date_filter is not None:
            self.date_filter = date_filter
        
        # Show/hide job frames based on combined filters
        for frame in self.job_frames:
            job_data = frame.job_data
            
            # Check text filter match
            text_match = self._matches_text_filter(job_data)
            
            # Check date filter match
            date_match = self._matches_date_filter(job_data)
            
            # Only show if both filters match
            if text_match and date_match:
                frame.pack(fill="x", padx=12, pady=7, expand=True)
            else:
                frame.pack_forget()
                
    def _matches_text_filter(self, job_data):
        """Check if a job matches the current text filter."""
        if not self.current_filter:
            return True
            
        # Extract fields to search
        title = job_data.get("title", "").lower()
        company = job_data.get("company", "").lower()
        location = job_data.get("location", "").lower()
        source = job_data.get("source", "").lower()
        description = job_data.get("description", "").lower() if "description" in job_data else ""
        
        # Check if filter text appears in any field
        return (self.current_filter in title or 
                self.current_filter in company or 
                self.current_filter in location or
                self.current_filter in source or
                self.current_filter in description)
                
    def _matches_date_filter(self, job_data):
        """Check if a job matches the current date filter."""
        # If no date filter is set, show all jobs
        if not self.date_filter or self.date_filter == "Any time":
            return True
            
        # Get job date and convert to datetime
        job_date_str = job_data.get('scraped_date', '')
        if not job_date_str:
            return True  # Include jobs without dates to be safe
            
        try:
            job_date = datetime.strptime(job_date_str, '%Y-%m-%d').date()
            today = datetime.now().date()
            days_ago = (today - job_date).days
            
            # Apply date filters
            if self.date_filter == "Last 24 hours":
                return days_ago <= 1
            elif self.date_filter == "Last week":
                return days_ago <= 7
            elif self.date_filter == "Last 2 weeks":
                return days_ago <= 14
            elif self.date_filter == "Last month":
                return days_ago <= 31
            else:
                return True
        except (ValueError, TypeError):
            # If date parsing fails, include the job
            return True
                
    def toggle_collapsed_view(self, collapsed: bool):
        """Toggle between collapsed and expanded view for all job listings."""
        self.collapsed_view = collapsed
        
        # Show/hide detail widgets based on collapsed state
        for frame in self.job_frames:
            if hasattr(frame, 'detail_widgets'):
                for widget in frame.detail_widgets:
                    if collapsed:
                        widget.pack_forget()
                    else:
                        # Re-add the widgets in their original order
                        if widget in frame.winfo_children():
                            if isinstance(widget, ctk.CTkLabel) and "Location:" in widget._text:
                                widget.pack(anchor="w", padx=10, pady=(5, 0))
                            elif isinstance(widget, ctk.CTkLabel):
                                widget.pack(anchor="w", padx=10, pady=(5, 0))
                
                # Always keep salary info visible if it exists
                if hasattr(frame, 'salary_frame') and frame.has_salary:
                    frame.salary_frame.pack(fill="x", padx=10, pady=(5, 10))
    
    def _evaluate_job(self, job: Dict[str, Any], job_frame: ctk.CTkFrame):
        """Evaluate the expected salary for a job and display it on the job frame."""
        # Don't re-evaluate if already done
        if job_frame.has_salary:
            return
        
        # Check if OpenAI client is set up
        global openai_client
        if not openai_client:
            # Ask for API key if not configured
            self._request_api_key(job, job_frame)
            return
            
        # Get the job details
        job_title = job.get("title", "")
        company = job.get("company", "")
        
        # Show evaluation is in progress
        progress_label = ctk.CTkLabel(
            job_frame.salary_frame,
            text="Evaluating salary...",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray70")
        )
        progress_label.pack(anchor="w")
        
        # Update the UI to show the progress
        self.update_idletasks()
        
        # Run evaluation in a thread to avoid freezing UI
        def evaluate_thread():
            # Get salary estimate
            salary, currency = evaluate_salary(job_title, company)
            
            # Calculate 25% fee
            fee = salary * 0.25
            
            # Update UI in main thread
            self.after(0, lambda: self._update_salary_display(
                job_frame, progress_label, salary, fee, currency))
        
        threading.Thread(target=evaluate_thread, daemon=True).start()
    
    def _request_api_key(self, job: Dict[str, Any], job_frame: ctk.CTkFrame):
        """Request OpenAI API key from user."""
        # Create a dialog to get the API key
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("OpenAI API Key Required")
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        dialog.transient(self.master)  # Make dialog modal
        dialog.grab_set()
        
        # Center the dialog on the parent window
        dialog.update_idletasks()
        x = self.master.winfo_rootx() + (self.master.winfo_width() - dialog.winfo_width()) // 2
        y = self.master.winfo_rooty() + (self.master.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Title
        title_label = ctk.CTkLabel(
            dialog,
            text="OpenAI API Key Required",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title_label.pack(pady=(20, 5))
        
        # Description
        desc_label = ctk.CTkLabel(
            dialog,
            text="To evaluate job salaries, please enter your OpenAI API key.",
            wraplength=350
        )
        desc_label.pack(pady=(0, 10))
        
        # API Key entry
        key_var = tk.StringVar()
        key_entry = ctk.CTkEntry(dialog, width=300, textvariable=key_var, show="*")
        key_entry.pack(pady=10)
        
        # Status label (hidden initially)
        status_var = tk.StringVar()
        status_label = ctk.CTkLabel(
            dialog,
            textvariable=status_var,
            text_color=("red", "red"),
            font=ctk.CTkFont(size=10)
        )
        status_label.pack(pady=(0, 10))
        status_label.pack_forget()
        
        # Buttons frame
        button_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        button_frame.pack(pady=10, fill="x")
        
        # Save function
        def on_save():
            api_key = key_var.get().strip()
            if not api_key:
                status_var.set("Please enter an API key")
                status_label.pack(pady=(0, 10))
                return
            
            if setup_openai_client(api_key):
                dialog.destroy()
                # Try evaluating again
                self._evaluate_job(job, job_frame)
            else:
                status_var.set("Invalid API key. Please try again.")
                status_label.pack(pady=(0, 10))
        
        # Cancel function
        def on_cancel():
            dialog.destroy()
        
        # Save button
        save_button = ctk.CTkButton(
            button_frame,
            text="Save",
            command=on_save,
            width=100
        )
        save_button.pack(side="left", padx=(50, 10))
        
        # Cancel button
        cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=on_cancel,
            width=100,
            fg_color="#d32f2f",
            hover_color="#b71c1c"
        )
        cancel_button.pack(side="right", padx=(10, 50))
        
        # Focus on the entry
        key_entry.focus_set()
    
    def _update_salary_display(self, job_frame, progress_label, salary, fee, currency):
        """Update the job frame with the salary estimation results."""
        # Clear existing contents of the salary frame
        for widget in job_frame.salary_frame.winfo_children():
            widget.destroy()
        
        # Remove the progress label if it exists
        if progress_label is not None:
            progress_label.destroy()
        
        # Format the salary and fee
        salary_formatted = f"{salary:,.2f} {currency}" if salary > 0 else "Not available"
        fee_formatted = f"{fee:,.2f} {currency}" if salary > 0 else "Not available"
        
        # Create salary label
        salary_label = ctk.CTkLabel(
            job_frame.salary_frame,
            text=f"Estimated Salary: {salary_formatted}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("green4", "green3")
        )
        salary_label.pack(anchor="w")
        
        # Create fee label
        fee_label = ctk.CTkLabel(
            job_frame.salary_frame,
            text=f"Estimated Fee (25%): {fee_formatted}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("royalblue3", "royalblue2")
        )
        fee_label.pack(anchor="w")
        
        # Mark this job as having salary info and store the salary value
        job_frame.has_salary = True
        job_frame.job_data['estimated_salary'] = salary
        job_frame.job_data['estimated_fee'] = fee
        
        # If we're in the process of evaluating all, continue with the next job
        if self.evaluating_all and hasattr(self, 'remaining_jobs') and self.remaining_jobs:
            self._evaluate_next_job()
        # If we've finished evaluating all, sort by salary
        elif self.evaluating_all and hasattr(self, 'remaining_jobs') and not self.remaining_jobs:
            self._finish_evaluate_all()
    
    def _evaluate_next_job(self):
        """Evaluate the next job in the queue during evaluate all process."""
        if not self.evaluating_all or not hasattr(self, 'remaining_jobs') or not self.remaining_jobs:
            return
        
        # Get the next job and frame
        job, job_frame = self.remaining_jobs.pop(0)
        
        # Start the evaluation
        self._evaluate_job(job, job_frame)
    
    def _open_job_url(self, url):
        """Open the job listing URL in the default web browser."""
        if url:
            try:
                logger.info(f"Opening URL in browser: {url}")
                webbrowser.open(url)
            except Exception as e:
                logger.error(f"Error opening URL: {str(e)}")
                # Show error in a messagebox
                from tkinter import messagebox
                messagebox.showerror("Erreur", f"Impossible d'ouvrir l'URL : {str(e)}")
    
    def _finish_evaluate_all(self):
        """Complete the evaluate all process and sort by salary."""
        # Reset the evaluating flag
        self.evaluating_all = False
        
        # Re-enable all evaluate buttons
        for frame in self.job_frames:
            if hasattr(frame, 'evaluate_button'):
                frame.evaluate_button.configure(state="normal")
        
        # Safely find the app instance to call sort by salary
        try:
            # First try direct parent
            if hasattr(self.master, '_sort_by_salary'):
                self.master._sort_by_salary()
                return
                
            # Try to find the main app instance (limited search to avoid infinite loops)
            parent = self.master
            max_depth = 5  # Limit search depth to avoid infinite loops
            depth = 0
            
            while parent is not None and depth < max_depth:
                if hasattr(parent, '_sort_by_salary'):
                    parent._sort_by_salary()
                    return
                parent = parent.master
                depth += 1
                
            # If we couldn't find the app, just log it
            logger.warning("Could not find main app to sort by salary")
            
        except Exception as e:
            # Catch any exceptions to prevent crashes
            logger.error(f"Error in _finish_evaluate_all: {str(e)}")


class JobScraperApp(ctk.CTk):
    """Main application window for the Job Scraper GUI."""
    
    def __init__(self):
        super().__init__()
        
        # Configure the window with better dimensions and title
        self.title("Immobilier Job Finder - Paris")
        self.geometry("1000x800")
        self.minsize(900, 700)
        
        # Set window icon if available
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
            if os.path.exists(icon_path):
                icon = Image.open(icon_path)
                photo = ImageTk.PhotoImage(icon)
                self.wm_iconphoto(True, photo)
        except Exception as e:
            logger.warning(f"Could not load application icon: {e}")
        
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
        
        # App title with better styling
        title_label = ctk.CTkLabel(
            header_frame, 
            text="Immobilier Job Finder", 
            font=ctk.CTkFont(family="Helvetica", size=28, weight="bold")
        )
        title_label.pack(side="left", padx=10)
        
        # Subtitle for context
        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Specialized in Real Estate Investment",
            font=ctk.CTkFont(size=14),
            text_color=("gray40", "gray70")
        )
        subtitle_label.pack(side="left", padx=5, pady=8)
        
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
        sidebar = ctk.CTkFrame(parent, width=280, corner_radius=15, border_width=1, border_color=("gray80", "gray30"))
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 20))
        
        # Settings label with better styling
        settings_label = ctk.CTkLabel(
            sidebar, 
            text="⚙️ Scraper Settings",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        settings_label.pack(anchor="w", padx=15, pady=(20, 15))
        
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
        
        # Date filter
        date_filter_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        date_filter_frame.pack(fill="x", padx=15, pady=5)
        
        date_filter_label = ctk.CTkLabel(
            date_filter_frame, 
            text="📅 Date Filter:",
            font=ctk.CTkFont(weight="bold")
        )
        date_filter_label.grid(row=0, column=0, sticky="w", pady=5)
        
        self.date_filter_var = tk.StringVar(value="Any time")
        date_filter_options = [
            "Any time", 
            "Last 24 hours", 
            "Last week", 
            "Last 2 weeks", 
            "Last month"
        ]
        date_filter_dropdown = ctk.CTkOptionMenu(
            date_filter_frame,
            values=date_filter_options,
            variable=self.date_filter_var,
            command=self._on_date_filter_changed,
            width=140,
            fg_color=("#3a7ebf", "#1f538d"),
            button_color=("#2d6db5", "#1a477a"),
            button_hover_color=("#2a65a7", "#164570")
        )
        date_filter_dropdown.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        date_filter_frame.grid_columnconfigure(1, weight=1)
        
        # Sites to scrape with better styling
        sites_label = ctk.CTkLabel(
            sidebar, 
            text="🔍 Sites to Scrape:",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        sites_label.pack(anchor="w", padx=15, pady=(20, 10))
        
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
        
        # Control buttons with improved styling and icons
        # Start scraping button
        self.start_button = ctk.CTkButton(
            button_frame, 
            text="▶️ Start Scraping",
            command=self.start_scraping,
            fg_color=("#2e8b57", "#1e5631"),  # Better shade of green
            hover_color=("#227346", "#19472a"),
            corner_radius=10,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            border_width=1,
            border_color=("gray80", "gray30")
        )
        self.start_button.pack(fill="x", pady=(0, 8))
        
        # Stop scraping button (disabled by default)
        self.stop_button = ctk.CTkButton(
            button_frame, 
            text="⏹️ Stop Scraping",
            command=self.stop_scraping,
            fg_color=("#c0392b", "#7f1d1d"),  # Better shade of red
            hover_color=("#962d22", "#630e0e"),
            corner_radius=10,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
            border_width=1,
            border_color=("gray80", "gray30")
        )
        self.stop_button.pack(fill="x", pady=(0, 8))
        
        # Load results button
        self.load_button = ctk.CTkButton(
            button_frame, 
            text="📂 Load Results",
            command=self.load_results,
            fg_color=("#3a7ebf", "#1f538d"),  # Better shade of blue
            hover_color=("#2d6db5", "#1a477a"),
            corner_radius=10,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            border_width=1,
            border_color=("gray80", "gray30")
        )
        self.load_button.pack(fill="x", pady=(0, 8))
        
        # Export to Excel button
        self.export_button = ctk.CTkButton(
            button_frame, 
            text="📊 Export to Excel",
            command=self.export_to_excel,
            fg_color=("#8e44ad", "#5b2c6f"),  # Better shade of purple
            hover_color=("#7d3c98", "#4a235a"),
            corner_radius=10,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            border_width=1,
            border_color=("gray80", "gray30")
        )
        self.export_button.pack(fill="x", pady=(0, 8))
    
    def create_job_listings(self, parent):
        """Create the area for displaying job listings."""
        # Container frame
        listings_frame = ctk.CTkFrame(parent)
        listings_frame.grid(row=0, column=1, sticky="nsew")
        listings_frame.grid_columnconfigure(0, weight=1)
        listings_frame.grid_rowconfigure(0, weight=0)  # Header 
        listings_frame.grid_rowconfigure(1, weight=1)  # Listings area
        
        # Results header with better styling
        results_header = ctk.CTkFrame(listings_frame, fg_color="transparent")
        results_header.grid(row=0, column=0, sticky="ew", padx=25, pady=15)
        results_header.grid_columnconfigure(1, weight=1)  # Make middle space expandable
        
        # Left side - Results count with better styling
        self.results_label = ctk.CTkLabel(
            results_header, 
            text="📋 Job Listings (0 results)",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.results_label.grid(row=0, column=0, sticky="w")
        
        # Right side - Controls frame
        controls_frame = ctk.CTkFrame(results_header, fg_color="transparent")
        controls_frame.grid(row=0, column=2, sticky="e")
        
        # Sort dropdown
        sort_label = ctk.CTkLabel(controls_frame, text="Sort by:")
        sort_label.pack(side="left", padx=(0, 5))
        
        self.sort_var = tk.StringVar(value="Date")
        sort_options = ["Date", "Source", "Company", "Salary"]
        sort_dropdown = ctk.CTkOptionMenu(
            controls_frame,
            values=sort_options,
            variable=self.sort_var,
            command=self._on_sort_changed,
            width=100
        )
        sort_dropdown.pack(side="left", padx=5)
        
        # Sort order toggle
        self.sort_order_var = tk.StringVar(value="↓")
        sort_order_button = ctk.CTkButton(
            controls_frame,
            text=self.sort_order_var.get(),
            command=self._toggle_sort_order,
            width=30
        )
        sort_order_button.pack(side="left", padx=5)
        
        # Evaluate All button with improved styling
        evaluate_all_button = ctk.CTkButton(
            controls_frame,
            text="💰 Evaluate All",
            command=self._evaluate_all_jobs,
            width=120,
            height=32,
            fg_color=("#2e8b57", "#1e5631"),
            hover_color=("#227346", "#19472a"),
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        evaluate_all_button.pack(side="left", padx=(20, 5))
        
        # Collapsed view switch
        collapsed_label = ctk.CTkLabel(controls_frame, text="Collapsed view:")
        collapsed_label.pack(side="left", padx=(10, 5))
        
        self.collapsed_var = tk.BooleanVar(value=False)
        collapsed_switch = ctk.CTkSwitch(
            controls_frame,
            text="",
            variable=self.collapsed_var,
            command=self._toggle_collapsed_view,
            width=40
        )
        collapsed_switch.pack(side="left")
        
        # Job listings scrollable frame with better styling
        self.jobs_frame = ScrollableJobFrame(listings_frame)
        self.jobs_frame.grid(row=1, column=0, sticky="nsew", padx=25, pady=(0, 25))
    
    def create_status_bar(self):
        """Create the status bar at the bottom of the UI."""
        status_bar = ctk.CTkFrame(self, height=30, corner_radius=0, border_width=1, border_color=("gray85", "gray25"))
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
        
    def _on_date_filter_changed(self, selected_option):
        """Handle changes to the date filter dropdown."""
        # Apply the filter to current job listings
        if self.job_data:
            self.jobs_frame.filter_jobs(date_filter=selected_option)
            
            # Count visible jobs to update result count
            visible_count = sum(1 for frame in self.jobs_frame.job_frames if frame.winfo_viewable())
            self.results_label.configure(text=f"📋 Job Listings ({visible_count} filtered results)")
    
    def _on_search_changed(self, *args):
        """Handle changes to the search bar."""
        search_text = self.search_var.get()
        self.jobs_frame.filter_jobs(text=search_text)
    
    def _on_sort_changed(self, selected_option):
        """Handle changes to the sort dropdown."""
        # Map the user-friendly option to the corresponding job data field
        sort_key_map = {
            "Date": "scraped_date",
            "Source": "source",
            "Company": "company",
            "Salary": "estimated_salary"
        }
        
        # Update the sort key in the jobs frame
        self.jobs_frame.sort_key = sort_key_map.get(selected_option, "scraped_date")
        
        # Re-sort and update the job listings
        self.update_job_listings(self.job_data)
    
    def _evaluate_all_jobs(self):
        """Evaluate salaries for all jobs and then sort by estimated salary."""
        if not self.job_data:
            self.update_status("No jobs to evaluate. Please load or scrape jobs first.")
            return
        
        # Check if OpenAI client is set up
        global openai_client
        if not openai_client:
            self.update_status("OpenAI API not configured. Cannot evaluate salaries.")
            return
        
        self.update_status("Evaluating all jobs...")
        
        # Set evaluating flag
        self.jobs_frame.evaluating_all = True
        
        # Get all jobs that don't have salary estimates yet
        jobs_to_evaluate = []
        for frame in self.jobs_frame.job_frames:
            if not frame.has_salary:
                jobs_to_evaluate.append((frame.job_data, frame))
        
        if not jobs_to_evaluate:
            self.update_status("All jobs already evaluated!")
            # Sort by salary anyway
            self._sort_by_salary()
            return
        
        # Store remaining jobs to evaluate
        self.jobs_frame.remaining_jobs = jobs_to_evaluate
        
        # Disable all evaluate buttons to prevent multiple evaluations
        for frame in self.jobs_frame.job_frames:
            if hasattr(frame, 'evaluate_button'):
                frame.evaluate_button.configure(state="disabled")
        
        # Start evaluating the first job
        self.jobs_frame._evaluate_next_job()
    
    def _sort_by_salary(self):
        """Sort the job listings by estimated salary."""
        # Change sort option to Salary
        self.sort_var.set("Salary")
        self.jobs_frame.sort_key = "estimated_salary"
        self.jobs_frame.sort_ascending = False  # Higher salaries first
        self.sort_order_var.set("↓")
        
        # Re-sort and update the job listings
        self.update_job_listings(self.job_data)
    
    def _toggle_sort_order(self):
        """Toggle between ascending and descending sort order."""
        self.jobs_frame.sort_ascending = not self.jobs_frame.sort_ascending
        
        # Update the button text to indicate sort direction
        self.sort_order_var.set("↑" if self.jobs_frame.sort_ascending else "↓")
        
        # Re-sort and update the job listings
        self.update_job_listings(self.job_data)
    
    def _toggle_collapsed_view(self):
        """Toggle between collapsed and expanded view for job listings."""
        collapsed = self.collapsed_var.get()
        self.jobs_frame.toggle_collapsed_view(collapsed)
    
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
    
    def sort_jobs(self, jobs: List[Dict[str, Any]]):
        """Sort the job listings based on the current sort key and order."""
        # Make a copy of the list to avoid modifying the original
        sorted_jobs = jobs.copy()
        
        # Default value for missing keys
        default_values = {
            "scraped_date": "Unknown",
            "source": "Unknown",
            "company": "Unknown",
            "estimated_salary": 0  # Default for estimated salary
        }
        
        # Special handling for different sort keys
        if self.jobs_frame.sort_key == "scraped_date":
            # Try to parse the date string, fallback to string comparison if parsing fails
            def get_date_key(job):
                date_str = job.get("scraped_date", default_values["scraped_date"])
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except (ValueError, TypeError):
                    # If date format is different or parsing fails, use string
                    return date_str
            
            key_func = get_date_key
        elif self.jobs_frame.sort_key == "estimated_salary":
            # Sort by the estimated salary (numeric value)
            key_func = lambda job: job.get("estimated_salary", default_values["estimated_salary"])
        else:
            # For other fields, use simple string comparison
            sort_key = self.jobs_frame.sort_key
            key_func = lambda job: job.get(sort_key, default_values.get(sort_key, "")).lower()
        
        # Sort the jobs
        sorted_jobs.sort(key=key_func, reverse=not self.jobs_frame.sort_ascending)
        
        return sorted_jobs
        
    def update_job_listings(self, jobs: List[Dict[str, Any]]):
        """Update the job listings display with the provided job data."""
        # Store reference to any jobs that had salary evaluations
        evaluated_jobs = {}
        for frame in self.jobs_frame.job_frames:
            if hasattr(frame, 'has_salary') and frame.has_salary and hasattr(frame, 'job_data'):
                # Use job title and company as a unique key
                job_key = (frame.job_data.get('title', ''), frame.job_data.get('company', ''))
                # Store the estimated salary and fee
                evaluated_jobs[job_key] = {
                    'estimated_salary': frame.job_data.get('estimated_salary', 0),
                    'estimated_fee': frame.job_data.get('estimated_fee', 0)
                }
        
        # Clear existing listings
        self.jobs_frame.clear_jobs()
        
        # Update results count
        self.results_label.configure(text=f"Job Listings ({len(jobs)} results)")
        
        # Sort the jobs based on current sort key
        sorted_jobs = self.sort_jobs(jobs)
        
        # Add each job to the scrollable frame and restore salary data if available
        for job in sorted_jobs:
            # Check if this job had salary evaluation
            job_key = (job.get('title', ''), job.get('company', ''))
            if job_key in evaluated_jobs:
                # Restore the salary and fee data
                job['estimated_salary'] = evaluated_jobs[job_key]['estimated_salary']
                job['estimated_fee'] = evaluated_jobs[job_key]['estimated_fee']
            
            # Add the job to the frame
            job_frame = self.jobs_frame.add_job(job)
            
            # If this job had salary data, trigger salary display
            if job_key in evaluated_jobs and job_frame is not None:
                # Access salary frame and update it
                self.jobs_frame._update_salary_display(
                    job_frame, 
                    None,  # No progress label needed
                    job['estimated_salary'],
                    job['estimated_fee'],
                    "EUR"
                )
            
        # Apply collapsed view if enabled
        if self.jobs_frame.collapsed_view:
            self.jobs_frame.toggle_collapsed_view(True)
            
        # Apply current filters (both search text and date)
        search_text = self.search_var.get()
        date_filter = self.date_filter_var.get()
        
        # Apply both filters at once
        self.jobs_frame.filter_jobs(filter_text=search_text, date_filter=date_filter)
    
    def start_scraping(self):
        """Start the job scraping process."""
        if self.is_scraping:
            return
        
        # Get settings from UI
        query_fr = self.query_fr_var.get()
        query_en = self.query_en_var.get()
        location = self.location_var.get()
        max_pages = self.max_pages_var.get()
        
        # Get date filter selection from UI
        date_filter = None
        selected_date_filter = self.date_filter_var.get()
        if selected_date_filter != "Any time":
            # Convert UI date filter to scraper date filter format
            date_filter_map = {
                "Last 24 hours": "1day",
                "Last week": "1week",
                "Last 2 weeks": "2weeks",
                "Last month": "1month"
            }
            date_filter = date_filter_map.get(selected_date_filter)
            logger.info(f"Using date filter: {date_filter}")
        
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
            args=(query_fr, query_en, location, max_pages, sites_to_scrape, date_filter)
        )
        self.scraping_thread.daemon = True
        self.scraping_thread.start()
    
    def _run_scraper(self, query_fr, query_en, location, max_pages, sites_to_scrape, date_filter=None):
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
                max_runtime=3600,  # 1 hour max runtime
                date_filter=date_filter  # Pass the date filter to the scraper
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
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"real_estate_jobs_{location.lower().replace(' ', '_')}_{timestamp}.json"
            
            # First, save to the timestamped file directly
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(self.scraper.jobs, f, ensure_ascii=False, indent=2)
                
            # Then use save_to_json for the default file which handles proper merging with existing jobs
            self.scraper.save_to_json(filename="real_estate_jobs_paris.json")
            
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
