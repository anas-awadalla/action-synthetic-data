#!/usr/bin/env python3
import json
import random
import webbrowser
import os
import sys

def load_websites(json_file):
    """Load websites from JSON file and return a list of all URLs."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract all URLs from the nested structure
        all_urls = []
        for category in data.values():
            if isinstance(category, dict):
                all_urls.extend(category.values())
        
        print(f"Loaded {len(all_urls)} websites from {json_file}")
        return all_urls
    except FileNotFoundError:
        print(f"Error: File '{json_file}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: '{json_file}' is not a valid JSON file.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

def open_random_website(urls):
    """Select a random URL from the list and open it in the default browser."""
    if not urls:
        print("No URLs found in the file.")
        return
    
    # Choose a random URL
    random_url = random.choice(urls)
    print(f"Opening: {random_url}")
    
    # Open the URL in the default browser
    webbrowser.open(random_url)

def main():
    # Default location of the seed_websites.json file
    json_file = "seed_websites.json"
    
    # Allow specifying a different file as command-line argument
    if len(sys.argv) > 1:
        json_file = sys.argv[1]
    
    # Ensure the file path is valid
    if not os.path.isfile(json_file):
        print(f"Error: '{json_file}' does not exist or is not a file.")
        sys.exit(1)
    
    # Load websites and open a random one
    urls = load_websites(json_file)
    open_random_website(urls)

if __name__ == "__main__":
    main() 